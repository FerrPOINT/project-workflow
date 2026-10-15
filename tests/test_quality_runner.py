"""Quality must not duplicate tests or lose mandatory checks."""

from scripts.quality import commands


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
