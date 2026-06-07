from __future__ import annotations

from pathlib import Path

from wartz_workflow import schema
from wartz_workflow.db import WorkflowDB
from wartz_workflow.wizard import WizardEngine


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
    convo_dir = tmp_path / ".wartz-workflow"
    convo_db = convo_dir / "conversation.db"
    monkeypatch.setattr("wartz_workflow.db.DB_PATH", workflow_db)
    monkeypatch.setattr("wartz_workflow.conversation.DB_DIR", convo_dir)
    monkeypatch.setattr("wartz_workflow.conversation.DB_PATH", convo_db)
    return workflow_db


def test_bootstrap_adds_smoke_project_and_short_workflow(tmp_path: Path, monkeypatch):
    workflow_db = _patch_runtime(monkeypatch, tmp_path)
    wdb = WorkflowDB(str(workflow_db))
    wdb.init()
    schema.ensure_phase_catalog(wdb)

    workflows = wdb.get_workflows()
    workflow_names = {workflow["name"] for workflow in workflows}
    assert "Default Workflow" in workflow_names
    assert SMOKE_WORKFLOW_NAME in workflow_names

    smoke_workflow = next(workflow for workflow in workflows if workflow["name"] == SMOKE_WORKFLOW_NAME)
    smoke_project = wdb.get_project_by_code("SMOKE")
    assert smoke_project is not None
    assert smoke_project["workflow_id"] == smoke_workflow["id"]
    assert smoke_project["workflow_name"] == SMOKE_WORKFLOW_NAME

    smoke_phases = wdb.get_phases(smoke_workflow["id"])
    assert [phase["code"] for phase in smoke_phases] == SMOKE_PHASE_CODES


def test_wizard_uses_project_workflow_and_starts_from_first_smoke_phase(tmp_path: Path, monkeypatch):
    workflow_db = _patch_runtime(monkeypatch, tmp_path)
    wdb = WorkflowDB(str(workflow_db))
    wdb.init()
    schema.ensure_phase_catalog(wdb)

    engine = WizardEngine("SMOKE-7")

    assert [phase.code for phase in engine.all_phases] == SMOKE_PHASE_CODES
    assert engine.current_phase == "smoke.intake"


def test_smoke_phase_prompt_surfaces_parallel_agent_and_rollback_metadata(tmp_path: Path, monkeypatch):
    workflow_db = _patch_runtime(monkeypatch, tmp_path)
    wdb = WorkflowDB(str(workflow_db))
    wdb.init()
    schema.ensure_phase_catalog(wdb)

    engine = WizardEngine("SMOKE-11")

    parallel_prompt = engine.get_phase_prompt("smoke.parallel-a")
    assert "Тип выполнения: parallel" in parallel_prompt
    assert "Параллельно с: smoke.parallel-b" in parallel_prompt
    assert "Делегировано агенту: researcher" in parallel_prompt

    review_prompt = engine.get_phase_prompt("smoke.review")
    assert "Делегировано агенту: critic" in review_prompt
    assert "Rollback target: smoke.plan" in review_prompt