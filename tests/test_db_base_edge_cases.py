"""Edge-case tests for db/base.py — uncovered paths."""
from __future__ import annotations

import sqlite3

import pytest

from workflow_cli.db import WorkflowDB


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    import workflow_cli.db as db_module
    monkeypatch.setattr(db_module.base, "DB_PATH", tmp_path / "workflow.db")
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "workflow.db")
    db = WorkflowDB()
    db.init()
    return db


class TestResolveIds:
    def test_resolve_phase_id_int(self, fresh_db):
        assert fresh_db._resolve_phase_id(42) == 42

    def test_resolve_phase_id_unknown_code(self, fresh_db):
        with pytest.raises(ValueError, match="Unknown phase code"):
            fresh_db._resolve_phase_id("NONEXISTENT")

    def test_resolve_project_id_int(self, fresh_db):
        assert fresh_db._resolve_project_id(42) == 42

    def test_resolve_project_id_unknown_code(self, fresh_db):
        with pytest.raises(ValueError, match="Unknown project code"):
            fresh_db._resolve_project_id("NONEXISTENT")

    def test_resolve_task_id_int(self, fresh_db):
        assert fresh_db._resolve_task_id(42) == 42

    def test_resolve_task_id_unknown_key(self, fresh_db):
        with pytest.raises(ValueError, match="Unknown task key"):
            fresh_db._resolve_task_id("AAT-99999")


class TestPhaseGetters:
    def test_get_phase_by_code_not_found(self, fresh_db):
        assert fresh_db.get_phase_by_code("NONEXISTENT") is None

    def test_get_phase_checks_invalid(self, fresh_db):
        assert fresh_db.get_phase_checks("NONEXISTENT") == []

    def test_get_phase_evidence_invalid(self, fresh_db):
        assert fresh_db.get_phase_evidence("NONEXISTENT") == []


class TestConnContext:
    def test_conn_context_manager(self, fresh_db):
        with fresh_db._conn() as conn:
            assert isinstance(conn, sqlite3.Connection)
            assert conn.row_factory == sqlite3.Row

    def test_close_noop(self, fresh_db):
        assert fresh_db.close() is None


class TestUpdateTask:
    def test_update_task_project_code(self, fresh_db):
        """Cover _resolve_project_id via project_code in update_task."""
        fresh_db.create_project({"code": "TST", "name": "Test", "key_patterns": [r"^(?P<prefix>TST)-(?P<number>[0-9]+)$"]})
        task_id = fresh_db.create_task({"task_key": "TST-1", "title": "t", "status": "active", "current_phase": "-1"})
        fresh_db.update_task(task_id, {"project_code": "TST"})
        task = fresh_db.get_task_by_key("TST-1")
        assert task["project_id"] is not None

    def test_update_task_plain_field(self, fresh_db):
        fresh_db.create_project({"code": "TST2", "name": "Test", "key_patterns": [r"^(?P<prefix>TST2)-(?P<number>[0-9]+)$"]})
        task_id = fresh_db.create_task({"task_key": "TST2-1", "title": "old", "status": "active", "current_phase": "-1"})
        fresh_db.update_task(task_id, {"title": "new"})
        task = fresh_db.get_task_by_key("TST2-1")
        assert task["title"] == "new"
