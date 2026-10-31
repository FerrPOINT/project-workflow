"""Frozen preparation, selection, invalidation and one-pass release contracts."""
import unittest

import pytest

from scripts.quality import commands


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
    tools = [command for command in selected if command[:2] == [sys.executable, "-m"]]
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


def test_changed_components_select_only_their_real_runner():
    from pathlib import Path

    from scripts.vendor import base_quality_selection as selection

    root = Path(__file__).resolve().parents[1]
    cases = [
        ([], []),
        (["docs/TESTING.md"], []),
        (["project_workflow/domain/entities.py"], ["backend:unit"]),
        (["scripts/quality.py"], ["backend:unit"]),
        (["tests/test_quality_preparation.py"], ["backend:unit"]),
        (["uv.lock"], ["backend:unit"]),
        (["Dockerfile"], ["backend:unit"]),
        (["dependency-wheels.json"], ["backend:unit"]),
        (["scripts/dependency_inputs.py"], ["backend:unit"]),
        (["tests/test_dependency_locks.py"], ["backend:unit"]),
        (["scripts/test_profession_navigation.mjs"], ["frontend:navigation"]),
    ]
    for changed, expected in cases:
        assert [g["id"] for g in selection.plan(root, profile="unit", changed=changed)["gates"]] == expected
    unknown = selection.plan(root, profile="unit", changed=["new-unknown.file"])
    assert {g["id"] for g in unknown["gates"]} == {"backend:unit", "frontend:navigation"}

class QualityBatchTest(unittest.TestCase):
    def test_overlapping_fast_targets_execute_each_identical_command_once(self):
        from scripts import quality

        selected = quality.operation_commands(("unit", "test", "quality", "lint", "install-dev"), prepared=True)
        self.assertEqual(len(selected), 5)
        self.assertEqual(sum("pytest" in command for command in selected), 1)
        self.assertEqual([command[2] for command in selected if command[1:2] == ["-m"]],
                         ["pytest", "ruff", "mypy"])
        self.assertEqual(selected[-1], ["git", "diff", "--check"])
        self.assertFalse(any("--cov=project_workflow" in command or "postgres" in command for command in selected))

    def test_different_pytest_modes_and_requested_order_are_preserved(self):
        from scripts import quality

        selected = quality.operation_commands(("lint", "quality", "unit"), prepared=True)
        self.assertEqual([command[2] for command in selected if command[1:2] == ["-m"]],
                         ["ruff", "mypy", "pytest"])
        modes = quality.operation_commands(("unit", "warnings", "test-verbose"), prepared=True)
        self.assertEqual(len(modes), 3)
        self.assertIn("-v", modes[-1])
        self.assertIn("error::ResourceWarning", modes[1])

    def test_batch_bootstrap_is_one_frozen_operation(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from scripts import quality

        with patch.dict(quality.os.environ, {"WORKFLOW_QUALITY_UV": quality.UV}), \
                patch.object(quality.sys, "argv", ["quality.py", "--also", "quality", "--also", "lint", "unit"]), \
                patch.object(quality.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(quality.main(), 0)
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command[:len(quality.UV.split())], quality.UV.split())
        self.assertEqual(command[-6:], ["--prepared", "--also", "quality", "--also", "lint", "unit"])

    def test_prepared_batch_stops_on_first_failed_check(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from scripts import quality

        with patch.object(quality.sys, "argv", ["quality.py", "--prepared", "--also", "quality", "unit"]), \
                patch.object(quality.sys, "version_info", (3, 11, 15)), \
                patch.object(quality.subprocess, "run", return_value=SimpleNamespace(returncode=17)) as run:
            self.assertEqual(quality.main(), 17)
        run.assert_called_once()
        self.assertIn("pytest", run.call_args.args[0])

    def test_prepared_batch_dispatches_the_requested_union_without_uv(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from scripts import quality

        with patch.object(quality.sys, "argv", ["quality.py", "--prepared", "--also", "quality", "unit"]), \
                patch.object(quality.sys, "version_info", (3, 11, 15)), \
                patch.object(quality.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(quality.main(), 0)
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         quality.operation_commands(("unit", "quality"), prepared=True))
        self.assertEqual(run.call_count, 5)

    def test_secondary_install_dev_preserves_custom_bootstrap(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from scripts import quality

        with patch.dict(quality.os.environ, {"WORKFLOW_QUALITY_UV": "custom-uv --frozen"}), \
                patch.object(quality.sys, "argv", ["quality.py", "--also", "install-dev", "unit"]), \
                patch.object(quality.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(quality.main(), 0)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][:2], ["custom-uv", "--frozen"])
        self.assertIn("--prepared", run.call_args.args[0])

    def test_batch_does_not_accept_manual_targets_or_scoped_pytest_arguments(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from unittest.mock import patch

        from scripts import quality

        for arguments in (["--also", "release", "unit"], ["--also", "unit", "integration"],
                          ["--also", "lint", "unit", "--", "tests/test_domain_entities.py"]):
            with self.subTest(arguments=arguments), redirect_stderr(StringIO()), \
                    patch.object(quality.sys, "argv", ["quality.py", *arguments]), \
                    patch.object(quality.subprocess, "run") as run, self.assertRaises(SystemExit) as error:
                quality.main()
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()

    def test_make_routes_overlapping_goals_once_without_preparing_or_testing_an_app(self):
        import os
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        make = shutil.which("make")
        if os.name != "posix" or make is None:
            self.skipTest("POSIX GNU Make is required for the inert Make routing fixture")
        version = subprocess.run([make, "--version"], capture_output=True, text=True, check=True, timeout=10)
        if "GNU Make" not in version.stdout:
            self.skipTest("This routing fixture requires GNU Make")
        source = Path(__file__).resolve().parents[1] / "Makefile"
        cases = (
            ([], ["scripts/quality.py test"]),
            (["unit", "quality"], ["scripts/quality.py --also quality unit"]),
            (["quality", "unit", "lint"], ["scripts/quality.py --also unit --also lint quality"]),
            (["unit", "test"], ["scripts/quality.py --also test unit"]),
            (["integration"], ["scripts/quality.py integration"]),
            (["coverage", "coverage-html"], ["scripts/quality.py --html-report coverage"]),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "bin"
            binary.mkdir()
            python = binary / "python"
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$WORKFLOW_MAKE_TEST_LOG"\n', encoding="utf-8")
            python.chmod(0o700)
            log = root / "calls"
            environment = {**os.environ, "PATH": str(binary) + os.pathsep + os.environ.get("PATH", ""),
                           "WORKFLOW_MAKE_TEST_LOG": str(log), "WORKFLOW_QUALITY_UV": "fixture-uv",
                           "MAKEFLAGS": "", "MFLAGS": "", "GNUMAKEFLAGS": "", "MAKEFILES": "", "MAKEOVERRIDES": ""}
            for goals, expected in cases:
                with self.subTest(goals=goals):
                    log.write_text("", encoding="utf-8")
                    result = subprocess.run([make, "-j2", "-f", str(source), *goals], cwd=root,
                                            env=environment, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(log.read_text(encoding="utf-8").splitlines(), expected)
