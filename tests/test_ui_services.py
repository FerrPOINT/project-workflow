"""Tests for interfaces.ui.services facade."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow.interfaces.ui import services as services_mod


def test_get_db():
    db = MagicMock()
    state = MagicMock()
    state.get_db.return_value = db
    with patch.object(services_mod, "_get_app_state", return_value=state):
        assert services_mod._get_db() is db


def test_ui_data_service():
    state = MagicMock()
    with patch.object(services_mod, "_get_app_state", return_value=state):
        svc = services_mod._ui_data_service()
        assert svc is not None


def test_load_functions_delegate_to_ui_data_service():
    mock_svc = MagicMock()
    mock_svc._load_workflows.return_value = [{"id": 1}]
    mock_svc._load_phases.return_value = [{"id": 2}]
    mock_svc._load_phase_detail.return_value = {"id": 3}
    mock_svc._load_tasks.return_value = [{"id": 4}]
    mock_svc._load_projects.return_value = [{"id": 5}]
    mock_svc._load_dashboard.return_value = {"count": 1}
    mock_svc._get_task_detail.return_value = {"id": 6}

    with patch.object(services_mod, "_ui_data_service", return_value=mock_svc):
        assert services_mod._load_workflows() == [{"id": 1}]
        assert services_mod._load_phases() == [{"id": 2}]
        assert services_mod._load_phase_detail(3) == {"id": 3}
        assert services_mod._load_tasks() == [{"id": 4}]
        assert services_mod._load_projects() == [{"id": 5}]
        assert services_mod._load_dashboard() == {"count": 1}
        assert services_mod._get_task_detail("T-1") == {"id": 6}


def test_resolve_task_phase():
    db = MagicMock()
    db.get_phases.return_value = [{"id": 1, "code": "p1"}]
    with patch.object(services_mod, "_get_db", return_value=db):
        token, phase = services_mod._resolve_task_phase("p1")
        assert token == "p1"
        assert phase == {"id": 1, "code": "p1"}


def test_resolve_task_phase_local():
    phases = [
        {"id": 1, "code": "p1"},
        {"id": 2, "code": "p2"},
    ]
    token, phase = services_mod._resolve_task_phase_local("p2", phases)
    assert token == "p2"
    assert phase == {"id": 2, "code": "p2"}


def test_resolve_task_phase_local_not_found():
    token, phase = services_mod._resolve_task_phase_local("missing", [])
    assert token == "missing"
    assert phase is None
