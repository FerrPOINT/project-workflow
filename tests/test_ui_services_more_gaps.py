"""Additional coverage gaps for interfaces/ui/services.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
import pytest

pytestmark = [pytest.mark.ui]

from project_workflow.interfaces.ui.helpers import _resolve_task_phase_id
from project_workflow.interfaces.ui.services import (
    _build_parallel_phase_blocks,
    _get_task_detail,
    _load_cli_reference,
    _load_dashboard,
)


def _mock_state(uow=None):
    state = MagicMock()
    state.get_db.return_value = uow or MagicMock()
    state.get_uow.return_value = uow or MagicMock()
    return state


class TestServicesMoreGaps:

    def test_build_parallel_phase_blocks(self):
        blocks = _build_parallel_phase_blocks(
            [
                {"id": 1, "code": "1", "execution_type": "sync"},
                {"id": 2, "code": "2", "execution_type": "parallel", "parallel_with_phase_id": 3},
                {"id": 3, "code": "3", "execution_type": "parallel"},
            ]
        )
        assert blocks[0]["kind"] == "single"
        assert blocks[1]["kind"] == "parallel"

    def test_load_dashboard_verdict_count(self, monkeypatch):
        uow = MagicMock()
        uow.get_projects.return_value = []
        from project_workflow.application.ui import UIDataService

        monkeypatch.setattr("project_workflow.interfaces.ui.services._get_app_state", lambda: _mock_state(uow))
        with (
            patch.object(UIDataService, "_load_tasks") as mock_tasks,
            patch.object(UIDataService, "_load_projects") as mock_projects,
        ):
            mock_tasks.return_value = [{"status": "active", "latest_verdict": "PASS"}]
            mock_projects.return_value = []
            result = _load_dashboard()
        assert result["stats"]["verdicts"]["PASS"] == 1
        assert result["stats"]["verdict_labels"]["PASS"] == "Принято"

    def test_load_dashboard_keeps_blocked_tasks_visible(self, monkeypatch):
        uow = MagicMock()
        from project_workflow.application.ui import UIDataService

        monkeypatch.setattr("project_workflow.interfaces.ui.services._get_app_state", lambda: _mock_state(uow))
        with (
            patch.object(UIDataService, "_load_tasks") as mock_tasks,
            patch.object(UIDataService, "_load_projects") as mock_projects,
        ):
            blocked = {"status": "blocked", "status_label": "Заблокирована", "latest_verdict": "blocked"}
            mock_tasks.return_value = [blocked]
            mock_projects.return_value = []
            result = _load_dashboard()

        assert result["open_tasks"] == [blocked]
        assert result["stats"]["active"] == 0

    def test_get_task_detail_completed_without_event_fails_closed(self, monkeypatch):
        uow = MagicMock()
        uow.get_task_by_key.return_value = {
            "id": 1,
            "task_key": "A-1",
            "status": "done",
            "updated_at": "2025-02-01",
            "workflow_id": 1,
            "current_phase_id": 1,
        }
        uow.list_phase_events.return_value = [
            {"phase_id": 1, "event_type": "entered", "occurred_at": "2025-01-01"}
        ]
        uow.list_step_history.return_value = []
        uow.get_phases.return_value = [
            {"id": 1, "code": "1", "name": "One", "phase_order": 1, "execution_type": "sync"}
        ]
        monkeypatch.setattr("project_workflow.interfaces.ui.services._get_app_state", lambda: _mock_state(uow))
        with pytest.raises(ValueError, match="нет события completed"):
            _get_task_detail("A-1")

    def test_get_task_detail_history_phase_not_found(self, monkeypatch):
        uow = MagicMock()
        uow.get_task_by_key.return_value = {
            "id": 1,
            "task_key": "A-1",
            "status": "active",
            "current_phase_id": 1,
            "workflow_id": 1,
        }
        uow.list_phase_events.return_value = [
            {"phase_id": 1, "event_type": "entered", "occurred_at": "2025-01-01"},
            {"phase_id": 99, "event_type": "completed", "occurred_at": "2025-01-02"},
        ]
        uow.list_step_history.return_value = []
        uow.get_phases.return_value = [
            {"id": 1, "code": "1", "name": "One", "phase_order": 1, "execution_type": "sync"}
        ]
        monkeypatch.setattr("project_workflow.interfaces.ui.services._get_app_state", lambda: _mock_state(uow))
        with pytest.raises(ValueError, match="неизвестные фазы: 99"):
            _get_task_detail("A-1")

    def test_get_task_detail_next_contract_none(self, monkeypatch):
        uow = MagicMock()
        task = {"id": 1, "task_key": "A-1", "status": "active", "current_phase_id": 1, "workflow_id": 1}
        uow.get_task_by_key.return_value = task
        uow.list_phase_events.return_value = [
            {"phase_id": 1, "event_type": "entered", "occurred_at": "2025-01-01"}
        ]
        uow.list_step_history.return_value = [
            {
                "verdict": "pass",
                "worker_report": "done",
                "evaluation_snapshot": {"phase_code": "1", "phase_name": "One"},
                "supervisor_response": {"message": "ok"},
            }
        ]
        uow.get_phases.return_value = [
            {"id": 1, "code": "1", "name": "One", "phase_order": 1, "execution_type": "sync"}
        ]
        monkeypatch.setattr("project_workflow.interfaces.ui.services._get_app_state", lambda: _mock_state(uow))
        result = _get_task_detail("A-1")
        assert result["step_history"][0]["next_contract"] is None
        assert result["step_history"][0]["verdict_label"] == "Принято"

    def test_load_cli_reference(self):
        with patch(
            "project_workflow.interfaces.ui.cli_reference.project_workflow.commands",
            {
                "help": click.Command("help"),
                "ui": click.Command("ui", hidden=True),
            },
            create=True,
        ):
            result = _load_cli_reference()
        assert any(item["name"] == "help" for item in result)
        assert not any(item["name"] == "ui" for item in result)

    def test_resolve_task_phase_unknown_id_is_rejected(self):
        with pytest.raises(ValueError, match="отсутствует"):
            _resolve_task_phase_id(5, [])
