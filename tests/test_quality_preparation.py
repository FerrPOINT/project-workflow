"""Frozen preparation, selection, invalidation and one-pass release contracts."""
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
        (["scripts/test_profession_navigation.mjs"], ["frontend:navigation"]),
    ]
    for changed, expected in cases:
        assert [g["id"] for g in selection.plan(root, profile="unit", changed=changed)["gates"]] == expected
    unknown = selection.plan(root, profile="unit", changed=["new-unknown.file"])
    assert {g["id"] for g in unknown["gates"]} == {"backend:unit", "frontend:navigation"}
