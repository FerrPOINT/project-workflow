"""Tests for WizardEngine edge cases and init error paths."""
from __future__ import annotations


import pytest

from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork

from project_workflow.wizard import WizardEngine


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    import project_workflow.infrastructure.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "workflow.db")
    uow = SAUnitOfWork(str(tmp_path / "workflow.db"))
    uow.init()
    schema.ensure_phase_catalog(uow)
    return uow


def _make_engine(fresh_db, task_key):
    return WizardEngine(task_key, uow=fresh_db)


def test_unknown_task_key_raises(fresh_db):
    with pytest.raises(ValueError):
        WizardEngine("INVALID-KEY", uow=fresh_db, create_if_missing=False)


def test_existing_task_empty_current_phase(fresh_db):
    fresh_db.create_task({"task_key": "PROJ-42", "title": "x", "current_phase": "-1"})
    engine = _make_engine(fresh_db, "PROJ-42")
    assert engine.current_phase == "-1"


class TestWizardEvaluateEdge:
    def test_evaluate_empty_report_with_no_checks_passes(self, fresh_db):
        fresh_db.create_task({"task_key": "PROJ-42", "title": "x", "current_phase": "-1"})
        engine = _make_engine(fresh_db, "PROJ-42")
        result = engine.evaluate("")
        assert result["verdict"] in {"PASS", "PARTIAL"}

    def test_evaluate_nonexistent_phase_returns_blocked(self, fresh_db):
        fresh_db.create_task({"task_key": "PROJ-42", "title": "x", "current_phase": "-1"})
        engine = _make_engine(fresh_db, "PROJ-42")
        engine.current_phase = "nonexistent"
        result = engine.evaluate("report")
        assert result["verdict"] == "BLOCKED"

    def test_evaluate_no_history_for_first_phase(self, fresh_db):
        fresh_db.create_task({"task_key": "PROJ-42", "title": "x", "current_phase": "-1"})
        engine = _make_engine(fresh_db, "PROJ-42")
        result = engine.evaluate("report")
        assert result["verdict"] in {"PASS", "PARTIAL"}

    def test_save_records_assessment(self, fresh_db):
        fresh_db.create_task({"task_key": "PROJ-42", "title": "x", "current_phase": "-1"})
        engine = _make_engine(fresh_db, "PROJ-42")
        result = engine.evaluate("report")
        engine._store.save(result)
        assert len(fresh_db.get_supervisor_runs()) >= 1
