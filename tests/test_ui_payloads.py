"""Tests for interfaces.ui.payloads."""
from __future__ import annotations

from project_workflow.interfaces.ui.payloads import _phase_create_payload, _workflow_form_payload


def test_workflow_form_payload():
    assert _workflow_form_payload({"name": " W ", "description": " D "}) == {
        "name": "W",
        "description": "D",
    }


def test_phase_create_payload_defaults():
    payload = _phase_create_payload({})
    assert payload["name"] == "Новая фаза"
    assert payload["execution_type"] == "sync"


def test_phase_create_payload_invalid_execution_type():
    payload = _phase_create_payload({"execution_type": "weird"})
    assert payload["execution_type"] == "sync"


def test_phase_create_payload_code_blank():
    payload = _phase_create_payload({"code": "  "})
    assert payload["code"] is None
