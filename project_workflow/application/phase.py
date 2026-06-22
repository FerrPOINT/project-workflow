"""Application services — use cases."""
from __future__ import annotations

from typing import Any

from project_workflow.domain.repositories import UnitOfWork


class PhaseServiceApp:
    """Use cases for phases."""

    DEFAULT_PHASE_NAME = "Новая фаза"

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def _generate_code(self, workflow_id: int, order: int) -> str:
        prefix = f"wf-{workflow_id}-phase-"
        existing = self._uow.phases.list(workflow_id)
        max_num = 0
        for phase in existing:
            if phase.code.startswith(prefix):
                suffix = phase.code[len(prefix):]
                try:
                    max_num = max(max_num, int(suffix))
                except ValueError:
                    pass
        return f"{prefix}{max_num + 1}"

    def create_phase(self, data: dict[str, Any]) -> dict[str, Any]:
        workflow_id = int(data["workflow_id"])
        with self._uow:
            order = data.get("phase_order")
            if order is None:
                order = self._uow.phases.get_next_order(workflow_id)
            else:
                order = int(order)
                existing = self._uow.phases.list(workflow_id)
                if any(p.phase_order == order for p in existing):
                    self._uow.phases.shift_orders(workflow_id, order, delta=1)

            phase_data = {
                "workflow_id": workflow_id,
                "code": data.get("code") or self._generate_code(workflow_id, order),
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
            return phase.to_dict()

    def list_phases(self, workflow_id: int | None = None) -> list[dict[str, Any]]:
        with self._uow:
            return [p.to_dict() for p in self._uow.phases.list(workflow_id=workflow_id)]

    def get_phase(self, phase_id: int) -> dict[str, Any] | None:
        with self._uow:
            p = self._uow.phases.get_by_id(phase_id)
            return p.to_dict() if p else None

    def update_phase(self, phase_id: int, data: dict[str, Any]) -> None:
        with self._uow:
            self._uow.phases.update(phase_id, data)
            return None

    def delete_phase(self, phase_id: int) -> None:
        with self._uow:
            self._uow.phases.delete(phase_id)
            return None

