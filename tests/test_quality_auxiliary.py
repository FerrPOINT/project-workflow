"""Auxiliary commands reuse the quality owner without another test run."""

import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import quality

pytestmark = pytest.mark.unit


def test_html_report_never_collects_or_executes_tests(monkeypatch):
    monkeypatch.delenv("WORKFLOW_QUALITY_UV", raising=False)
    monkeypatch.setattr(quality, "unit_test_paths", lambda: pytest.fail("Report must not collect tests"))
    assert quality.commands("coverage-html", prepared=True) == [
        [sys.executable, "-m", "coverage", "html", "--fail-under=94"]
    ]
    command = quality.commands("coverage-html")[0]
    assert command == shlex.split(quality.UV) + [
        "--no-sync", "--no-python-downloads", "coverage", "html", "--fail-under=94"
    ]


def test_prepare_only_has_no_test_or_lint_tools(monkeypatch):
    monkeypatch.setattr(quality, "unit_test_paths", lambda: pytest.fail("Preparation must not collect tests"))
    assert quality.commands("install-dev", prepared=True) == []


@pytest.mark.parametrize("target", ["coverage-html", "install-dev"])
def test_default_auxiliary_entrypoint_uses_one_pinned_child(monkeypatch, target):
    calls = []
    monkeypatch.delenv("WORKFLOW_QUALITY_UV", raising=False)
    monkeypatch.setenv("VIRTUAL_ENV", "unrelated-environment")
    monkeypatch.setenv("PYTHONHOME", "unrelated-home")
    monkeypatch.setenv("WORKFLOW_QUALITY_ENVIRONMENT", "chosen-quality-environment")
    monkeypatch.setattr(sys, "argv", ["quality.py", target])
    monkeypatch.setattr(quality.subprocess, "run", lambda argv, **kwargs: (
        calls.append((argv, kwargs)) or SimpleNamespace(returncode=0)))
    assert quality.main() == 0
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[-2:] == ["--prepared", target]
    assert "pytest" not in argv and "pip" not in argv
    assert ("--no-sync" in argv) == (target == "coverage-html")
    assert ("--no-python-downloads" in argv) == (target == "coverage-html")
    assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == "chosen-quality-environment"
    assert "VIRTUAL_ENV" not in kwargs["env"] and "PYTHONHOME" not in kwargs["env"]


@pytest.mark.parametrize("target", ["coverage-html", "install-dev"])
def test_prepared_auxiliary_entrypoint_does_not_resync(monkeypatch, target):
    calls = []
    monkeypatch.setattr(sys, "version_info", (3, 11, 15))
    monkeypatch.setattr(sys, "argv", ["quality.py", "--prepared", target])
    monkeypatch.setattr(quality.subprocess, "run", lambda argv, **_kwargs: (
        calls.append(argv) or SimpleNamespace(returncode=0)))
    assert quality.main() == 0
    assert calls == ([[sys.executable, "-m", "coverage", "html", "--fail-under=94"]]
                     if target == "coverage-html" else [])


@pytest.mark.parametrize("failure", [1, 2])
def test_failed_report_never_retries_tests_or_install(monkeypatch, failure):
    calls = []
    monkeypatch.setattr(sys, "version_info", (3, 11, 15))
    monkeypatch.setattr(sys, "argv", ["quality.py", "--prepared", "coverage-html"])
    monkeypatch.setattr(quality.subprocess, "run", lambda argv, **_kwargs: (
        calls.append(argv) or SimpleNamespace(returncode=failure)))
    assert quality.main() == failure
    assert calls == [[sys.executable, "-m", "coverage", "html", "--fail-under=94"]]


def test_install_dev_keeps_custom_wrapper_and_pinned_child(monkeypatch):
    calls = []
    monkeypatch.setenv("WORKFLOW_QUALITY_UV", "custom-run --offline")
    monkeypatch.setattr(sys, "argv", ["quality.py", "install-dev"])
    monkeypatch.setattr(quality.subprocess, "run", lambda argv, **_kwargs: (
        calls.append(argv) or SimpleNamespace(returncode=17)))
    assert quality.main() == 17
    assert len(calls) == 1 and calls[0][:2] == ["custom-run", "--offline"]
    assert calls[0][-2:] == ["--prepared", "install-dev"]


def test_report_keeps_custom_runner_flags_without_assuming_uv(monkeypatch):
    monkeypatch.setenv("WORKFLOW_QUALITY_UV", "custom-run --offline")
    assert quality.commands("coverage-html")[0] == [
        "custom-run", "--offline", "coverage", "html", "--fail-under=94"
    ]


def test_make_and_powershell_share_auxiliary_targets():
    root = Path(__file__).resolve().parents[1]
    make = (root / "Makefile").read_text(encoding="utf-8")
    assert "release coverage coverage-html:\n" in make
    powershell = (root / "scripts/quality.ps1").read_text(encoding="utf-8")
    for target in ("coverage-html", "install-dev"):
        assert target in quality.TARGETS
        assert target in make.split("\n.PHONY: ", 1)[1].splitlines()[0].split()
        assert "'" + target + "'" in powershell
        assert "\n" + target + ":\n" not in make
    assert "pip install" not in make and "$(PYTEST)" not in make


@pytest.mark.parametrize("target", ["coverage-html", "install-dev"])
def test_auxiliary_pin_mismatch_fails_before_any_child(monkeypatch, target):
    monkeypatch.delenv("WORKFLOW_QUALITY_UV", raising=False)
    monkeypatch.setattr(sys, "argv", ["quality.py", target])
    def mismatch(_root):
        raise ValueError("Quality pin mismatch")
    monkeypatch.setattr(quality, "verify_constraint_versions", mismatch)
    monkeypatch.setattr(quality.subprocess, "run", lambda *_a, **_k: pytest.fail("Invalid pins must not run"))
    with pytest.raises(SystemExit) as error:
        quality.main()
    assert error.value.code == 2


@pytest.mark.parametrize("target", ["coverage-html", "install-dev"])
def test_prepared_auxiliary_wrong_interpreter_is_not_accepted(monkeypatch, target):
    monkeypatch.setattr(sys, "version_info", (3, 12, 0))
    monkeypatch.setattr(sys, "argv", ["quality.py", "--prepared", target])
    monkeypatch.setattr(quality.subprocess, "run", lambda *_a, **_k: pytest.fail("Wrong interpreter must not run"))
    with pytest.raises(SystemExit) as error:
        quality.main()
    assert error.value.code == 2


@pytest.mark.parametrize("target", ["coverage-html", "install-dev"])
def test_auxiliary_target_rejects_pytest_selection_arguments(monkeypatch, target):
    monkeypatch.setattr(sys, "argv", ["quality.py", target, "--", "tests/test_quality_auxiliary.py"])
    monkeypatch.setattr(quality.subprocess, "run",
                        lambda *_a, **_k: pytest.fail("Invalid target arguments must not run"))
    with pytest.raises(SystemExit) as error:
        quality.main()
    assert error.value.code == 2


@pytest.mark.parametrize("target,failure", [
    (target, failure) for target in ("coverage", "release")
    for failure in ([None, "uv", "coverage"] if target == "coverage"
                    else [None, "uv", "hygiene", "coverage", "postgres", "ruff", "mypy", "git"])
])
def test_explicit_report_union_keeps_one_preparation_and_original_failures(monkeypatch, target, failure):
    # Reuse the previously qualified release-owner protocol for the adopted runner.
    from unittest.mock import patch
    calls = []
    def run(command, **_kwargs):
        name = ("uv" if command[0] == "uv" else
                "hygiene" if "scripts/check_repository_hygiene.py" in command else
                "coverage" if "--cov=project_workflow" in command else
                "postgres" if "postgres" in command else
                "git" if command[0] == "git" else command[2])
        calls.append((name, command))
        if name == failure:
            return SimpleNamespace(returncode=7)
        if name == "uv":
            child = command[command.index("--prepared"):]
            with patch.object(sys, "argv", ["quality.py", *child]), \
                    patch.object(sys, "version_info", (3, 11, 15)):
                return SimpleNamespace(returncode=quality.main())
        return SimpleNamespace(returncode=0)
    monkeypatch.delenv("WORKFLOW_QUALITY_UV", raising=False)
    monkeypatch.setattr(sys, "argv", ["quality.py", "--html-report", target])
    monkeypatch.setattr(quality.subprocess, "run", run)
    assert quality.main() == (7 if failure else 0)
    expected = (["uv", "hygiene", "coverage", "postgres", "ruff", "mypy", "git"]
                if target == "release" else ["uv", "coverage"])
    assert [name for name, _ in calls] == (expected[:expected.index(failure) + 1] if failure else expected)
    assert "--no-sync" not in calls[0][1]
    executed = next((command for name, command in calls if name == "coverage"), None)
    if executed:
        for report in ("term", "xml", "html"):
            assert executed.count("--cov-report=" + report) == 1
        assert executed[executed.index("-n") + 1] == "2"
        assert "error::ResourceWarning" in executed
        assert "error::pytest.PytestUnraisableExceptionWarning" in executed


@pytest.mark.parametrize("target", ["unit", "quality", "coverage-html", "install-dev"])
def test_html_option_cannot_expand_an_unrelated_lane(monkeypatch, target):
    with pytest.raises(ValueError, match="coverage or release"):
        quality.commands(target, html_report=True)
    monkeypatch.setattr(sys, "argv", ["quality.py", "--html-report", target])
    monkeypatch.setattr(quality.subprocess, "run", lambda *_a, **_k: pytest.fail("Invalid report lane must not run"))
    with pytest.raises(SystemExit) as error:
        quality.main()
    assert error.value.code == 2
