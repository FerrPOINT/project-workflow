"""Application services — use cases."""

from __future__ import annotations

from typing import Any, cast

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import UnitOfWork


class InstructionService:
    """Use cases for phase instructions."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def list_instructions(self, phase_id: int) -> list[dict[str, Any]]:
        return list(self._uow.instructions.list(phase_id))

    def get_instruction(self, instruction_id: int) -> dict[str, Any] | None:
        return self._uow.instructions.get_by_id(instruction_id)

    def _lock_phase(self, phase_id: int) -> None:
        phase = self._uow.phases.get_by_id(phase_id)
        if phase is None or phase.workflow_id is None:
            raise NotFoundError(f"Фаза {phase_id} не найдена")
        workflow = self._uow.workflows.lock(phase.workflow_id)
        if workflow is None:
            raise NotFoundError(f"Воркфлоу {phase.workflow_id} не найден")
        if getattr(workflow, "is_locked", False) is True:
            raise ConflictError("Locked workflow revision cannot be changed")
        if not any(item.id == phase_id for item in self._uow.phases.list(phase.workflow_id)):
            raise NotFoundError(f"Фаза {phase_id} не найдена")

    def _lock_instruction(self, instruction_id: int) -> dict[str, Any]:
        initial = self._uow.instructions.get_by_id(instruction_id)
        if initial is None:
            raise NotFoundError(f"Инструкция {instruction_id} не найдена")
        phase_id = cast(int, initial["phase_id"])
        self._lock_phase(phase_id)
        fresh = self._uow.instructions.get_by_id(instruction_id)
        if fresh is None or fresh.get("phase_id") != phase_id:
            raise NotFoundError(f"Инструкция {instruction_id} не найдена")
        return fresh

    def create_instruction(self, phase_id: int, data: dict[str, Any]) -> dict[str, Any]:
        self._lock_phase(phase_id)

        existing_rows = list(self._uow.instructions.list(phase_id))
        requested_step = data.get("step_num")
        if requested_step is None:
            requested_step = len(existing_rows) + 1
        try:
            insertion_step = int(requested_step)
        except (TypeError, ValueError) as exc:
            raise ValueError("step_num должен быть положительным целым числом") from exc
        if insertion_step < 1 or insertion_step > len(existing_rows) + 1:
            raise ValueError(f"step_num должен быть в диапазоне 1..{len(existing_rows) + 1}")

        create_data = {key: value for key, value in data.items() if key != "step_num"}
        try:
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
                raise RuntimeError("Не удалось создать инструкцию")
            self._uow.commit()
            return item
        except Exception:
            self._uow.rollback()
            raise

    def update_instruction(self, instruction_id: int, data: dict[str, Any]) -> None:
        self._lock_instruction(instruction_id)
        try:
            self._uow.instructions.update(instruction_id, data)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return None

    def delete_instruction(self, instruction_id: int) -> None:
        item = self._lock_instruction(instruction_id)
        phase_id = cast(int, item["phase_id"])
        try:
            self._uow.instructions.delete(instruction_id)
            remaining_ids = [
                cast(int, row["id"])
                for row in self._uow.instructions.list(phase_id)
                if row["id"] != instruction_id
            ]
            if remaining_ids:
                self._uow.instructions.reorder(
                    phase_id,
                    [(item_id, index) for index, item_id in enumerate(remaining_ids, 1)],
                )
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return None

    def reorder_instructions(self, phase_id: int, instruction_ids: list[int]) -> None:
        """Persist a complete, unique instruction order for one locked phase."""
        self._lock_phase(phase_id)
        existing_rows = list(self._uow.instructions.list(phase_id))
        existing_ids = [cast(int, row["id"]) for row in existing_rows]
        if not instruction_ids:
            raise ValueError("instruction_ids не может быть пустым")
        if len(instruction_ids) != len(set(instruction_ids)):
            raise ValueError("instruction_ids должен содержать уникальные значения")
        if len(instruction_ids) != len(existing_ids) or set(instruction_ids) != set(existing_ids):
            raise ConflictError("instruction_ids должен содержать полный набор инструкций одной фазы")
        try:
            orders = [(iid, idx + 1) for idx, iid in enumerate(instruction_ids)]
            self._uow.instructions.reorder(phase_id, orders)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return None


__all__ = ["InstructionService"]
