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


class CoverageEntrypointContracts(unittest.TestCase):
    """Source/protocol controls without pytest collection, application imports or uv."""

    def test_html_coverage_prepares_once_in_the_canonical_environment(self):
        import os
        import sys
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch

        from scripts import quality

        for override in (None, str(Path.cwd() / "owned-quality-fixture")):
            with self.subTest(override=override):
                preparation, executions = [], []
                environment = dict(os.environ)
                environment.pop("WORKFLOW_QUALITY_UV", None)
                environment.pop("WORKFLOW_QUALITY_ENVIRONMENT", None)
                environment.update(UV_PROJECT_ENVIRONMENT="foreign-workspace-underlay", VIRTUAL_ENV="foreign-venv")
                if override:
                    environment["WORKFLOW_QUALITY_ENVIRONMENT"] = override

                def inert_run(command, **kwargs):
                    if command[0] == "uv":
                        preparation.append((command, kwargs["env"]))
                        child_args = command[command.index("--prepared"):]
                        with patch.object(sys, "argv", ["quality.py", *child_args]), \
                                patch.object(sys, "version_info", (3, 11, 15)):
                            return SimpleNamespace(returncode=quality.main())
                    executions.append((command, kwargs["env"]))
                    return SimpleNamespace(returncode=0)

                with patch.dict(os.environ, environment, clear=True), \
                        patch.object(sys, "argv", ["quality.py", "coverage-html"]), \
                        patch.object(quality.subprocess, "run", side_effect=inert_run):
                    self.assertEqual(0, quality.main())
                self.assertEqual(1, len(preparation))
                self.assertEqual(1, len(executions))
                expected = override or str(
                    Path(quality.__file__).resolve().parents[1] / ".local/quality-python" / os.name / "3.11.15"
                )
                for _, child_environment in preparation + executions:
                    self.assertEqual(expected, child_environment["UV_PROJECT_ENVIRONMENT"])
                    self.assertNotIn("VIRTUAL_ENV", child_environment)
                command = executions[0][0]
                self.assertEqual([sys.executable, "-m", "pytest"], command[:3])
                self.assertIn("--cov-report=xml", command)
                self.assertIn("--cov-report=html", command)
                self.assertIn("error::ResourceWarning", command)
                self.assertIn("error::pytest.PytestUnraisableExceptionWarning", command)
                self.assertEqual("not postgres", command[command.index("-m", 2) + 1])

    def test_make_coverage_goals_dispatch_one_canonical_operation_in_either_order(self):
        import os
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        make = shutil.which("make")
        bash = (Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
                if os.name == "nt" else Path(shutil.which("bash") or "/missing"))
        if not make or not bash.is_file():
            self.skipTest("GNU Make and native Bash are required for the inert dispatch fixture")
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(source / "Makefile", root / "Makefile")
            (root / "scripts").mkdir()
            (root / "scripts/quality.py").write_text(
                "import sys\nfrom pathlib import Path\n"
                "with Path('calls.txt').open('a') as stream: stream.write(sys.argv[1] + '\\n')\n",
                encoding="utf-8",
            )
            for goals, expected in ((("coverage", "coverage-html"), "coverage-html"),
                                    (("coverage-html", "coverage"), "coverage-html"),
                                    (("coverage",), "coverage"), (("coverage-html",), "coverage-html")):
                with self.subTest(goals=goals):
                    (root / "calls.txt").unlink(missing_ok=True)
                    result = subprocess.run([make, "--no-print-directory", "-j8", *goals, "SHELL=" + bash.as_posix()],
                                            cwd=root, text=True, capture_output=True, timeout=10, check=False)
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertEqual([expected], (root / "calls.txt").read_text().splitlines())

    def test_failed_coverage_preparation_does_not_retry_or_start_tests(self):
        import os
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch

        from scripts import quality

        environment = dict(os.environ)
        environment.pop("WORKFLOW_QUALITY_UV", None)
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(sys, "argv", ["quality.py", "coverage-html"]), \
                patch.object(quality.subprocess, "run", return_value=SimpleNamespace(returncode=7)) as runner:
            self.assertEqual(7, quality.main())
        self.assertEqual(1, runner.call_count)
        self.assertIn("--prepared", runner.call_args.args[0])

    def test_docs_release_job_does_not_repeat_full_coverage_contracts(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
        docs = workflow.split("\n  docs:\n", 1)[1].split("\n  quality:\n", 1)[0]
        self.assertIn("python scripts/verify_readme.py", docs)
        self.assertNotIn("setup-uv", docs)
        self.assertNotIn("quality.py", docs)
        self.assertNotIn("pytest", docs)
        self.assertEqual(1, workflow.count("run: make release"))

    def test_actual_marker_owner_keeps_docs_in_full_manual_coverage(self):
        import ast
        import json
        import tomllib
        from pathlib import Path
        from types import SimpleNamespace

        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "tests/conftest.py").read_text(encoding="utf-8"))
        owner = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == "pytest_collection_modifyitems")
        owner.decorator_list = []
        lanes = json.loads((root / "tests/lanes.json").read_text(encoding="utf-8"))
        namespace = {"Path": Path, "__file__": str(root / "tests/conftest.py"), "_LANES": lanes,
                     "pytest": SimpleNamespace(mark=SimpleNamespace(unit="unit", integration="integration",
                                                                    slow="slow", postgres="postgres"))}
        exec(compile(ast.Module(body=[owner], type_ignores=[]), "marker-owner-fixture", "exec"), namespace)
        observed = {}
        for name in ("test_docs_quality.py", "test_quality_runner.py", lanes["postgres"], lanes["slow"][0]):
            markers = []
            namespace[owner.name]([SimpleNamespace(path=root / "tests" / name, add_marker=markers.append)])
            observed[name] = markers
        self.assertEqual(["integration"], observed["test_docs_quality.py"])
        self.assertEqual(["unit"], observed["test_quality_runner.py"])
        self.assertIn("postgres", observed[lanes["postgres"]])
        self.assertIn("slow", observed[lanes["slow"][0]])
        for target in ("coverage", "coverage-html", "release"):
            command = next(command for command in commands(target) if "--cov=project_workflow" in command)
            self.assertEqual("not postgres", command[command.index("-m") + 1])
            self.assertFalse(any(argument.startswith("tests/") for argument in command))
        policy = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(94, policy["tool"]["coverage"]["report"]["fail_under"])

    def test_documented_ci_contract_matches_current_tiers(self):
        import importlib.util
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "workflow_docs_contract", Path(__file__).with_name("test_docs_quality.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.test_hosted_ci_covers_quality_and_compose_readiness()
