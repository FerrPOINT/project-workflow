"""Supervisor workflow tests using custom DB workflow."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.supervisor]

from project_workflow.infrastructure.db.session import ensure_schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.supervisor import SupervisorEngine
from tests._db_helpers import phase_by_code

SUPERVISOR_WORKFLOW_NAME = "Supervisor Workflow"
SUPERVISOR_PHASES = ["sup.intake", "sup.review", "sup.done"]


def _patch_runtime(monkeypatch, tmp_path: Path) -> SAUnitOfWork:
    workflow_db = tmp_path / "workflow.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{workflow_db}")
    from project_workflow import config

    config.get_settings.cache_clear()
    uow = SAUnitOfWork(f"sqlite:///{workflow_db}")
    ensure_schema(uow.session.get_bind())
    return uow


def _bootstrap_supervisor_workflow(uow: SAUnitOfWork) -> None:
    workflow_id = uow.workflows.create(
        {
            "name": SUPERVISOR_WORKFLOW_NAME,
            "description": "Workflow used to validate DB-backed supervisor behavior.",
        }
    )
    uow.projects.create(
        {
            "workflow_id": workflow_id,
            "code": "SUP",
            "name": "Supervisor Project",
            "key_prefixes": ["SUP"],
        }
    )

    agents = [a.to_dict() for a in uow.agents.list()]
    critic = next((agent for agent in agents if agent["name"] == "critic"), None)
    critic_id = critic["id"] if critic else uow.agents.create({"name": "critic", "description": "Quality gate"})

    intake_id = uow.phases.create(
        {
            "workflow_id": workflow_id,
            "code": "sup.intake",
            "name": "Intake",
            "description": "Capture the implementation path before work starts.",
            "phase_order": 1,
        }
    )
    uow.phase_instructions.create(
        intake_id,
        {
            "step_num": 1,
            "description": "Create implementation plan",
            "execution_type": "sync",
        },
    )
    uow.phase_checks.create(intake_id, {"description": "Plan is documented"})
    uow.phase_evidence_requirements.create(intake_id, {"description": "Plan file attached"})

    review_id = uow.phases.create(
        {
            "workflow_id": workflow_id,
            "code": "sup.review",
            "name": "Review Gate",
            "description": "Review readiness before marking the task done.",
            "phase_order": 2,
            "agent_id": critic_id,
            "rollback_target_phase_id": intake_id,
        }
    )
    uow.phase_instructions.create(
        review_id,
        {
            "step_num": 1,
            "description": "Validate release readiness",
            "execution_type": "sync",
        },
    )
    uow.phase_checks.create(review_id, {"description": "All acceptance criteria confirmed"})
    uow.phase_evidence_requirements.create(review_id, {"description": "Reviewer sign-off attached"})

    uow.phases.create(
        {
            "workflow_id": workflow_id,
            "code": "sup.done",
            "name": "Done",
            "description": "Task is complete and ready to close.",
            "phase_order": 3,
        }
    )


def test_supervisor_context_contains_full_path_and_contract(tmp_path: Path, monkeypatch) -> None:
    uow = _patch_runtime(monkeypatch, tmp_path)
    _bootstrap_supervisor_workflow(uow)
    engine = SupervisorEngine("SUP-1", uow=uow)
    task = uow.tasks.get_by_key("SUP-1")

    assert task is not None
    assert task.current_phase_code == "sup.intake"

    ctx = engine.get_full_context()
    assert [phase["code"] for phase in ctx["workflow_path"]] == SUPERVISOR_PHASES
    assert ctx["current_contract"]["phase_code"] == "sup.intake"
    assert ctx["current_contract"]["required_evidence"] == ["Plan file attached"]
    assert "summary" in ctx["report_template"]
    assert ctx["cli_actor"]["kind"] == "cli-user"
    assert "любой пользователь" in ctx["cli_actor"]["description"].lower()

    prompt = engine.get_phase_prompt()
    assert "Текущий шаг" in prompt
    assert "Create implementation plan" in prompt
    assert "Задача" in prompt
    assert "Формат отчёта" in prompt
    assert "Полный путь workflow" not in prompt
    # Empty history/verdict sections are still present.
    assert "История выполнения:" in prompt
    assert "Недавние вердикты:" in prompt
    assert "Недавние сообщения:" not in prompt


def test_supervisor_evaluate_pass_updates_db_state_and_persists_run(
    tmp_path: Path, monkeypatch, supervisor_llm
) -> None:
    uow = _patch_runtime(monkeypatch, tmp_path)
    _bootstrap_supervisor_workflow(uow)

    engine = SupervisorEngine("SUP-2", uow=uow)
    supervisor_llm("PASS", covered=["Plan is documented", "Plan file attached"])
    result = engine.evaluate(
        "summary: Created implementation plan. completed: Plan is documented. "
        "evidence: Plan file attached. blockers: none. next_step: move to review."
    )

    assert result["verdict"] == "PASS"
    assert result["next_phase_code"] == "sup.review"

    task = uow.tasks.get_by_key("SUP-2")
    assert task is not None
    assert task.current_phase_code == "sup.review"

    events = uow.list_phase_events(task.id)
    assert [(event["event_type"], event["step_history_id"]) for event in events] == [
        ("entered", None),
        ("completed", 1),
        ("entered", 1),
    ]

    runs = uow.step_history.list(task_key="SUP-2")
    assert len(runs) == 1
    assert runs[0].verdict == "pass"
    assert runs[0].supervisor_response["next_phase_code"] == "sup.review"
    assert runs[0].evaluation_snapshot["contract_snapshot"]["phase_code"] == "sup.intake"


def test_supervisor_rolls_back_gate_phase_when_report_is_blocked(tmp_path: Path, monkeypatch, supervisor_llm) -> None:
    uow = _patch_runtime(monkeypatch, tmp_path)
    _bootstrap_supervisor_workflow(uow)

    project_row = next((p for p in uow.projects.list() if p.code == "SUP"), None)
    project_id = project_row.id if project_row else None
    review_row = phase_by_code(uow, "sup.review")
    review_id = review_row.id if review_row else None
    uow.tasks.create(
        {
            "task_key": "SUP-3",
            "title": "Rollback case",
            "project_id": project_id,
            "workflow_id": project_row.workflow_id,
            "current_phase_id": review_id,
        }
    )
    uow.commit()

    engine = SupervisorEngine("SUP-3", uow=uow, create_if_missing=False)
    supervisor_llm("ROLLBACK")
    result = engine.evaluate("Blocked by dependency mismatch. blocker remains and the gate cannot pass.")

    assert result["verdict"] == "ROLLBACK"
    assert result["rollback_phase_code"] == "sup.intake"
    assert result["next_phase_code"] == "sup.intake"

    task = uow.tasks.get_by_key("SUP-3")
    assert task is not None
    assert task.current_phase_code == "sup.intake"

    events = uow.list_phase_events(task.id)
    assert [event["event_type"] for event in events[-2:]] == ["rolled_back", "entered"]

    runs = uow.step_history.list(task_key="SUP-3")
    assert runs[0].verdict == "rollback"
    assert runs[0].supervisor_response["rollback_phase_code"] == "sup.intake"
    assert all(event["step_history_id"] == runs[0].id for event in events[-2:])
