"""Supervisor workflow tests using custom DB workflow."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.wizard]

from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.wizard import WizardEngine

SUPERVISOR_WORKFLOW_NAME = "Supervisor Workflow"
SUPERVISOR_PHASES = ["sup.intake", "sup.review", "sup.done"]


def _patch_runtime(monkeypatch, tmp_path: Path) -> SAUnitOfWork:
    workflow_db = tmp_path / "workflow.db"
    convo_dir = tmp_path / ".project-workflow"
    convo_db = convo_dir / "conversation.db"
    monkeypatch.setattr("project_workflow.infrastructure.db.DB_PATH", workflow_db)
    monkeypatch.setattr("project_workflow.infrastructure.db.DB_PATH", workflow_db)
    monkeypatch.setattr("project_workflow.infrastructure.conversation.DB_DIR", convo_dir)
    monkeypatch.setattr("project_workflow.infrastructure.conversation.DB_PATH", convo_db)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{workflow_db}")
    from project_workflow import config
    config.get_settings.cache_clear()
    uow = SAUnitOfWork(str(workflow_db))
    uow.create_all()
    return uow


def _bootstrap_supervisor_workflow(uow: SAUnitOfWork) -> None:
    workflow_id = uow.workflows.create({
        "name": SUPERVISOR_WORKFLOW_NAME,
        "description": "Workflow used to validate DB-backed supervisor behavior.",
        "_skip_default_phase": True,
    })
    uow.projects.create({
        "workflow_id": workflow_id,
        "code": "SUP",
        "name": "Supervisor Project",
        "key_prefixes": ["SUP"],
    })

    agents = [a.to_dict() for a in uow.agents.list()]
    critic = next((agent for agent in agents if agent["name"] == "critic"), None)
    critic_id = critic["id"] if critic else uow.agents.create({"name": "critic", "description": "Quality gate"})

    intake_id = uow.phases.create({
        "workflow_id": workflow_id,
        "code": "sup.intake",
        "name": "Intake",
        "description": "Capture the implementation path before work starts.",
        "phase_order": 1,
        "next_recommendation": "Prepare review package once the plan is documented.",
    })
    uow.instructions.create(intake_id, {
        "step_num": 1,
        "description": "Create implementation plan",
        "execution_type": "sync",
    })
    uow.checks.create(intake_id, {"description": "Plan is documented"})
    uow.evidence.create(intake_id, {"description": "Plan file attached"})

    review_id = uow.phases.create({
        "workflow_id": workflow_id,
        "code": "sup.review",
        "name": "Review Gate",
        "description": "Review readiness before marking the task done.",
        "phase_order": 2,
        "agent_id": critic_id,
        "rollback_target": "sup.intake",
        "next_recommendation": "Move to done only after the gate is green.",
    })
    uow.instructions.create(review_id, {
        "step_num": 1,
        "description": "Validate release readiness",
        "execution_type": "sync",
    })
    uow.checks.create(review_id, {"description": "All acceptance criteria confirmed"})
    uow.evidence.create(review_id, {"description": "Reviewer sign-off attached"})

    uow.phases.create({
        "workflow_id": workflow_id,
        "code": "sup.done",
        "name": "Done",
        "description": "Task is complete and ready to close.",
        "phase_order": 3,
    })



def test_supervisor_context_contains_full_path_and_contract(tmp_path: Path, monkeypatch) -> None:
    uow = _patch_runtime(monkeypatch, tmp_path)
    _bootstrap_supervisor_workflow(uow)
    engine = WizardEngine("SUP-1", repo="/repo", uow=uow)
    task = uow.tasks.get_by_key("SUP-1")

    assert task is not None
    assert task.current_phase == "sup.intake"

    ctx = engine.get_full_context()
    assert [phase["code"] for phase in ctx["workflow_path"]] == SUPERVISOR_PHASES
    assert ctx["current_contract"]["phase_code"] == "sup.intake"
    assert ctx["current_contract"]["required_evidence"] == ["Plan file attached"]
    assert "summary" in ctx["report_template"]
    assert any("skip" in item.lower() for item in ctx["global_instructions"])
    assert ctx["cli_actor"]["kind"] == "cli-user"
    assert "любой пользователь" in ctx["cli_actor"]["description"].lower()

    prompt = engine.get_phase_prompt()
    assert "Текущий шаг" in prompt
    assert "Create implementation plan" in prompt
    assert "Задача" in prompt
    assert "Формат отчёта" not in prompt
    assert "Полный путь workflow" not in prompt



def test_supervisor_evaluate_pass_updates_db_state_and_persists_run(tmp_path: Path, monkeypatch) -> None:
    uow = _patch_runtime(monkeypatch, tmp_path)
    _bootstrap_supervisor_workflow(uow)

    engine = WizardEngine("SUP-2", repo="/repo", uow=uow)
    result = engine.evaluate(
        "summary: Created implementation plan. completed: Plan is documented. evidence: Plan file attached. blockers: none. next_step: move to review."
    )

    assert result["verdict"] == "PASS"
    assert result["next_phase"] == "sup.review"

    task = uow.tasks.get_by_key("SUP-2")
    assert task is not None
    assert task.current_phase == "sup.review"

    history = {
        uow.phases.get_by_id(item['phase_id']).code: item['status']
        for item in uow.tasks.get_history(task.id)
    }
    assert history["sup.intake"] == "done"
    assert history["sup.review"] == "pending"

    runs = uow.supervisor_runs.list(task_key="SUP-2")
    assert len(runs) == 1
    assert runs[0].verdict == "pass"
    assert runs[0].response["next_phase"] == "sup.review"
    assert runs[0].context_snapshot["current_contract"]["phase_code"] == "sup.intake"



def test_supervisor_rolls_back_gate_phase_when_report_is_blocked(tmp_path: Path, monkeypatch) -> None:
    uow = _patch_runtime(monkeypatch, tmp_path)
    _bootstrap_supervisor_workflow(uow)

    project_row = next((p for p in uow.projects.list() if p.code == "SUP"), None)
    project_id = project_row.id if project_row else None
    intake_row = uow.phases.get_by_code("sup.intake")
    intake_id = intake_row.id if intake_row else None
    review_row = uow.phases.get_by_code("sup.review")
    review_id = review_row.id if review_row else None
    task_id = uow.tasks.create({
        "task_key": "SUP-3",
        "title": "Rollback case",
        "project_id": project_id,
        "current_phase": "sup.review",
    })
    uow.tasks.add_history(task_id, intake_id, "done")
    uow.tasks.add_history(task_id, review_id, "pending")

    engine = WizardEngine("SUP-3", repo="/repo", uow=uow, create_if_missing=False)
    result = engine.evaluate(
        "Blocked by dependency mismatch. blocker remains and the gate cannot pass."
    )

    assert result["verdict"] == "ROLLBACK"
    assert result["rollback_target"] == "sup.intake"
    assert result["next_phase"] == "sup.intake"

    task = uow.tasks.get_by_key("SUP-3")
    assert task is not None
    assert task.current_phase == "sup.intake"

    history = {
        uow.phases.get_by_id(item['phase_id']).code: item['status']
        for item in uow.tasks.get_history(task.id)
    }
    assert history["sup.review"] == "rollback"
    assert history["sup.intake"] == "pending"

    runs = uow.supervisor_runs.list(task_key="SUP-3")
    assert runs[0].verdict == "rollback"
    assert runs[0].response["rollback_target"] == "sup.intake"
