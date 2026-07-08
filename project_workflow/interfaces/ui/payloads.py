"""Form payload normalizers for UI routes."""

from __future__ import annotations

from typing import Any


def _workflow_form_payload(body: dict[str, Any]) -> dict[str, Any]:
    """Normalize workflow creation/update payload."""
    name = str(body.get("name", "")).strip()
    description = str(body.get("description", "")).strip()
    return {
        "name": name,
        "description": description,
    }


def _phase_create_payload(body: dict[str, Any]) -> dict[str, Any]:
    """Normalize phase creation payload with safe defaults."""
    name = str(body.get("name", "")).strip()
    if not name:
        name = "Новая фаза"
    description = str(body.get("description", "")).strip()
    execution_type = str(body.get("execution_type", "sync")).strip()
    if execution_type not in {"sync", "parallel"}:
        execution_type = "sync"
    return {
        "name": name,
        "description": description,
        "execution_type": execution_type,
        "workflow_id": body.get("workflow_id"),
        "phase_order": body.get("phase_order"),
        "code": str(body.get("code", "")).strip() or None,
        "agent_id": body.get("agent_id"),
    }
