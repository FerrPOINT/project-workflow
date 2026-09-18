"""Application services — use cases."""

from __future__ import annotations

from typing import Any

from project_workflow.domain import WorkflowMode
from project_workflow.domain.repositories import UnitOfWork


class PhaseServiceApp:
    """Use cases for phases."""

    DEFAULT_PHASE_NAME = "Новая фаза"

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def _legacy_mode(self, workflow_id: int) -> WorkflowMode:
        default = self._uow.workflow_modes.get_by_key(workflow_id, "default")
        if default is not None:
            return default
        modes = list(self._uow.workflow_modes.list(workflow_id))
        return modes[0] if modes else self._uow.workflow_modes.ensure_default(workflow_id)

    def _generate_code(self, workflow_id: int, mode_id: int, order: int) -> str:
        prefix = f"wf-{workflow_id}-phase-"
        existing = self._uow.phases.list(workflow_id, mode_id)
        max_num = 0
        for phase in existing:
            if phase.code.startswith(prefix):
                suffix = phase.code[len(prefix) :]
                try:
                    max_num = max(max_num, int(suffix))
                except ValueError:
                    pass
        return f"{prefix}{max_num + 1}"

    def create_phase(self, data: dict[str, Any]) -> dict[str, Any]:
        workflow_id = int(data["workflow_id"])
        mode_id_raw = data.get("mode_id")
        mode: WorkflowMode | None
        if mode_id_raw is None:
            mode = self._legacy_mode(workflow_id)
        else:
            mode = self._uow.workflow_modes.get_by_id(int(mode_id_raw))
            if mode is None or mode.workflow_id != workflow_id:
                raise ValueError("mode_id does not belong to workflow")
        if mode.id is None:
            raise RuntimeError("Workflow mode has no id")
        mode_id = mode.id
        order = data.get("phase_order")
        if order is None:
            order = self._uow.phases.get_next_order(workflow_id, mode_id)
        else:
            order = int(order)
            existing = self._uow.phases.list(workflow_id, mode_id)
            if any(p.phase_order == order for p in existing):
                self._uow.phases.shift_orders(workflow_id, order, delta=1, mode_id=mode_id)
        phase_data = {
            "workflow_id": workflow_id,
            "mode_id": mode_id,
            "code": data.get("code") or self._generate_code(workflow_id, mode_id, order),
            "name": data.get("name", self.DEFAULT_PHASE_NAME),
            "description": data.get("description", ""),
            "execution_type": data.get("execution_type", "sync"),
            "phase_order": order,
            "agent_id": data.get("agent_id"),
            "next_recommendation": data.get("next_recommendation"),
            "parallel_with": data.get("parallel_with"),
            "rollback_target": data.get("rollback_target"),
            "is_seed_managed": data.get("is_seed_managed", False),
            "min_time_min": data.get("min_time_min", 0),
        }
        pid = self._uow.phases.create(phase_data)
        phase = self._uow.phases.get_by_id(pid)
        if not phase:
            raise RuntimeError("Phase creation failed")
        self._uow.commit()
        return phase.to_dict()

    def list_phases(self, workflow_id: int | None = None, mode_id: int | None = None) -> list[dict[str, Any]]:
        if workflow_id is not None and mode_id is None:
            mode = self._legacy_mode(workflow_id)
            mode_id = mode.id
        return [p.to_dict() for p in self._uow.phases.list(workflow_id=workflow_id, mode_id=mode_id)]

    def get_phase(self, phase_id: int) -> dict[str, Any] | None:
        p = self._uow.phases.get_by_id(phase_id)
        return p.to_dict() if p else None

    def update_phase(self, phase_id: int, data: dict[str, Any]) -> None:
        self._uow.phases.update(phase_id, data)
        self._uow.commit()
        return None

    def delete_phase(self, phase_id: int) -> None:
        self._uow.phases.delete(phase_id)
        self._uow.commit()
        return None
