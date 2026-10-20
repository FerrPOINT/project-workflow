"""Quality must not duplicate tests or lose mandatory checks."""

import unittest

import pytest

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
    assert "--all-extras" in commands("coverage")[0]
    assert "--with-requirements" not in commands("coverage")[0]


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
    header = next(line for line in make.splitlines() if line.endswith(":") and "test-verbose" in line.split())
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


class QualityMakeContracts(unittest.TestCase):
    def test_quality_contains_the_identical_unit_and_lint_commands(self):
        quality = commands("quality", prepared=True)
        self.assertEqual(commands("test", prepared=True), commands("unit", prepared=True))
        self.assertEqual(quality, [*commands("unit", prepared=True),
                                  *commands("lint", prepared=True), ["git", "diff", "--check"]])

    def test_make_aliases_depend_on_quality_only_when_explicitly_requested(self):
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "Makefile").read_text(encoding="utf-8")
        # Keep failure propagation in Make's dependency graph, including make -j.
        self.assertIn("ifneq ($(filter quality,$(MAKECMDGOALS)),)\ntest unit lint: quality\nelse\n", source)
        phony = next(line for line in source.splitlines() if line.startswith(".PHONY:"))
        self.assertTrue({"test", "unit", "lint", "quality"}.issubset(phony.split()))

    def test_make_unit_alias_and_explicit_release_share_existing_owners(self):
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "Makefile").read_text(encoding="utf-8")
        self.assertIn("ifneq ($(filter release,$(MAKECMDGOALS)),)\n"
                      "test unit lint quality: $(COVERAGE_OWNER)\nelse\n", source)
        self.assertIn("\nelse\ntest: unit\nunit lint:\n", source)
        release = commands("release", prepared=True)
        self.assertEqual(commands("quality", prepared=True)[1:], release[2:])
        self.assertEqual("not postgres", release[0][release[0].index("-m", 2) + 1])
        self.assertIn("--cov=project_workflow", release[0])

    def test_real_make_coalesces_quality_aliases_and_preserves_other_lanes(self):
        import itertools
        import json
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
            for target in ("test", "unit", "lint", "quality"):
                (root / target).touch()
            (root / "scripts").mkdir()
            (root / "scripts/quality.py").write_text(
                "import json,os,sys\nfrom pathlib import Path\n"
                "with Path('calls.txt').open('a') as stream: stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                "raise SystemExit(int(os.environ.get('WORKFLOW_DISPATCH_EXIT', '0')))\n",
                encoding="utf-8",
            )
            coalesced = [goals for count in (2, 3, 4)
                         for goals in itertools.permutations(("quality", "test", "unit", "lint"), count)
                         if "quality" in goals]
            standalone = [(target,) for target in ("test", "unit", "lint", "quality")]
            release_goals = [goals for alias in ("test", "unit", "lint", "quality")
                             for goals in (("release", alias), (alias, "release"))]
            release_goals += [goals for pair in itertools.combinations(("test", "unit", "lint", "quality"), 2)
                              for goals in itertools.permutations(("release", *pair))]
            release_goals += [("test", "unit", "lint", "quality", "release"),
                              ("release", "quality", "lint", "unit", "test")]
            # Co-goals must depend on the actual report owner, even when a report
            # precedes release and therefore owns the existing coverage recipe.
            release_goals += [("coverage", "quality", "release", "lint"),
                              ("unit", "release", "test", "coverage"),
                              ("coverage-html", "quality", "release", "lint"),
                              ("unit", "release", "test", "coverage-html")]
            neighbors = [("quality", target) for target in (
                "warnings", "test-verbose", "integration", "slow", "test-integration",
                "coverage", "coverage-html",
            )]
            neighbors += [("release", "warnings"), ("test-verbose", "release")]
            for goals in [*coalesced, *release_goals, *standalone, *neighbors,
                          ("test", "unit"), ("unit", "test"), ("test", "lint")]:
                if "release" in goals and set(goals) <= {
                    "release", "quality", "test", "unit", "lint", "coverage", "coverage-html",
                }:
                    expected = [["--html-report", "release"]] if "coverage-html" in goals else [["release"]]
                elif "quality" in goals and set(goals) <= {"quality", "test", "unit", "lint"}:
                    expected = [["quality"]]
                else:
                    expected = [list(goal) for goal in dict.fromkeys(
                        ("unit" if goal == "test" else goal,) for goal in goals
                    )]
                for exit_code in ((0, 7) if len(expected) == 1 else (0,)):
                    with self.subTest(goals=goals, exit_code=exit_code):
                        (root / "calls.txt").unlink(missing_ok=True)
                        result = subprocess.run(
                            [make, "--no-print-directory", "-j8", *goals, "SHELL=" + bash.as_posix()],
                            cwd=root, env={**os.environ, "WORKFLOW_DISPATCH_EXIT": str(exit_code)},
                            text=True, capture_output=True, timeout=10, check=False,
                        )
                        self.assertEqual(exit_code == 0, result.returncode == 0, result.stdout + result.stderr)
                        self.assertCountEqual(expected, [json.loads(line) for line in
                                                       (root / "calls.txt").read_text().splitlines()])


class CoverageEntrypointContracts(unittest.TestCase):
    """Source/protocol controls without pytest collection, application imports or uv."""

    def test_release_html_keeps_one_preparation_and_all_release_checks(self):
        import itertools
        import os
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch

        from scripts import quality

        for html_report, failure in itertools.product(
            (False, True), (None, "uv", "coverage", "postgres", "ruff", "mypy", "git")
        ):
            with self.subTest(html_report=html_report, failure=failure):
                calls = []

                def inert_run(command, **_kwargs):
                    name = ("uv" if command[0] == "uv" else
                            "coverage" if "--cov=project_workflow" in command else
                            "postgres" if "postgres" in command else
                            "git" if command[0] == "git" else command[2])
                    calls.append((name, command))
                    if name == failure:
                        return SimpleNamespace(returncode=7)
                    if name == "uv":
                        child_args = command[command.index("--prepared"):]
                        with patch.object(sys, "argv", ["quality.py", *child_args]), \
                                patch.object(sys, "version_info", (3, 11, 15)):
                            return SimpleNamespace(returncode=quality.main())
                    return SimpleNamespace(returncode=0)

                environment = dict(os.environ)
                environment.pop("WORKFLOW_QUALITY_UV", None)
                arguments = ["quality.py", *(["--html-report"] if html_report else []), "release"]
                with patch.dict(os.environ, environment, clear=True), \
                        patch.object(sys, "argv", arguments), \
                        patch.object(quality.subprocess, "run", side_effect=inert_run):
                    self.assertEqual(7 if failure else 0, quality.main())
                expected = ["uv", "coverage", "postgres", "ruff", "mypy", "git"]
                self.assertEqual(expected[:expected.index(failure) + 1] if failure else expected,
                                 [name for name, _ in calls])
                coverage = next((command for name, command in calls if name == "coverage"), None)
                if coverage:
                    for report in ("term", "xml"):
                        self.assertEqual(1, coverage.count("--cov-report=" + report))
                    self.assertEqual(int(html_report), coverage.count("--cov-report=html"))
                    self.assertEqual("not postgres", coverage[coverage.index("-m", 2) + 1])
                    self.assertIn("error::ResourceWarning", coverage)
                    self.assertIn("error::pytest.PytestUnraisableExceptionWarning", coverage)
                    self.assertEqual("2", coverage[coverage.index("-n") + 1])

    def test_html_report_option_cannot_expand_an_unrelated_lane(self):
        import sys
        from unittest.mock import patch

        from scripts import quality

        for target in ("unit", "coverage", "coverage-html", "quality", "compose-ready"):
            with self.subTest(target=target), \
                    patch.object(sys, "argv", ["quality.py", "--html-report", target]), \
                    patch.object(quality.subprocess, "run") as runner:
                with self.assertRaises(SystemExit) as error:
                    quality.main()
                self.assertEqual(2, error.exception.code)
                runner.assert_not_called()

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
        import itertools
        import json
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
            (root / "release").write_text("A source file cannot suppress the phony release owner.\n")
            (root / "scripts").mkdir()
            (root / "scripts/quality.py").write_text(
                "import json,os,sys\nfrom pathlib import Path\n"
                "with Path('calls.txt').open('a') as stream: stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                "raise SystemExit(int(os.environ.get('WORKFLOW_DISPATCH_EXIT', '0')))\n",
                encoding="utf-8",
            )
            for count in (1, 2, 3):
                for goals in itertools.permutations(("release", "coverage", "coverage-html"), count):
                    expected = (["--html-report", "release"] if "release" in goals and "coverage-html" in goals
                                else ["release"] if "release" in goals
                                else ["coverage-html"] if "coverage-html" in goals else ["coverage"])
                    for exit_code in (0, 7):
                        with self.subTest(goals=goals, exit_code=exit_code):
                            (root / "calls.txt").unlink(missing_ok=True)
                            result = subprocess.run(
                                [make, "--no-print-directory", "-j8", *goals, "SHELL=" + bash.as_posix()],
                                cwd=root, env={**os.environ, "WORKFLOW_DISPATCH_EXIT": str(exit_code)},
                                text=True, capture_output=True, timeout=10, check=False,
                            )
                            self.assertEqual(exit_code == 0, result.returncode == 0, result.stdout + result.stderr)
                            self.assertEqual([expected], [json.loads(line) for line in
                                                        (root / "calls.txt").read_text().splitlines()])

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
        from pathlib import Path
        from types import SimpleNamespace

        import tomllib

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


def test_shared_frozen_pins_allow_build_only_and_conditional_nodes() -> None:
    from pathlib import Path

    from scripts.quality import UV, verify_constraint_versions

    root = Path(__file__).resolve().parents[1]
    verify_constraint_versions(root)
    assert f"WORKFLOW_QUALITY_UV ?= {UV}\n" in (root / "Makefile").read_text(encoding="utf-8")


@pytest.mark.parametrize("package", [
    "anyio", "ast-serialize", "coverage", "psycopg", "psycopg-binary",
    "pydantic", "pydantic-core", "ruff",
])
def test_each_former_overlay_version_mismatch_is_refused(tmp_path, package) -> None:
    from pathlib import Path

    from scripts.quality import verify_constraint_versions

    root = Path(__file__).resolve().parents[1]
    (tmp_path / "uv.lock").write_bytes((root / "uv.lock").read_bytes())
    constraints = (root / "constraints.txt").read_text(encoding="utf-8")
    lines = [f"{package}==0.0.0" if line.startswith(package + "==") else line
             for line in constraints.splitlines()]
    (tmp_path / "constraints.txt").write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(ValueError, match=f"Quality pin mismatch: {package}:"):
        verify_constraint_versions(tmp_path)


def test_normalized_constraint_collision_and_multiple_lock_versions_are_not_hidden(tmp_path) -> None:
    from scripts.quality import verify_constraint_versions

    lock = '[[package]]\nname="pydantic-core"\nversion="1"\n'
    (tmp_path / "uv.lock").write_text(lock, encoding="utf-8")
    constraints = tmp_path / "constraints.txt"
    constraints.write_text("pydantic-core==1\nPydantic_Core==2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate quality constraint: pydantic-core"):
        verify_constraint_versions(tmp_path)
    constraints.write_text("pydantic-core==1\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text(lock + lock.replace('version="1"', 'version="2"'), encoding="utf-8")
    with pytest.raises(ValueError, match="uv.lock=2, constraints=1"):
        verify_constraint_versions(tmp_path)


def test_pin_mismatch_blocks_bootstrap_before_subprocess(monkeypatch) -> None:
    import sys

    from scripts import quality

    def mismatch(_root):
        raise ValueError("Quality pin mismatch: pydantic: uv.lock=2, constraints=1")

    def unexpected(*_args, **_kwargs):
        pytest.fail("A mismatched canonical graph must not start uv or tests")

    monkeypatch.delenv("WORKFLOW_QUALITY_UV", raising=False)
    monkeypatch.setattr(sys, "argv", ["quality.py", "unit"])
    monkeypatch.setattr(quality, "verify_constraint_versions", mismatch)
    monkeypatch.setattr(quality.subprocess, "run", unexpected)
    with pytest.raises(SystemExit) as error:
        quality.main()
    assert error.value.code == 2


def test_python310_launcher_defers_toml_guard_to_pinned_child(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    from scripts import quality

    calls = []
    monkeypatch.delenv("WORKFLOW_QUALITY_UV", raising=False)
    monkeypatch.setattr(sys, "version_info", (3, 10, 99))
    monkeypatch.setattr(sys, "argv", ["quality.py", "unit"])
    monkeypatch.setattr(quality.subprocess, "run", lambda command, **_kwargs: (
        calls.append(command) or SimpleNamespace(returncode=0)))
    monkeypatch.setattr(quality, "verify_constraint_versions", lambda _root: pytest.fail("No TOML dependency in 3.10"))
    assert quality.main() == 0
    assert len(calls) == 1 and "--prepared" in calls[0]
    calls.clear()
    monkeypatch.setattr(sys, "argv", ["quality.py", "--prepared", "unit"])
    with pytest.raises(SystemExit) as error:
        quality.main()
    assert error.value.code == 2
    assert calls == []


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
            "scripts/test_profession_navigation.mjs", "tests/node/test_navigation_inputs.mjs",
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
            "scripts/quality.py", "scripts/quality.ps1", "tests/test_quality_runner.py", "uv.lock",
            "Dockerfile", "dependency-wheels.json", "tests/lanes.json",
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
