"""Integration checks for the text CLI, Wizard and existing FSM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from project_workflow.config import get_settings
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.cli.ui import cli


@pytest.fixture
def manual_env(tmp_path, monkeypatch):
    workflow_dir = tmp_path / "manual_workflow"
    workflow_dir.mkdir()
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("WORKFLOW_DIR", str(workflow_dir))
    monkeypatch.setattr("project_workflow.infrastructure.db.DB_PATH", workflow_dir / "workflow.db")
    get_settings.cache_clear()

    seed = json.loads(
        (Path(__file__).parent / "manual_workflow_seed.json").read_text(encoding="utf-8")
    )
    uow = SAUnitOfWork()
    uow.init()
    workflow_id = uow.workflows.create(
        {
            "name": "Manual Test Workflow",
            "description": "CLI integration workflow",
            "_skip_default_phase": True,
        }
    )
    uow.projects.create(
        {
            "workflow_id": workflow_id,
            "code": "MANUAL",
            "name": "Manual Test Project",
            "key_prefixes": ["MANUAL"],
        }
    )
    for phase in seed:
        phase_id = uow.phases.create(
            {
                "workflow_id": workflow_id,
                "phase_order": phase["phase_order"],
                "code": phase["code"],
                "name": phase["name"],
                "description": phase["description"],
                "execution_type": phase["execution_type"],
                "parallel_with": phase.get("parallel_with"),
                "rollback_target": phase.get("rollback_target"),
                "is_delegated": phase.get("is_delegated", False),
            }
        )
        for instruction in phase.get("instructions", []):
            uow.instructions.create(phase_id, {"description": instruction["description"]})
        for check in phase.get("checks", []):
            uow.checks.create(phase_id, {"description": check["description"]})
        for evidence in phase.get("evidence", []):
            uow.evidence.create(phase_id, {"description": evidence["description"]})
    uow.commit()
    uow.close()

    yield CliRunner()
    get_settings.cache_clear()


def _phase_report(runner: CliRunner, task: str) -> str:
    result = runner.invoke(cli, ["--json", "step", "--task", task])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["prompt"]
    return (
        f"task: {task}; phase: {data['phase']}; "
        "instructions completed; checks passed; evidence: test://readback"
    )


def _submit(runner: CliRunner, task: str, report: str) -> dict:
    result = runner.invoke(
        cli,
        ["--json", "step", "--task", task, "--report", str(report)],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_full_workflow_uses_text_report_wizard_and_history(manual_env, wizard_llm):
    wizard_llm("PASS")
    runner = manual_env
    task = "MANUAL-1"
    submitted = []

    for _ in range(8):
        current = runner.invoke(cli, ["--json", "step", "--task", task])
        data = json.loads(current.output)
        if data.get("status") == "done":
            break
        result = _submit(runner, task, _phase_report(runner, task))
        submitted.append(result["phase"])
    else:
        pytest.fail("workflow did not finish")

    assert submitted == [
        "manual.intake",
        "manual.plan",
        "manual.parallel-a",
        "manual.seq-instr",
        "manual.rollback-demo",
        "manual.delegate-demo",
        "manual.done",
    ]
    history = runner.invoke(cli, ["--json", "history", "--task", task])
    assert history.exit_code == 0
    history_data = json.loads(history.output)
    assert history_data["count"] == len(submitted)
    intake = next(
        record
        for record in history_data["records"]
        if record["phase_code"] == "manual.intake"
    )
    assert intake["report"].startswith("task: MANUAL-1")
    assert intake["feedback"] == "Test Wizard verdict: PASS"
    assert intake["next_phase"] == "manual.plan"


def test_soft_fail_keeps_current_phase_for_revised_text_report(manual_env, wizard_llm):
    runner = manual_env
    task = "MANUAL-2"
    wizard_llm("SOFT_FAIL", missing=["more evidence"])
    first = _submit(runner, task, _phase_report(runner, task))
    assert first["verdict"] == "SOFT_FAIL"
    assert first["phase"] == "manual.intake"
    assert first["next_phase"] is None

    wizard_llm("PASS")
    revised = _phase_report(runner, task) + "; additional evidence: test://artifact"
    assert _submit(runner, task, revised)["next_phase"] == "manual.plan"


def test_wizard_rollback_uses_configured_target(manual_env, wizard_llm):
    runner = manual_env
    task = "MANUAL-3"
    wizard_llm("PASS")
    for _ in range(4):
        _submit(runner, task, _phase_report(runner, task))

    report = _phase_report(runner, task)
    wizard_llm("ROLLBACK")
    result = _submit(runner, task, report)
    assert result["phase"] == "manual.rollback-demo"
    assert result["rollback_target"] == "manual.seq-instr"
    assert result["next_phase"] == "manual.seq-instr"
