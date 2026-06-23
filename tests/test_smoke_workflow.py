from __future__ import annotations

import pytest
from pathlib import Path

from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork

from project_workflow.wizard import WizardEngine


SMOKE_WORKFLOW_NAME = "Smoke Test Workflow"
SMOKE_PHASE_CODES = [
    "smoke.intake",
    "smoke.plan",
    "smoke.parallel-a",
    "smoke.parallel-b",
    "smoke.review",
    "smoke.done",
]


def _patch_runtime(monkeypatch, tmp_path: Path) -> Path:
    workflow_db = tmp_path / "workflow.db"
    convo_dir = tmp_path / ".project-workflow"
    convo_db = convo_dir / "conversation.db"
    monkeypatch.setattr("project_workflow.infrastructure.db.DB_PATH", workflow_db)
    monkeypatch.setattr("project_workflow.infrastructure.conversation.DB_DIR", convo_dir)
    monkeypatch.setattr("project_workflow.infrastructure.conversation.DB_PATH", convo_db)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{workflow_db}")
    from project_workflow import config
    from project_workflow.infrastructure.db.session import reset_engine
    reset_engine()
    config.get_settings.cache_clear()
    return workflow_db


@pytest.fixture(autouse=True)
def _reset_engine_per_test(monkeypatch, tmp_path):
    """Ensure each smoke test gets its own isolated DB engine/session."""
    from project_workflow.infrastructure.db.session import reset_engine
    reset_engine()


def test_bootstrap_adds_smoke_project_and_short_workflow(tmp_path: Path, monkeypatch):
    workflow_db = _patch_runtime(monkeypatch, tmp_path)
    uow = SAUnitOfWork(str(workflow_db))
    uow.init()
    schema.ensure_phase_catalog(uow)

    workflows = uow.get_workflows()
    workflow_names = {workflow["name"] for workflow in workflows}
    assert "Default Workflow" in workflow_names
    assert SMOKE_WORKFLOW_NAME in workflow_names

    smoke_workflow = next(workflow for workflow in workflows if workflow["name"] == SMOKE_WORKFLOW_NAME)
    smoke_project = uow.get_project_by_code("SMOKE")
    assert smoke_project is not None
    assert smoke_project["workflow_id"] == smoke_workflow["id"]
    assert smoke_project["workflow_name"] == SMOKE_WORKFLOW_NAME

    smoke_phases = uow.get_phases(smoke_workflow["id"])
    assert [phase["code"] for phase in smoke_phases] == SMOKE_PHASE_CODES


def test_wizard_uses_project_workflow_and_starts_from_first_smoke_phase(tmp_path: Path, monkeypatch):
    workflow_db = _patch_runtime(monkeypatch, tmp_path)
    uow = SAUnitOfWork(str(workflow_db))
    uow.init()
    schema.ensure_phase_catalog(uow)

    engine = WizardEngine("SMOKE-7")

    assert [phase.code for phase in engine.all_phases] == SMOKE_PHASE_CODES
    assert engine.current_phase == "smoke.intake"


def test_smoke_phase_prompt_surfaces_parallel_agent_and_rollback_metadata(tmp_path: Path, monkeypatch):
    workflow_db = _patch_runtime(monkeypatch, tmp_path)
    uow = SAUnitOfWork(str(workflow_db))
    uow.init()
    schema.ensure_phase_catalog(uow)

    engine = WizardEngine("SMOKE-11")

    parallel_prompt = engine.get_phase_prompt("smoke.parallel-a")
    assert "ПАРАЛЛЕЛЬНАЯ ГРУППА ФАЗ" in parallel_prompt
    assert "Smoke Parallel A" in parallel_prompt  # name shown
    assert "smoke.parallel-b" in parallel_prompt   # parallel partner (code)
    assert "Делегировано агенту: researcher" in parallel_prompt

    review_prompt = engine.get_phase_prompt("smoke.review")
    assert "Делегировано агенту: critic" in review_prompt


def test_parallel_group_pass_advances_all_phases(tmp_path: Path, monkeypatch):
    """Full report on parallel group marks all phases done and advances past group."""
    workflow_db = _patch_runtime(monkeypatch, tmp_path)
    uow = SAUnitOfWork(str(workflow_db))
    uow.init()
    schema.ensure_phase_catalog(uow)

    engine = WizardEngine("SMOKE-101")
    # Move to parallel-a
    uow.update_task(engine.task["id"], {"current_phase": "smoke.parallel-a"})
    uow.commit()
    engine.current_phase = "smoke.parallel-a"

    # Full report covering both checks
    report = (
        "backend check prepared. "
        "ui check prepared. "
        "Evidence: backend check, ui check."
    )
    result = engine.evaluate(report)

    assert result["verdict"] == "PASS"
    assert result["next_phase"] == "smoke.review"
    assert "Parallel group" in result["phase_name"]

    # All group phases should be done in history
    history = uow.get_task_history(engine.task["id"])
    statuses = {uow.get_phase(h["phase_id"])["code"]: h["status"] for h in history if h.get("phase_id")}
    assert statuses.get("smoke.parallel-a") == "done"
    assert statuses.get("smoke.parallel-b") == "done"

    # Current phase should be review
    task = uow.get_task_by_key("SMOKE-101")
    assert task["current_phase"] == "smoke.review"


def test_parallel_group_partial_stays_on_group(tmp_path: Path, monkeypatch):
    """Partial report does NOT advance or mark any parallel phase done."""
    workflow_db = _patch_runtime(monkeypatch, tmp_path)
    uow = SAUnitOfWork(str(workflow_db))
    uow.init()
    schema.ensure_phase_catalog(uow)

    engine = WizardEngine("SMOKE-102")
    uow.update_task(engine.task["id"], {"current_phase": "smoke.parallel-a"})
    uow.commit()
    engine.current_phase = "smoke.parallel-a"

    # Only one check covered → partial
    report = "backend check is ready. ui check is not ready."
    result = engine.evaluate(report)

    assert result["verdict"] == "PARTIAL"
    assert result["next_phase"] is None
    assert "Parallel group" in result["phase_name"]

    # No parallel phases in history yet
    history = uow.get_task_history(engine.task["id"])
    codes = {uow.get_phase(h["phase_id"])["code"] for h in history}
    assert "smoke.parallel-a" not in codes
    assert "smoke.parallel-b" not in codes

    # Current phase stays on parallel-a
    task = uow.get_task_by_key("SMOKE-102")
    assert task["current_phase"] == "smoke.parallel-a"


def test_parallel_group_blocked_stays_on_group(tmp_path: Path, monkeypatch):
    """Blocked report does NOT advance or mark any parallel phase done."""
    workflow_db = _patch_runtime(monkeypatch, tmp_path)
    uow = SAUnitOfWork(str(workflow_db))
    uow.init()
    schema.ensure_phase_catalog(uow)

    engine = WizardEngine("SMOKE-103")
    uow.update_task(engine.task["id"], {"current_phase": "smoke.parallel-a"})
    uow.commit()
    engine.current_phase = "smoke.parallel-a"

    report = "Blocker: dependency mismatch. Cannot proceed."
    result = engine.evaluate(report)

    assert result["verdict"] == "BLOCKED"
    assert result["next_phase"] is None
    assert "Parallel group" in result["phase_name"]

    # No parallel phases in history
    history = uow.get_task_history(engine.task["id"])
    codes = {uow.get_phase(h["phase_id"])["code"] for h in history}
    assert "smoke.parallel-a" not in codes
    assert "smoke.parallel-b" not in codes

    # Current phase stays
    task = uow.get_task_by_key("SMOKE-103")
    assert task["current_phase"] == "smoke.parallel-a"
    assert task["status"] == "blocked"
