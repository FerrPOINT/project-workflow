"""Tests for SupervisorEngine edge cases and init error paths."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.supervisor]

from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.supervisor import SupervisorEngine


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'workflow.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    uow = SAUnitOfWork(database_url)
    uow.init()
    schema.ensure_phase_catalog(uow)
    return uow


def _make_engine(fresh_db, task_key):
    return SupervisorEngine(task_key, uow=fresh_db)


def test_unknown_task_key_raises(fresh_db):
    with pytest.raises(ValueError):
        SupervisorEngine("INVALID-KEY", uow=fresh_db, create_if_missing=False)


def test_existing_task_empty_current_phase(fresh_db):
    fresh_db.create_task({"task_key": "TASK-42", "title": "x", "current_phase": "-1"})
    engine = _make_engine(fresh_db, "TASK-42")
    assert engine.current_phase == "-1"


class TestSupervisorEvaluateEdge:
    def test_evaluate_empty_report_with_no_checks_passes(self, fresh_db, supervisor_llm):
        fresh_db.create_task({"task_key": "TASK-42", "title": "x", "current_phase": "-1"})
        engine = _make_engine(fresh_db, "TASK-42")
        supervisor_llm("PASS")
        result = engine.evaluate("")
        assert result["verdict"] == "PASS"

    def test_evaluate_nonexistent_phase_returns_blocked(self, fresh_db):
        fresh_db.create_task({"task_key": "TASK-42", "title": "x", "current_phase": "-1"})
        engine = _make_engine(fresh_db, "TASK-42")
        engine.current_phase = "nonexistent"
        result = engine.evaluate("report")
        assert result["verdict"] == "BLOCKED"

    def test_evaluate_no_history_for_first_phase(self, fresh_db, supervisor_llm):
        fresh_db.create_task({"task_key": "TASK-42", "title": "x", "current_phase": "-1"})
        engine = _make_engine(fresh_db, "TASK-42")
        supervisor_llm("PARTIAL", missing=["evidence"])
        result = engine.evaluate("report")
        assert result["verdict"] == "PARTIAL"

    def test_save_records_assessment(self, fresh_db, supervisor_llm):
        fresh_db.create_task({"task_key": "TASK-42", "title": "x", "current_phase": "-1"})
        engine = _make_engine(fresh_db, "TASK-42")
        supervisor_llm("PARTIAL")
        engine.evaluate("report")
        # evaluate() itself records the supervisor run; _store removed as dead code
        assert len(fresh_db.get_supervisor_runs()) >= 1
