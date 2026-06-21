from __future__ import annotations

from pathlib import Path

from project_workflow.db import WorkflowDB
from project_workflow.wizard import WizardEngine


SUPERVISOR_WORKFLOW_NAME = "Supervisor Workflow"
SUPERVISOR_PHASES = ["sup.intake", "sup.review", "sup.done"]


def _patch_runtime(monkeypatch, tmp_path: Path) -> Path:
    workflow_db = tmp_path / "workflow.db"
    convo_dir = tmp_path / ".project-workflow"
    convo_db = convo_dir / "conversation.db"
    monkeypatch.setattr("project_workflow.db.DB_PATH", workflow_db)
    monkeypatch.setattr("project_workflow.db.DB_PATH", workflow_db)
    monkeypatch.setattr("project_workflow.conversation.DB_DIR", convo_dir)
    monkeypatch.setattr("project_workflow.conversation.DB_PATH", convo_db)
    return workflow_db


def _bootstrap_supervisor_workflow(wdb: WorkflowDB) -> None:
    workflow_id = wdb.create_workflow({
        "name": SUPERVISOR_WORKFLOW_NAME,
        "description": "Workflow used to validate DB-backed supervisor behavior.",
        "_skip_default_phase": True,
    })
    wdb.create_project({
        "workflow_id": workflow_id,
        "code": "SUP",
        "name": "Supervisor Project",
        "key_patterns": [r"^(?P<prefix>SUP)-(?P<number>[0-9]+)$"],
    })

    critic = next((agent for agent in wdb.get_agents() if agent["name"] == "critic"), None)
    critic_id = critic["id"] if critic else wdb.create_agent({"name": "critic", "description": "Quality gate"})

    wdb.create_phase({
        "workflow_id": workflow_id,
        "code": "sup.intake",
        "name": "Intake",
        "description": "Capture the implementation path before work starts.",
        "phase_order": 1,
        "next_recommendation": "Prepare review package once the plan is documented.",
    })
    wdb.create_instruction({
        "phase_id": "sup.intake",
        "step_num": 1,
        "description": "Create implementation plan",
        "execution_type": "sync",
    })
    wdb.create_check({"phase_id": "sup.intake", "description": "Plan is documented"})
    wdb.create_evidence({"phase_id": "sup.intake", "description": "Plan file attached"})

    wdb.create_phase({
        "workflow_id": workflow_id,
        "code": "sup.review",
        "name": "Review Gate",
        "description": "Review readiness before marking the task done.",
        "phase_order": 2,
        "agent_id": critic_id,
        "rollback_target": "sup.intake",
        "next_recommendation": "Move to done only after the gate is green.",
    })
    wdb.create_instruction({
        "phase_id": "sup.review",
        "step_num": 1,
        "description": "Validate release readiness",
        "execution_type": "sync",
    })
    wdb.create_check({"phase_id": "sup.review", "description": "All acceptance criteria confirmed"})
    wdb.create_evidence({"phase_id": "sup.review", "description": "Reviewer sign-off attached"})

    wdb.create_phase({
        "workflow_id": workflow_id,
        "code": "sup.done",
        "name": "Done",
        "description": "Task is complete and ready to close.",
        "phase_order": 3,
    })



def test_supervisor_context_contains_full_path_and_contract(tmp_path: Path, monkeypatch) -> None:
    workflow_db = _patch_runtime(monkeypatch, tmp_path)
    wdb = WorkflowDB(str(workflow_db))
    wdb.init()
    _bootstrap_supervisor_workflow(wdb)

    engine = WizardEngine("SUP-1", repo="/repo")
    task = wdb.get_task_by_key("SUP-1")

    assert task is not None
    assert task["current_phase"] == "sup.intake"

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
    workflow_db = _patch_runtime(monkeypatch, tmp_path)
    wdb = WorkflowDB(str(workflow_db))
    wdb.init()
    _bootstrap_supervisor_workflow(wdb)

    engine = WizardEngine("SUP-2", repo="/repo")
    result = engine.evaluate(
        "summary: Created implementation plan. completed: Plan is documented. evidence: Plan file attached. blockers: none. next_step: move to review."
    )

    assert result["verdict"] == "PASS"
    assert result["next_phase"] == "sup.review"

    task = wdb.get_task_by_key("SUP-2")
    assert task is not None
    assert task["current_phase"] == "sup.review"

    history = {
        wdb.get_phase(item["phase_id"])["code"]: item["status"]
        for item in wdb.get_task_history(task["id"])
    }
    assert history["sup.intake"] == "done"
    assert history["sup.review"] == "pending"

    runs = wdb.get_supervisor_runs(task_key="SUP-2")
    assert len(runs) == 1
    assert runs[0]["verdict"] == "pass"
    assert runs[0]["response"]["next_phase"] == "sup.review"
    assert runs[0]["context_snapshot"]["current_contract"]["phase_code"] == "sup.intake"



def test_supervisor_rolls_back_gate_phase_when_report_is_blocked(tmp_path: Path, monkeypatch) -> None:
    workflow_db = _patch_runtime(monkeypatch, tmp_path)
    wdb = WorkflowDB(str(workflow_db))
    wdb.init()
    _bootstrap_supervisor_workflow(wdb)

    task_id = wdb.create_task({
        "task_key": "SUP-3",
        "title": "Rollback case",
        "current_phase": "sup.review",
    })
    wdb.add_task_history(task_id, "sup.intake", "done")
    wdb.add_task_history(task_id, "sup.review", "pending")

    engine = WizardEngine("SUP-3", repo="/repo")
    result = engine.evaluate(
        "Blocked by dependency mismatch. blocker remains and the gate cannot pass."
    )

    assert result["verdict"] == "ROLLBACK"
    assert result["rollback_target"] == "sup.intake"
    assert result["next_phase"] == "sup.intake"

    task = wdb.get_task_by_key("SUP-3")
    assert task is not None
    assert task["current_phase"] == "sup.intake"

    history = {
        wdb.get_phase(item["phase_id"])["code"]: item["status"]
        for item in wdb.get_task_history(task["id"])
    }
    assert history["sup.review"] == "rollback"
    assert history["sup.intake"] == "pending"

    runs = wdb.get_supervisor_runs(task_key="SUP-3")
    assert runs[0]["verdict"] == "rollback"
    assert runs[0]["response"]["rollback_target"] == "sup.intake"
