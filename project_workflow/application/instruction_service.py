"""Application services — use cases."""
from __future__ import annotations
from typing import Any, cast
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
        iid = self._uow.instructions.create(phase_id, data)
        item = self._uow.instructions.get_by_id(iid)
        if not item:
            raise RuntimeError('Instruction creation failed')
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
        existing_ids = [cast(int, row['id']) for row in existing_rows]
        seen: set[int] = set(instruction_ids)
        full_order = list(instruction_ids) + [iid for iid in existing_ids if iid not in seen]
        orders = [(iid, idx + 1) for idx, iid in enumerate(full_order)]
        self._uow.instructions.reorder(phase_id, orders)
        self._uow.commit()
        return None
__all__ = ['InstructionService']
