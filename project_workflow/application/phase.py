"""Application services — use cases."""

from __future__ import annotations

from typing import Any

from project_workflow.domain.exceptions import ConflictError, NotFoundError
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
                suffix = phase.code[len(prefix) :]
                try:
                    max_num = max(max_num, int(suffix))
                except ValueError:
                    pass
        return f"{prefix}{max_num + 1}"

    def _lock_workflow(self, workflow_id: int) -> None:
        if self._uow.workflows.lock(workflow_id) is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")

    def _validate_agent(self, agent_id: Any) -> None:
        if agent_id is not None and self._uow.agents.get_by_id(int(agent_id)) is None:
            raise NotFoundError(f"Agent {agent_id} not found")

    def _validate_links(self, workflow_id: int, phase_code: str, data: dict[str, Any]) -> None:
        phase_codes = {phase.code for phase in self._uow.phases.list(workflow_id)}
        for field in ("parallel_with", "rollback_target"):
            if field not in data or data[field] is None:
                continue
            target = str(data[field]).strip()
            if not target:
                data[field] = None
                continue
            if target == phase_code:
                raise ConflictError(f"{field} cannot reference the same phase")
            if target not in phase_codes:
                raise ConflictError(f"{field} must reference a phase from the same workflow")
            data[field] = target

    def create_phase(self, data: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        workflow_id = int(data["workflow_id"])
        self._lock_workflow(workflow_id)
        existing = list(self._uow.phases.list(workflow_id))
        order = data.get("phase_order")
        if order is None:
            order = self._uow.phases.get_next_order(workflow_id)
        else:
            order = int(order)
            if order <= 0:
                raise ValueError("phase_order must be positive")
            order = min(order, len(existing) + 1)
        code = data.get("code") or self._generate_code(workflow_id, order)
        if any(phase.code == code for phase in existing):
            raise ConflictError(f"Phase code {code!r} already exists in the workflow")
        self._validate_agent(data.get("agent_id"))
        validated = dict(data)
        self._validate_links(workflow_id, code, validated)
        if any(phase.phase_order == order for phase in existing):
            self._uow.phases.shift_orders(workflow_id, order, delta=1)
        phase_data = {
            "workflow_id": workflow_id,
            "code": code,
            "name": validated.get("name", self.DEFAULT_PHASE_NAME),
            "description": validated.get("description", ""),
            "execution_type": validated.get("execution_type", "sync"),
            "phase_order": order,
            "agent_id": validated.get("agent_id"),
            "next_recommendation": validated.get("next_recommendation"),
            "parallel_with": validated.get("parallel_with"),
            "rollback_target": validated.get("rollback_target"),
            "is_seed_managed": validated.get("is_seed_managed", False),
            "min_time_min": validated.get("min_time_min", 0),
        }
        pid = self._uow.phases.create(phase_data)
        phase = self._uow.phases.get_by_id(pid)
        if not phase:
            raise RuntimeError("Phase creation failed")
        if commit:
            self._uow.commit()
        return phase.to_dict()

    def list_phases(self, workflow_id: int | None = None) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self._uow.phases.list(workflow_id=workflow_id)]

    def get_phase(self, phase_id: int) -> dict[str, Any] | None:
        p = self._uow.phases.get_by_id(phase_id)
        return p.to_dict() if p else None

    def prepare_update(self, phase_id: int, data: dict[str, Any]) -> dict[str, Any]:
        phase = self._uow.phases.get_by_id(phase_id)
        if phase is None:
            raise NotFoundError(f"Phase {phase_id} not found")
        if phase.workflow_id is None:
            raise ConflictError("Phase has no owning workflow")
        workflow_id = phase.workflow_id
        self._lock_workflow(workflow_id)
        updates = dict(data)
        if "agent_id" in updates:
            self._validate_agent(updates["agent_id"])
        self._validate_links(workflow_id, phase.code, updates)
        return updates

    def update_phase(self, phase_id: int, data: dict[str, Any], *, commit: bool = True) -> None:
        self._uow.phases.update(phase_id, self.prepare_update(phase_id, data))
        if commit:
            self._uow.commit()
        return None

    def delete_phase(self, phase_id: int, *, commit: bool = True) -> None:
        phase = self._uow.phases.get_by_id(phase_id)
        if phase is None:
            raise NotFoundError(f"Phase {phase_id} not found")
        if phase.workflow_id is None:
            raise ConflictError("Phase has no owning workflow")
        workflow_id = phase.workflow_id
        self._lock_workflow(workflow_id)
        references = self._uow.phases.reference_kinds(phase_id)
        if references:
            raise ConflictError(f"Phase is referenced by {', '.join(sorted(references))}")
        self._uow.phases.delete(phase_id)
        self._uow.phases.resequence(workflow_id)
        if commit:
            self._uow.commit()
        return None

    def reorder_phases(self, orders: list[tuple[int, int]], *, commit: bool = True) -> int:
        if not orders:
            raise ValueError("Phase order list is empty")
        phase_ids = [phase_id for phase_id, _ in orders]
        if len(phase_ids) != len(set(phase_ids)):
            raise ConflictError("Phase order contains duplicate phase ids")

        phases = [self._uow.phases.get_by_id(phase_id) for phase_id in phase_ids]
        if any(phase is None for phase in phases):
            raise NotFoundError("Phase order contains an unknown phase")
        if any(phase is not None and phase.workflow_id is None for phase in phases):
            raise ConflictError("A reordered phase has no owning workflow")
        workflow_ids = {
            phase.workflow_id
            for phase in phases
            if phase is not None and phase.workflow_id is not None
        }
        if len(workflow_ids) != 1:
            raise ConflictError("All reordered phases must belong to one workflow")
        workflow_id = workflow_ids.pop()
        self._lock_workflow(workflow_id)

        current_ids = {phase.id for phase in self._uow.phases.list(workflow_id)}
        if set(phase_ids) != current_ids:
            raise ConflictError("Phase order must include every phase in the workflow exactly once")
        positions = [position for _, position in orders]
        if sorted(positions) != list(range(1, len(orders) + 1)):
            raise ConflictError("Phase order positions must be the contiguous range 1..N")

        for phase_id, position in orders:
            self._uow.phases.update(phase_id, {"phase_order": position})
        if commit:
            self._uow.commit()
        return len(orders)
