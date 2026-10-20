"""Quality must not duplicate tests or lose mandatory checks."""

import unittest

from scripts.quality import commands


def test_changed_runner_has_one_unit_owner_in_product_selection() -> None:
    from pathlib import Path

    from scripts.vendor import base_quality_selection as selection

    root = Path(__file__).resolve().parents[1]
    for path in ("scripts/quality.py", "Makefile", "tests/test_quality_runner.py"):
        candidate = selection.plan(root, profile="unit", changed=[path])
        assert [gate["id"] for gate in candidate["gates"]] == ["backend:unit"]
    assert "tests/test_quality_runner.py" in commands("unit")[0]
    assert selection.plan(root, profile="unit", changed=["README.md"])["gates"] == []


def test_docs_only_ci_does_not_prepare_python_dependencies() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    docs_job = source.split("\n  docs:\n", 1)[1].split("\n  quality:\n", 1)[0]
    assert "python scripts/verify_readme.py" in docs_job
    assert "setup-uv" not in docs_job
    assert "quality.py" not in docs_job


def test_uv_binary_environment_does_not_replace_the_canonical_runner(monkeypatch) -> None:
    monkeypatch.delenv("WORKFLOW_QUALITY_UV", raising=False)
    monkeypatch.setenv("UV", "/installed/uv")
    assert "--frozen" in commands("coverage")[0]
    assert "--with-requirements" in commands("coverage")[0]


def test_release_runs_full_coverage_once_and_postgres_separately() -> None:
    selected = commands("release")
    tests = [command for command in selected if "pytest" in command]
    assert len(tests) == 2
    assert sum("--cov=project_workflow" in command for command in tests) == 1
    coverage = next(command for command in tests if "--cov=project_workflow" in command)
    assert "error::ResourceWarning" in coverage
    assert "error::pytest.PytestUnraisableExceptionWarning" in coverage
    assert coverage[coverage.index("-n") + 1] == "2"
    assert "--dist=load" in coverage
    integration = next(command for command in tests if "postgres" in command)
    assert "-n" not in integration
    assert any("postgres" in command and "tests/test_postgres_integration.py" in command for command in tests)
    assert all("--durations=25" in command for command in tests)
    assert any("ruff" in command for command in selected)
    assert any("mypy" in command for command in selected)
    assert ["git", "diff", "--check"] in selected


def test_standalone_test_remains_available_without_coverage() -> None:
    selected = commands("test")
    assert len(selected) == 1
    assert "pytest" in selected[0]
    assert "--cov=project_workflow" not in selected[0]


def test_make_powershell_and_ci_delegate_to_product_quality_entrypoint() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert "scripts/quality.py" in (root / "Makefile").read_text(encoding="utf-8")
    assert "quality.py" in (root / "scripts/quality.ps1").read_text(encoding="utf-8")
    assert "make quality" in (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def test_default_unit_collection_uses_the_reviewed_files_only() -> None:
    import json
    from pathlib import Path

    lanes = json.loads(Path(__file__).with_name("lanes.json").read_text(encoding="utf-8"))
    expected = {"tests/" + name for name in lanes["unit"]}
    for target in ("unit", "test", "quality", "warnings"):
        selected = next(command for command in commands(target) if "pytest" in command)
        actual = {arg for arg in selected if arg.startswith("tests/")}
        assert actual == expected
    release = commands("release")
    coverage = next(command for command in release if "--cov=project_workflow" in command)
    assert not any(arg.startswith("tests/") for arg in coverage)


def test_verbose_unit_uses_the_same_reviewed_collection_and_entrypoints() -> None:
    from pathlib import Path

    from scripts.quality import TARGETS

    assert "test-verbose" in TARGETS
    normal = commands("unit")[0]
    verbose = commands("test-verbose")[0]
    assert verbose == ["-v" if argument == "-q" else argument for argument in normal]
    root = Path(__file__).resolve().parents[1]
    make = (root / "Makefile").read_text(encoding="utf-8")
    header = next(line for line in make.splitlines() if line.startswith("test unit "))
    assert "test-verbose" in header.split()
    assert "\ntest-verbose:\n" not in make
    assert "'test-verbose'" in (root / "scripts/quality.ps1").read_text(encoding="utf-8")


def test_verbose_entrypoint_never_collects_integration_modules(tmp_path) -> None:
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    import pytest

    from scripts.quality import unit_test_paths

    if sys.version_info[:3] != (3, 11, 15):
        pytest.skip("Prepared entrypoint requires the product's Python 3.11.15")
    plugin = tmp_path / "unit_collection_guard.py"
    report = tmp_path / "collection.json"
    plugin.write_text(
        "import json, os, pytest\n"
        "from pathlib import Path\n"
        "seen = set()\n"
        "def pytest_configure(config):\n"
        "    original = pytest.Module._getobj\n"
        "    def guarded(module):\n"
        "        assert module.path.name not in {'test_ui.py', 'test_postgres_integration.py'}\n"
        "        seen.add(module.path.name)\n"
        "        return original(module)\n"
        "    pytest.Module._getobj = guarded\n"
        "def pytest_collection_finish(session):\n"
        "    Path(os.environ['UNIT_COLLECTION_REPORT']).write_text(json.dumps({\n"
        "        'files': sorted(seen), 'items': len(session.items)}))\n",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "PYTHONPATH": str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "PYTEST_PLUGINS": "unit_collection_guard",
        "PYTEST_ADDOPTS": "--collect-only",
        "UNIT_COLLECTION_REPORT": str(report),
    }
    result = subprocess.run(
        [sys.executable, "scripts/quality.py", "--prepared", "test-verbose"],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    collected = json.loads(report.read_text(encoding="utf-8"))
    assert collected["files"] == sorted(Path(path).name for path in unit_test_paths())
    assert collected["items"] > 0


def test_explicit_scoped_arguments_keep_the_original_pytest_selection(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    from scripts import quality

    captured = []
    monkeypatch.setattr(sys, "argv", ["quality.py", "unit", "--", "tests/test_phase_graph.py"])
    monkeypatch.setattr(
        quality.subprocess, "run",
        lambda command, **_kwargs: (captured.append(command) or SimpleNamespace(returncode=0)),
    )
    assert quality.main() == 0
    assert {arg for arg in captured[0] if arg.startswith("tests/")} == {"tests/test_phase_graph.py"}


def test_scoped_unit_defaults_are_decided_by_pytest_before_collection(tmp_path) -> None:
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    import pytest

    from scripts.quality import unit_test_paths

    if sys.version_info[:3] != (3, 11, 15):
        pytest.skip("Prepared entrypoint requires the product's Python 3.11.15")
    reviewed = sorted(Path(path).name for path in unit_test_paths())
    plugin = tmp_path / "scoped_collection_guard.py"
    report = tmp_path / "collection.json"
    plugin.write_text(
        "import json, os, pytest\n"
        "from pathlib import Path\n"
        "seen = set()\n"
        "def pytest_configure(config):\n"
        "    original = pytest.Module._getobj\n"
        "    def guarded(module):\n"
        "        assert module.path.name in json.loads(os.environ['REVIEWED_UNIT_FILES'])\n"
        "        seen.add(module.path.name)\n"
        "        return original(module)\n"
        "    pytest.Module._getobj = guarded\n"
        "def pytest_collection_finish(session):\n"
        "    Path(os.environ['UNIT_COLLECTION_REPORT']).write_text(json.dumps({\n"
        "        'files': sorted(seen), 'items': len(session.items)}))\n",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "PYTHONPATH": str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "PYTEST_PLUGINS": "scoped_collection_guard",
        "PYTEST_ADDOPTS": "--collect-only",
        "UNIT_COLLECTION_REPORT": str(report),
        "REVIEWED_UNIT_FILES": json.dumps(reviewed),
    }
    cases = [
        (["-k", "default_unit_collection", "--maxfail=1"], reviewed, 0),
        (["-k", "default_unit_collection", "tests/test_quality_runner.py"], ["test_quality_runner.py"], 0),
        (["tests/test_quality_runner.py::test_default_unit_collection_uses_the_reviewed_files_only", "-q"],
         ["test_quality_runner.py"], 0),
        # A file-shaped option value is still an expression, not a path scope.
        (["-k", "tests/test_quality_runner.py"], reviewed, 5),
    ]
    for extra, expected_files, expected_exit in cases:
        report.unlink(missing_ok=True)
        result = subprocess.run(
            [sys.executable, "scripts/quality.py", "--prepared", "unit", "--", *extra],
            cwd=Path(__file__).resolve().parents[1], env=environment,
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
        )
        assert result.returncode == expected_exit, result.stdout + result.stderr
        collected = json.loads(report.read_text(encoding="utf-8"))
        assert collected["files"] == expected_files
        assert collected["items"] == (0 if expected_exit == 5 else 1)


def test_empty_or_invalid_unit_list_never_falls_back_to_full_collection(monkeypatch) -> None:
    import pytest

    from scripts import quality

    for names in ([], "test_domain_entities.py", ["../outside.py"], ["missing.py"], [3]):
        with monkeypatch.context() as context:
            context.setattr(quality.json, "loads", lambda _text: {"unit": names})
            with pytest.raises(ValueError, match="Unit lane"):
                commands("unit")


def test_prepared_operation_reuses_one_interpreter_without_uv_resync() -> None:
    import sys

    selected = commands("quality", prepared=True)
    tools = [command for command in selected if command != ["git", "diff", "--check"]]
    assert len(tools) == 3
    assert all(command[:2] == [sys.executable, "-m"] for command in tools)
    assert {command[2] for command in tools} == {"pytest", "ruff", "mypy"}


def test_quality_bootstrap_prepares_once_for_multiple_tools(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    from scripts import quality

    calls = []
    monkeypatch.delenv("WORKFLOW_QUALITY_UV", raising=False)
    monkeypatch.setattr(sys, "argv", ["quality.py", "quality"])
    monkeypatch.setattr(quality.subprocess, "run", lambda command, **_kwargs: (
        calls.append(command) or SimpleNamespace(returncode=0)))
    assert quality.main() == 0
    assert len(calls) == 1
    assert calls[0].count("--prepared") == 1
    assert calls[0][-1] == "quality"


class ComponentSelectionContracts(unittest.TestCase):
    """Use the packaged selector shared by local entrypoints and hosted CI."""

    def test_frontend_assets_and_navigation_runner_select_only_node_units(self):
        from pathlib import Path

        from scripts.vendor import base_quality_selection as selection

        root = Path(__file__).resolve().parents[1]
        for path in (
            "project_workflow/interfaces/ui/templates/profession-navigation.js",
            "project_workflow/interfaces/ui/templates/namespaces.html",
            "project_workflow/interfaces/ui/templates/base/base-ui.css",
            "project_workflow/interfaces/ui/templates/base/platform-navigation.js",
            "scripts/test_profession_navigation.mjs",
        ):
            with self.subTest(path=path):
                plan = selection.plan(root, profile="unit", changed=[path])
                self.assertEqual(["frontend"], plan["components"])
                self.assertEqual(["frontend:navigation"], [gate["id"] for gate in plan["gates"]])

    def test_python_and_backend_data_keep_units_without_navigation(self):
        from pathlib import Path

        from scripts.vendor import base_quality_selection as selection

        root = Path(__file__).resolve().parents[1]
        for path in (
            "project_workflow/domain/entities.py",
            "project_workflow/interfaces/ui/__main__.py",
            "project_workflow/interfaces/ui/templates.py",
            "project_workflow/interfaces/cli/commands.py",
            "project_workflow/references/base_sdlc_catalog_v2.json",
            "scripts/quality.py", "tests/test_quality_runner.py", "uv.lock",
        ):
            with self.subTest(path=path):
                plan = selection.plan(root, profile="unit", changed=[path])
                self.assertEqual(["backend"], plan["components"])
                self.assertEqual(["backend:unit"], [gate["id"] for gate in plan["gates"]])

    def test_shared_mixed_and_unknown_inputs_keep_both_consumers(self):
        from pathlib import Path

        from scripts.vendor import base_quality_selection as selection

        root = Path(__file__).resolve().parents[1]
        for paths in (
            [".github/workflows/ci.yml"], ["openapi/openapi.json"],
            ["project_workflow/new-component/unknown.bin"],
            ["project_workflow/domain/entities.py", "scripts/test_profession_navigation.mjs"],
        ):
            with self.subTest(paths=paths):
                plan = selection.plan(root, profile="unit", changed=paths)
                self.assertEqual({"backend", "frontend"}, set(plan["components"]) - {"docs"})
                self.assertEqual({"backend:unit", "frontend:navigation"}, {gate["id"] for gate in plan["gates"]})

    def test_hosted_outputs_use_the_same_path_ownership(self):
        from pathlib import Path
        from unittest.mock import patch

        from scripts.vendor import base_quality_selection as selection

        root = Path(__file__).resolve().parents[1]
        for path, expected in (
            ("scripts/test_profession_navigation.mjs", {"backend": "false", "frontend": "true"}),
            ("project_workflow/interfaces/ui/templates/profession-navigation.js",
             {"backend": "false", "frontend": "true"}),
            ("project_workflow/domain/entities.py", {"backend": "true", "frontend": "false"}),
            (".github/workflows/ci.yml", {"backend": "true", "frontend": "true"}),
            ("unknown-input.bin", {"backend": "true", "frontend": "true"}),
        ):
            with self.subTest(path=path), patch.object(selection, "git", return_value=path):
                actual = selection.classify("pull_request", "1" * 40, "2" * 40, repo=root)
                self.assertEqual(expected, actual)

    def test_hosted_preparation_and_commands_follow_their_component(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        source = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        steps = source.split("\n  quality:\n", 1)[1].split("\n      - ")[1:]
        backend = "if: needs.changes.outputs.backend == 'true'"
        frontend = "if: needs.changes.outputs.frontend == 'true'"
        for identity in (
            "Read independent Base SDK contract revision", "Check out pinned Base SDK source",
            "Verify generated dependency-free namespace contract", "astral-sh/setup-uv@",
            "Fast unit gate and static analysis",
        ):
            with self.subTest(step=identity):
                step = next(step for step in steps if identity in step)
                self.assertIn(backend, step)
        navigation = next(step for step in steps if "Profession and platform navigation regression" in step)
        self.assertIn(frontend, navigation)
        self.assertIn("run: node tests/node/test_navigation_inputs.mjs", navigation)
        self.assertEqual(1, source.count("run: make quality"))
        self.assertIn("--revision .base-revision", source)
        self.assertIn("export_python_namespace.py", source)
