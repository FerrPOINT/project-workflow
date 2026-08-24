"""Application services — use cases."""

from __future__ import annotations

from typing import Any, cast

from project_workflow.domain.exceptions import NotFoundError
from project_workflow.domain.repositories import UnitOfWork


class InstructionService:
    """Use cases for phase instructions."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def list_instructions(self, phase_id: int) -> list[dict[str, Any]]:
        return list(self._uow.instructions.list(phase_id))

    def get_instruction(self, instruction_id: int) -> dict[str, Any] | None:
        return self._uow.instructions.get_by_id(instruction_id)

    def create_instruction(self, phase_id: int, data: dict[str, Any]) -> dict[str, Any]:
        phase = self._uow.phases.get_by_id(phase_id)
        if phase is None or phase.workflow_id is None:
            raise NotFoundError(f"Phase {phase_id} not found")
        if self._uow.workflows.lock(phase.workflow_id) is None:
            raise NotFoundError(f"Workflow {phase.workflow_id} not found")
        if not any(item.id == phase_id for item in self._uow.phases.list(phase.workflow_id)):
            raise NotFoundError(f"Phase {phase_id} not found")

        existing_rows = list(self._uow.instructions.list(phase_id))
        requested_step = data.get("step_num")
        if requested_step is None:
            requested_step = len(existing_rows) + 1
        try:
            insertion_step = int(requested_step)
        except (TypeError, ValueError) as exc:
            raise ValueError("step_num must be a positive integer") from exc
        if insertion_step < 1 or insertion_step > len(existing_rows) + 1:
            raise ValueError(f"step_num must be in range 1..{len(existing_rows) + 1}")

        create_data = {key: value for key, value in data.items() if key != "step_num"}
        iid = self._uow.instructions.create(phase_id, create_data)
        if insertion_step <= len(existing_rows):
            ordered_ids = [cast(int, row["id"]) for row in existing_rows]
            ordered_ids.insert(insertion_step - 1, iid)
            self._uow.instructions.reorder(
                phase_id,
                [(instruction_id, index) for index, instruction_id in enumerate(ordered_ids, 1)],
            )
        item = self._uow.instructions.get_by_id(iid)
        if not item:
            raise RuntimeError("Instruction creation failed")
        self._uow.commit()
        return item

    def update_instruction(self, instruction_id: int, data: dict[str, Any]) -> None:
        self._uow.instructions.update(instruction_id, data)
        self._uow.commit()
        return None

    def delete_instruction(self, instruction_id: int) -> None:
        self._uow.instructions.delete(instruction_id)
        self._uow.commit()
        return None

    def reorder_instructions(self, phase_id: int, instruction_ids: list[int]) -> None:
        """Persist a new instruction order: listed ids first, remaining ids appended."""
        existing_rows = self._uow.instructions.list(phase_id)
        existing_ids = [cast(int, row["id"]) for row in existing_rows]
        valid_ids = set(existing_ids)
        requested_ids = [iid for iid in dict.fromkeys(instruction_ids) if iid in valid_ids]
        requested_set = set(requested_ids)
        full_order = requested_ids + [iid for iid in existing_ids if iid not in requested_set]
        orders = [(iid, idx + 1) for idx, iid in enumerate(full_order)]
        self._uow.instructions.reorder(phase_id, orders)
        self._uow.commit()
        return None


__all__ = ["InstructionService"]
