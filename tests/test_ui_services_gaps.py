"""Additional tests for UI services helper coverage gaps."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.ui]

from project_workflow.interfaces.ui import (
    _instruction_service,
    _phase_create_payload,
    _phase_service,
    _project_service,
    _resolve_task_phase,
    _task_service,
    _workflow_form_payload,
    _workflow_service,
)
from project_workflow.interfaces.ui.schemas import (
    AgentCreate,
    PhaseCreate,
    PhaseUpdate,
    ProjectCreate,
    ProjectUpdate,
    WorkflowCreate,
    WorkflowUpdate,
)


class TestServiceHelpers:
    def test_service_helpers_call_get_db(self, monkeypatch):
        db = MagicMock()
        monkeypatch.setattr("project_workflow.interfaces.ui._app_state", MagicMock(get_db=lambda: db))
        assert _workflow_service() is db
        assert _phase_service() is db
        assert _project_service() is db
        assert _task_service() is db
        assert _instruction_service() is db


class TestPayloadHelpers:
    def test_phase_create_payload_defaults(self):
        payload = _phase_create_payload({"workflow_id": 1})
        assert payload["name"] == "Новая фаза"
        assert payload["execution_type"] == "sync"

    def test_phase_create_payload_invalid_execution_type(self):
        payload = _phase_create_payload({"name": "X", "execution_type": "bad", "workflow_id": 1})
        assert payload["execution_type"] == "sync"


class TestWorkflowFormPayload:
    def test_strips_and_defaults(self):
        payload = _workflow_form_payload({"name": "  WF  ", "description": "  desc  "})
        assert payload["name"] == "WF"
        assert payload["description"] == "desc"


class TestResolveTaskPhaseRedirects:
    def test_legacy_redirect_via_get_phase(self, monkeypatch):
        from project_workflow import config
        monkeypatch.setattr(config, "LEGACY_PHASE_REDIRECTS", {"old": "1"})
        db = MagicMock()
        db.get_phases.return_value = []
        db.get_phase.side_effect = lambda token: {"id": 99, "code": "1", "name": "One"} if str(token) == "1" else None
        token, phase = _resolve_task_phase("old", _db=db)
        assert token == "1"
        assert phase["id"] == 99

    def test_numeric_phase_lookup(self):
        db = MagicMock()
        db.get_phases.return_value = []
        db.get_phase.return_value = {"id": 5, "code": "5", "name": "Five"}
        token, phase = _resolve_task_phase("5", _db=db)
        assert token == "5"
        assert phase["id"] == 5

    def test_unresolvable_numeric(self):
        db = MagicMock()
        db.get_phases.return_value = []
        db.get_phase.return_value = None
        token, phase = _resolve_task_phase("999", _db=db)
        assert token == "999"
        assert phase is None


class TestSchemas:
    def test_phase_create_insert_after_string(self):
        p = PhaseCreate(workflow_id=1, insert_after="2")
        assert p.phase_order == 3

    def test_phase_create_coerce_invalid_phase_order(self):
        p = PhaseCreate(workflow_id=1, phase_order="bad")
        assert p.phase_order is None

    def test_phase_update_excluded_fields(self):
        p = PhaseUpdate(name="X", code="ignored", phase_num=99)
        assert p.name == "X"
        assert "code" not in p.model_dump(exclude={"code", "phase_num", "phase_order"})

    def test_project_create_key_prefixes_from_string(self):
        p = ProjectCreate(code="p", key_prefixes="foo\nbar")
        assert p.key_prefixes == ["FOO", "BAR"]

    def test_project_create_default_prefixes(self):
        p = ProjectCreate(code="p", key_prefixes=[])
        assert p.key_prefixes

    def test_project_update_key_prefixes_none(self):
        p = ProjectUpdate(code="p")
        assert p.key_prefixes is None

    def test_workflow_create_defaults(self):
        w = WorkflowCreate()
        assert w.name is None
        assert w.description == ""

    def test_workflow_update_fields(self):
        w = WorkflowUpdate(name="N", description="D", code="C")
        assert w.name == "N"

    def test_agent_create_valid(self):
        a = AgentCreate(name="A")
        assert a.name == "A"
