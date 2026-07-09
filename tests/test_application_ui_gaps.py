"""Coverage gap tests for application.ui UIDataService."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.ui]


class MockAppState:
    def __init__(self, wdb):
        self._wdb = wdb

    def get_db(self):
        return self._wdb


def _service(wdb):
    from project_workflow.application.ui import UIDataService

    return UIDataService(MockAppState(wdb))


class TestUIDataServiceGaps:
    def test_load_tasks_latest_run_without_task_id(self):
        wdb = MagicMock()
        wdb.get_tasks.return_value = [
            {"id": 1, "task_key": "TASK-1", "title": "t", "project_id": 1, "status": "active"}
        ]
        wdb.get_workflows.return_value = []
        wdb.get_phases.return_value = []
        wdb.tasks.get_history_batch.return_value = {1: []}

        class Run:
            pass

        wdb.supervisor_runs.latest_for_tasks.return_value = [Run()]
        wdb.get_projects.return_value = []

        result = _service(wdb)._load_tasks()
        assert result[0]["latest_verdict"] is None
        assert result[0]["latest_verdict_phase"] is None

    def test_load_tasks_latest_run_extracts_verdict(self):
        wdb = MagicMock()
        wdb.get_tasks.return_value = [
            {"id": 1, "task_key": "TASK-1", "title": "t", "project_id": 1, "status": "active"}
        ]
        wdb.get_workflows.return_value = []
        wdb.get_phases.return_value = []
        wdb.tasks.get_history_batch.return_value = {1: []}

        class Run:
            task_id = 1

            def to_dict(self):
                return {"verdict": "pass", "phase_code": "1"}

        wdb.supervisor_runs.latest_for_tasks.return_value = [Run()]
        wdb.get_projects.return_value = []

        result = _service(wdb)._load_tasks()
        assert result[0]["latest_verdict"] == "pass"
        assert result[0]["latest_verdict_phase"] == "1"

    def test_resolve_task_workflow_id_from_project_dict(self):
        wdb = MagicMock()
        wid, phases = _service(wdb)._resolve_task_workflow_id(
            {"workflow_id": None, "project": {"workflow_id": 5}}, wdb
        )
        assert wid == 5

    def test_compute_completion_time_empty_done_entries(self):
        result = _service(None)._compute_completion_time(
            {"status": "done", "updated_at": "2026-01-01"}, []
        )
        assert result == "2026-01-01"

    def test_get_task_detail_empty_history_returns_zero_completed(self):
        wdb = MagicMock()
        wdb.get_task_by_key.return_value = {
            "id": 1,
            "task_key": "TASK-1",
            "title": "t",
            "project_id": 1,
            "status": "active",
            "current_phase": "-1",
            "workflow_id": 1,
        }
        wdb.get_task_history.return_value = []
        wdb.get_phases.return_value = []
        wdb.get_supervisor_runs.return_value = []
        wdb.projects.get_by_id.return_value = None
        wdb.get_phase.return_value = None

        result = _service(wdb)._get_task_detail("TASK-1")
        assert result is not None
        assert result["completed"] == 0
