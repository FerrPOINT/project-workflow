"""SQLAlchemy repository implementations."""

from __future__ import annotations

import builtins
import json
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import PhaseInstructionRepository
from project_workflow.infrastructure.db import models as m


def _parse_skills(raw: str | None) -> list[str]:
    if raw is None:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Сохранённые skills инструкции содержат некорректный JSON") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError("Сохранённые skills инструкции должны быть JSON-массивом строк")
    return parsed


def _dump_skills(skills: list[str] | None) -> str | None:
    if skills in (None, []):
        return None
    if not isinstance(skills, list) or not all(isinstance(item, str) for item in skills):
        raise TypeError("skills должен быть массивом строк или null")
    return json.dumps(skills, ensure_ascii=False)


class SAPhaseInstructionRepository(PhaseInstructionRepository):

    def __init__(self, session: Session):
        self._session = session

    def list(self, phase_id: int) -> Sequence[dict[str, Any]]:
        rows = (
            self._session.execute(
                select(m.PhaseInstruction)
                .where(m.PhaseInstruction.phase_id == phase_id)
                .order_by(m.PhaseInstruction.step_num)
            )
            .scalars()
            .all()
        )
        return [self._to_dict(row) for row in rows]

    def list_for_phases(self, phase_ids: Sequence[int]) -> Mapping[int, Sequence[dict[str, Any]]]:
        result: dict[int, list[dict[str, Any]]] = {phase_id: [] for phase_id in phase_ids}
        if not phase_ids:
            return result
        rows = self._session.execute(
            select(m.PhaseInstruction)
            .where(m.PhaseInstruction.phase_id.in_(phase_ids))
            .order_by(m.PhaseInstruction.phase_id, m.PhaseInstruction.step_num)
        ).scalars().all()
        for row in rows:
            result.setdefault(int(row.phase_id), []).append(self._to_dict(row))
        return result

    def get_by_id(self, instruction_id: int) -> dict[str, Any] | None:
        row = self._session.get(m.PhaseInstruction, instruction_id)
        if row is None:
            return None
        return self._to_dict(row)

    @staticmethod
    def _to_dict(row: m.PhaseInstruction) -> dict[str, Any]:
        return {
            "id": row.id,
            "phase_id": row.phase_id,
            "step_num": row.step_num,
            "description": row.description,
            "execution_type": row.execution_type or "sync",
            "skills": _parse_skills(row.skills),
        }

    def create(self, phase_id: int, data: dict[str, Any]) -> int:
        next_step = self._next_step_num(phase_id)
        item = m.PhaseInstruction(
            phase_id=phase_id,
            step_num=data.get("step_num", next_step),
            description=data["description"],
            execution_type=data.get("execution_type", "sync"),
            skills=_dump_skills(data.get("skills")),
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def update(self, instruction_id: int, data: dict[str, Any]) -> None:
        row = self._session.get(m.PhaseInstruction, instruction_id)
        if row is None:
            raise NotFoundError(f"Инструкция {instruction_id} не найдена")
        if "description" in data:
            row.description = data["description"]
        if "execution_type" in data:
            row.execution_type = data["execution_type"]
        if "step_num" in data:
            row.step_num = data["step_num"]
        if "skills" in data:
            row.skills = _dump_skills(data["skills"])

    def delete(self, instruction_id: int) -> None:
        row = self._session.get(m.PhaseInstruction, instruction_id)
        if row is None:
            raise NotFoundError(f"Инструкция {instruction_id} не найдена")
        self._session.delete(row)

    def delete_for_phase(self, phase_id: int) -> None:
        self._session.execute(
            text("DELETE FROM phase_instructions WHERE phase_id = :pid"),
            {"pid": phase_id},
        )

    def reorder(self, phase_id: int, orders: builtins.list[tuple[int, int]]) -> None:
        """Reassign step_num values based on (instruction_id, new_step_num) pairs.

        Uses a two-stage raw-SQL update: first shift every instruction in the
        phase out of the target number range, then assign the final numbers.
        This avoids UNIQUE constraint collisions on (phase_id, step_num).
        """
        existing_ids = list(
            self._session.execute(
                select(m.PhaseInstruction.id)
                .where(m.PhaseInstruction.phase_id == phase_id)
                .order_by(m.PhaseInstruction.step_num)
            ).scalars()
        )
        requested_ids = [instruction_id for instruction_id, _ in orders]
        positions = [position for _, position in orders]
        if (
            not orders
            or len(requested_ids) != len(set(requested_ids))
            or set(requested_ids) != set(existing_ids)
            or sorted(positions) != list(range(1, len(existing_ids) + 1))
        ):
            raise ConflictError("Перестановка должна содержать полный порядок инструкций фазы")
        offset = len(orders) + 1000
        self._session.execute(
            text("UPDATE phase_instructions SET step_num = step_num + :offset WHERE phase_id = :phase_id"),
            {"offset": offset, "phase_id": phase_id},
        )
        for instruction_id, new_step in orders:
            self._session.execute(
                text(
                    "UPDATE phase_instructions SET step_num = :step "
                    "WHERE id = :id AND phase_id = :phase_id"
                ),
                {"step": new_step, "id": instruction_id, "phase_id": phase_id},
            )
        self._session.flush()
        self._session.expire_all()

    def _next_step_num(self, phase_id: int) -> int:
        max_step = self._session.execute(
            select(m.PhaseInstruction.step_num)
            .where(m.PhaseInstruction.phase_id == phase_id)
            .order_by(m.PhaseInstruction.step_num.desc())
        ).scalar()
        return (max_step or 0) + 1


