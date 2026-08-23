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
    @pytest.mark.parametrize(
        ("status", "expected_total"),
        [("done", 2), ("active", 3)],
    )
    def test_load_tasks_progress_uses_history_only_after_completion(self, status, expected_total):
        wdb = MagicMock()
        wdb.get_tasks.return_value = [
            {
                "id": 1,
                "task_key": "RUN-1",
                "title": "t",
                "project_id": 1,
                "status": status,
                "current_phase": "b",
            }
        ]
        phases = [
            {"id": 1, "workflow_id": 1, "code": "a", "name": "A"},
            {"id": 2, "workflow_id": 1, "code": "b", "name": "B"},
            {"id": 3, "workflow_id": 1, "code": "later", "name": "Added later"},
        ]
        wdb.get_workflows.return_value = [{"id": 1}]
        wdb.get_phases.return_value = phases
        wdb.tasks.get_history_batch.return_value = {
            1: [
                {"phase_id": 1, "status": "done"},
                {"phase_id": 2, "status": "done"},
            ]
        }
        wdb.supervisor_runs.latest_for_tasks.return_value = []
        wdb.get_projects.return_value = [
            {"id": 1, "code": "TASK", "name": "Task", "workflow_id": 1}
        ]

        result = _service(wdb)._load_tasks()

        assert result[0]["completed"] == 2
        assert result[0]["total_phases"] == expected_total

    def test_load_tasks_latest_run_without_task_id(self):
        wdb = MagicMock()
        wdb.get_tasks.return_value = [
            {"id": 1, "task_key": "RUN-1", "title": "t", "project_id": 1, "status": "active"}
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
            {"id": 1, "task_key": "RUN-1", "title": "t", "project_id": 1, "status": "active"}
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

    def test_phase_history_uses_consecutive_numbers_after_phase_order_sort(self):
        wdb = MagicMock()
        phases = [
            {"id": 30, "phase_order": 30, "code": "internal.c", "name": "Third"},
            {"id": 10, "phase_order": 10, "code": "internal.a", "name": "First"},
            {"id": 20, "phase_order": 20, "code": "internal.b", "name": "Second"},
        ]
        history = [
            {"phase_id": 30, "status": "done"},
            {"phase_id": 10, "status": "done"},
            {"phase_id": 20, "status": "done"},
        ]

        blocks = _service(wdb)._build_phase_history_blocks(history, phases, None, wdb)
        displayed_phases = [phase for block in blocks for phase in block["phases"]]

        assert [phase["phase_code"] for phase in displayed_phases] == [
            "internal.a",
            "internal.b",
            "internal.c",
        ]
        assert [phase["sequence_number"] for phase in displayed_phases] == [1, 2, 3]

    def test_get_task_detail_empty_history_returns_zero_completed(self):
        wdb = MagicMock()
        wdb.get_task_by_key.return_value = {
            "id": 1,
            "task_key": "RUN-1",
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

        result = _service(wdb)._get_task_detail("RUN-1")
        assert result is not None
        assert result["completed"] == 0

    @pytest.mark.parametrize(
        ("status", "expected_total"),
        [("done", 2), ("active", 3)],
    )
    def test_task_detail_progress_uses_history_only_after_completion(self, status, expected_total):
        wdb = MagicMock()
        phases = [
            {"id": 1, "workflow_id": 1, "phase_order": 1, "code": "a", "name": "A"},
            {"id": 2, "workflow_id": 1, "phase_order": 2, "code": "b", "name": "B"},
            {
                "id": 3,
                "workflow_id": 1,
                "phase_order": 3,
                "code": "later",
                "name": "Added later",
            },
        ]
        wdb.get_task_by_key.return_value = {
            "id": 1,
            "task_key": "RUN-1",
            "title": "t",
            "project_id": 1,
            "status": status,
            "current_phase": "b",
            "workflow_id": 1,
        }
        wdb.get_phases.return_value = phases
        wdb.get_task_history.return_value = [
            {"phase_id": 1, "status": "done"},
            {"phase_id": 2, "status": "done"},
        ]
        wdb.get_supervisor_runs.return_value = []

        result = _service(wdb)._get_task_detail("RUN-1")

        assert result is not None
        assert result["progress_done"] == 2
        assert result["progress_total"] == expected_total
        assert result["workflow_phase_count"] == 3
