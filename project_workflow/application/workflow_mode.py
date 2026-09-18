"""Workflow-mode use cases."""

from __future__ import annotations

import re
from typing import Any

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import UnitOfWork

MODE_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class WorkflowModeService:
    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def list_modes(self, workflow_id: int) -> list[dict[str, Any]]:
        return [mode.to_dict() for mode in self._uow.workflow_modes.list(workflow_id)]

    def ensure_default(self, workflow_id: int) -> dict[str, Any]:
        mode = self._uow.workflow_modes.ensure_default(workflow_id)
        self._uow.commit()
        return mode.to_dict()

    def create_mode(self, workflow_id: int, data: dict[str, Any]) -> dict[str, Any]:
        if self._uow.workflows.get_by_id(workflow_id) is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")
        key = str(data.get("key") or "").strip().lower()
        if not MODE_KEY_RE.fullmatch(key):
            raise ValueError("Mode key must match ^[a-z][a-z0-9_-]{0,31}$")
        if self._uow.workflow_modes.get_by_key(workflow_id, key):
            raise ConflictError(f"Mode {key!r} already exists")
        mode_id = self._uow.workflow_modes.create(
            {
                "workflow_id": workflow_id,
                "key": key,
                "name": str(data.get("name") or key).strip(),
                "mode_order": data.get("mode_order"),
            }
        )
        mode = self._uow.workflow_modes.get_by_id(mode_id)
        if mode is None:
            raise RuntimeError("Workflow mode creation failed")
        self._uow.commit()
        return mode.to_dict()

    def update_mode(self, mode_id: int, data: dict[str, Any]) -> dict[str, Any]:
        mode = self._uow.workflow_modes.get_by_id(mode_id)
        if mode is None:
            raise NotFoundError(f"Workflow mode {mode_id} not found")
        updates = dict(data)
        if "key" in updates:
            key = str(updates["key"]).strip().lower()
            if mode.key == "default" and key != "default":
                raise ConflictError("Default mode key cannot be changed")
            if not MODE_KEY_RE.fullmatch(key):
                raise ValueError("Mode key must match ^[a-z][a-z0-9_-]{0,31}$")
            updates["key"] = key
        self._uow.workflow_modes.update(mode_id, updates)
        self._uow.commit()
        updated = self._uow.workflow_modes.get_by_id(mode_id)
        if updated is None:
            raise RuntimeError("Workflow mode update failed")
        return updated.to_dict()

    def delete_mode(self, mode_id: int) -> None:
        mode = self._uow.workflow_modes.get_by_id(mode_id)
        if mode is None:
            raise NotFoundError(f"Workflow mode {mode_id} not found")
        if mode.key == "default":
            raise ConflictError("Default mode cannot be deleted")
        self._uow.workflow_modes.delete(mode_id)
        self._uow.commit()
