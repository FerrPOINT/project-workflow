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
        [("done", 3), ("active", 3)],
    )
    def test_load_tasks_progress_uses_history_only_after_completion(self, status, expected_total):
        wdb = MagicMock()
        wdb.get_tasks.return_value = [
            {
                "id": 1,
                "task_key": "RUN-1",
                "title": "t",
                "project_id": 1,
                "workflow_id": 1,
                "status": status,
                "current_phase_id": 2,
                "current_phase_code": "b",
                "current_phase_name": "B",
            }
        ]
        phases = [
            {"id": 1, "workflow_id": 1, "code": "a", "name": "A"},
            {"id": 2, "workflow_id": 1, "code": "b", "name": "B"},
            {"id": 3, "workflow_id": 1, "code": "later", "name": "Added later"},
        ]
        wdb.get_workflows.return_value = [{"id": 1}]
        wdb.get_phases.return_value = phases
        wdb.list_phase_events_batch.return_value = {
            1: [
                {"phase_id": 1, "event_type": "completed", "occurred_at": "2026-01-01"},
                {"phase_id": 2, "event_type": "completed", "occurred_at": "2026-01-02"},
            ]
        }
        wdb.step_history.latest_for_tasks.return_value = []
        wdb.get_projects.return_value = [
            {"id": 1, "code": "TASK", "name": "Task", "workflow_id": 1}
        ]

        result = _service(wdb)._load_tasks()

        assert result[0]["completed"] == 2
        assert result[0]["total_phases"] == expected_total

    def test_load_tasks_prefers_pinned_workflow_over_project_revision(self):
        wdb = MagicMock()
        wdb.get_tasks.return_value = [
            {
                "id": 1,
                "task_key": "RUN-OLD",
                "title": "old",
                "project_id": 1,
                "workflow_id": 1,
                "status": "active",
                "current_phase_id": 11,
                "current_phase_code": "v1",
                "current_phase_name": "V1",
            }
        ]
        wdb.get_workflows.return_value = [{"id": 1}, {"id": 2}]
        phases = {
            1: [{"id": 11, "workflow_id": 1, "code": "v1", "name": "V1"}],
            2: [
                {"id": 21, "workflow_id": 2, "code": "wf-two-a", "name": "Workflow two A"},
                {"id": 22, "workflow_id": 2, "code": "wf-two-b", "name": "Workflow two B"},
            ],
        }
        wdb.get_phases.side_effect = lambda workflow_id=None: phases.get(workflow_id, [])
        wdb.list_phase_events_batch.return_value = {1: []}
        wdb.step_history.latest_for_tasks.return_value = []
        wdb.get_projects.return_value = [{"id": 1, "code": "RUN", "name": "Runs", "workflow_id": 2}]

        result = _service(wdb)._load_tasks()

        assert result[0]["workflow_id"] == 1
        assert result[0]["total_phases"] == 1
        assert result[0]["current_phase_name"] == "V1"

    def test_load_tasks_latest_run_extracts_verdict(self):
        wdb = MagicMock()
        wdb.get_tasks.return_value = [
            {
                "id": 1,
                "task_key": "RUN-1",
                "title": "t",
                "project_id": 1,
                "workflow_id": 1,
                "status": "active",
                "current_phase_id": 1,
                "current_phase_code": "1",
                "current_phase_name": "One",
            }
        ]
        wdb.get_workflows.return_value = [{"id": 1}]
        wdb.get_phases.return_value = [{"id": 1, "code": "1", "name": "One"}]
        wdb.list_phase_events_batch.return_value = {1: []}

        class Run:
            task_id = 1

            def to_dict(self):
                return {
                    "verdict": "pass",
                    "evaluation_snapshot": {"phase_code": "1"},
                    "supervisor_response": {},
                }

        wdb.step_history.latest_for_tasks.return_value = [Run()]
        wdb.get_projects.return_value = [{"id": 1, "code": "RUN", "name": "Runs"}]

        result = _service(wdb)._load_tasks()
        assert result[0]["latest_verdict"] == "pass"
        assert result[0]["latest_verdict_label"] == "Принято"
        assert result[0]["latest_verdict_phase"] == "1"

    def test_load_tasks_fails_closed_when_context_is_missing(self):
        wdb = MagicMock()
        wdb.get_tasks.return_value = [
            {
                "id": 1,
                "task_key": "RUN-1",
                "project_id": 7,
                "workflow_id": 1,
                "status": "active",
                "current_phase_id": 1,
                "current_phase_code": "1",
                "current_phase_name": "One",
            }
        ]
        wdb.get_workflows.return_value = [{"id": 1}]
        wdb.get_phases.return_value = [{"id": 1, "code": "1", "name": "One"}]
        wdb.list_phase_events_batch.return_value = {1: []}
        wdb.step_history.latest_for_tasks.return_value = []
        wdb.get_projects.return_value = []

        with pytest.raises(ValueError, match="не найден неймспейс 7"):
            _service(wdb)._load_tasks()

    def test_missing_task_workflow_id_fails_closed_without_project_fallback(self):
        wdb = MagicMock()
        wid, phases = _service(wdb)._resolve_task_workflow_id(
            {"workflow_id": None, "project": {"workflow_id": 5}}, wdb
        )
        assert wid is None
        assert phases == []
        wdb.get_phases.assert_not_called()

    def test_compute_completion_time_empty_done_entries(self):
        with pytest.raises(ValueError, match="нет события completed"):
            _service(None)._compute_completion_time(
                {"status": "done", "task_key": "RUN-1", "updated_at": "2026-01-01"}, []
            )

    def test_phase_history_uses_consecutive_numbers_after_phase_order_sort(self):
        wdb = MagicMock()
        phases = [
            {"id": 30, "phase_order": 30, "code": "internal.c", "name": "Third"},
            {"id": 10, "phase_order": 10, "code": "internal.a", "name": "First"},
            {"id": 20, "phase_order": 20, "code": "internal.b", "name": "Second"},
        ]
        history = [
            {"phase_id": 30, "event_type": "completed", "occurred_at": "2026-01-03"},
            {"phase_id": 10, "event_type": "completed", "occurred_at": "2026-01-01"},
            {"phase_id": 20, "event_type": "completed", "occurred_at": "2026-01-02"},
        ]

        blocks = _service(wdb)._build_phase_history_blocks(history, phases, phases[0], "done")
        displayed_phases = [phase for block in blocks for phase in block["phases"]]

        assert [phase["phase_code"] for phase in displayed_phases] == [
            "internal.a",
            "internal.b",
            "internal.c",
        ]
        assert [phase["sequence_number"] for phase in displayed_phases] == [1, 2, 3]

    def test_get_task_detail_empty_history_fails_closed(self):
        wdb = MagicMock()
        wdb.get_task_by_key.return_value = {
            "id": 1,
            "task_key": "RUN-1",
            "title": "t",
            "project_id": 1,
            "status": "active",
            "current_phase_id": 1,
            "current_phase_code": "-1",
            "current_phase_name": "Start",
            "workflow_id": 1,
        }
        wdb.list_phase_events.return_value = []
        wdb.get_phases.return_value = [
            {"id": 1, "workflow_id": 1, "phase_order": 1, "code": "-1", "name": "Start"}
        ]
        wdb.list_step_history.return_value = []
        project = MagicMock()
        project.to_dict.return_value = {"id": 1, "code": "RUN", "name": "Runs"}
        wdb.projects.get_by_id.return_value = project

        with pytest.raises(ValueError, match="обязательный журнал событий"):
            _service(wdb)._get_task_detail("RUN-1")

    @pytest.mark.parametrize(
        ("status", "current_phase_id"),
        [("done", 2), ("active", 3)],
    )
    def test_task_detail_progress_uses_events_and_current_snapshot(self, status, current_phase_id):
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
            "current_phase_id": current_phase_id,
            "workflow_id": 1,
        }
        wdb.get_phases.return_value = phases
        wdb.list_phase_events.return_value = [
            {"phase_id": 1, "event_type": "completed", "occurred_at": "2026-01-01"},
            {"phase_id": 2, "event_type": "completed", "occurred_at": "2026-01-02"},
            *(
                [{"phase_id": 3, "event_type": "entered", "occurred_at": "2026-01-03"}]
                if status == "active"
                else []
            ),
        ]
        wdb.list_step_history.return_value = []

        result = _service(wdb)._get_task_detail("RUN-1")

        assert result is not None
        assert result["progress_done"] == 2
        assert result["progress_total"] == 3
        assert result["workflow_phase_count"] == 3
