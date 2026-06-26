"""Additional coverage gaps for interfaces/ui/services.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
import pytest

pytestmark = [pytest.mark.ui]

from project_workflow.interfaces.ui.services import (
    _load_tasks,
    _load_dashboard,
    _get_task_detail,
    _load_cli_reference,
    _parse_key_prefixes,
    _build_parallel_phase_blocks,
    _resolve_task_phase,
)


def _mock_state(uow=None):
    state = MagicMock()
    state.get_db.return_value = uow or MagicMock()
    state.get_uow.return_value = uow or MagicMock()
    return state


class TestServicesMoreGaps:
    def test_load_tasks_response_not_dict(self, monkeypatch):
        uow = MagicMock()
        uow.get_tasks.return_value = [{"id": 1, "task_key": "A-1", "current_phase": "1", "status": "active"}]
        uow.get_workflows.return_value = []
        uow.get_task_history.return_value = []
        uow.get_supervisor_runs.return_value = [{"response": "raw string", "verdict": "pass", "created_at": "2025-01-01T00:00:00"}]
        monkeypatch.setattr("project_workflow.interfaces.ui.services._get_app_state", lambda: _mock_state(uow))
        result = _load_tasks()
        assert result[0]["latest_verdict_message"] == "raw string"[:120]

    def test_parse_key_prefixes(self):
        assert _parse_key_prefixes(["a", " b "]) == ["A", "B"]
        assert _parse_key_prefixes("a\nb") == ["A", "B"]
        assert _parse_key_prefixes(123) == []

    def test_build_parallel_phase_blocks(self):
        blocks = _build_parallel_phase_blocks([
            {"code": "1", "execution_type": "sync"},
            {"code": "2", "execution_type": "parallel"},
            {"code": "3", "execution_type": "sync"},
        ])
        assert blocks[0]["kind"] == "parallel"
        assert blocks[1]["kind"] == "single"

    def test_load_dashboard_verdict_count(self, monkeypatch):
        uow = MagicMock()
        uow.get_projects.return_value = []
        monkeypatch.setattr("project_workflow.interfaces.ui.services._get_app_state", lambda: _mock_state(uow))
        with patch("project_workflow.interfaces.ui.services._load_tasks") as mock_tasks, \
             patch("project_workflow.interfaces.ui.services._load_projects") as mock_projects:
            mock_tasks.return_value = [{"status": "active", "latest_verdict": "PASS"}]
            mock_projects.return_value = []
            result = _load_dashboard()
        assert result["stats"]["verdicts"]["PASS"] == 1

    def test_get_task_detail_completed_at_fallback(self, monkeypatch):
        uow = MagicMock()
        uow.get_task_by_key.return_value = {"id": 1, "task_key": "A-1", "status": "done", "updated_at": "2025-02-01", "workflow_id": 1}
        uow.get_task_history.return_value = [{"phase_id": 1, "status": "done", "completed_at": ""}]
        uow.get_supervisor_runs.return_value = []
        uow.get_projects.return_value = []
        uow.get_phase.return_value = None
        uow.get_phases.return_value = []
        monkeypatch.setattr("project_workflow.interfaces.ui.services._get_app_state", lambda: _mock_state(uow))
        result = _get_task_detail("A-1")
        assert result["completed_at"] == "2025-02-01"

    def test_get_task_detail_history_phase_not_found(self, monkeypatch):
        uow = MagicMock()
        uow.get_task_by_key.return_value = {"id": 1, "task_key": "A-1", "status": "active", "current_phase": "1", "workflow_id": 1}
        uow.get_task_history.return_value = [{"phase_id": 99, "status": "done", "completed_at": ""}]
        uow.get_supervisor_runs.return_value = []
        uow.get_projects.return_value = []
        uow.get_phase.return_value = None
        uow.get_phases.return_value = []
        monkeypatch.setattr("project_workflow.interfaces.ui.services._get_app_state", lambda: _mock_state(uow))
        result = _get_task_detail("A-1")
        assert result["phase_history"] == []

    def test_get_task_detail_next_contract_none(self, monkeypatch):
        uow = MagicMock()
        task = {"id": 1, "task_key": "A-1", "status": "active", "current_phase": "1", "workflow_id": 1}
        uow.get_task_by_key.return_value = task
        uow.get_task_history.return_value = []
        uow.get_supervisor_runs.return_value = [{"verdict": "pass", "response": {"message": "ok"}}]
        uow.get_projects.return_value = []
        uow.get_phases.return_value = []
        uow.get_phase.return_value = None
        monkeypatch.setattr("project_workflow.interfaces.ui.services._get_app_state", lambda: _mock_state(uow))
        result = _get_task_detail("A-1")
        assert result["supervisor_runs"][0]["next_contract"] is None

    def test_load_cli_reference(self):
        with patch("project_workflow.interfaces.ui.services.project_workflow.commands", {
            "help": click.Command("help"),
            "ui": click.Command("ui", hidden=True),
        }, create=True):
            result = _load_cli_reference()
        assert any(item["name"] == "help" for item in result)
        assert not any(item["name"] == "ui" for item in result)

    def test_resolve_task_phase_numeric(self, monkeypatch):
        uow = MagicMock()
        uow.get_phase.return_value = {"id": 5, "code": "PH-5"}
        monkeypatch.setattr("project_workflow.interfaces.ui.services._get_app_state", lambda: _mock_state(uow))
        token, phase = _resolve_task_phase("5", workflow_id=1)
        assert token == "5"
        assert phase["code"] == "PH-5"
