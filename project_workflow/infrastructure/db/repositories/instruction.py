"""SQLAlchemy repository implementations."""

from __future__ import annotations

import builtins
import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from project_workflow.domain.exceptions import NotFoundError
from project_workflow.domain.repositories import InstructionRepository
from project_workflow.infrastructure.db import models as m


def _parse_skills(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Persisted instruction skills contain invalid JSON") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError("Persisted instruction skills must be a JSON string array")
    return parsed


def _dump_skills(skills: list[str] | None) -> str | None:
    if skills in (None, []):
        return None
    if not isinstance(skills, list) or not all(isinstance(item, str) for item in skills):
        raise TypeError("skills must be a list of strings or null")
    return json.dumps(skills, ensure_ascii=False)


class SAInstructionRepository(InstructionRepository):
    """SQLAlchemy implementation of InstructionRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(self, phase_id: int) -> Sequence[dict[str, Any]]:
        rows = (
            self._session.execute(
                select(m.Instruction).where(m.Instruction.phase_id == phase_id).order_by(m.Instruction.step_num)
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": r.id,
                "phase_id": r.phase_id,
                "step_num": r.step_num,
                "description": r.description,
                "execution_type": r.execution_type or "sync",
                "skills": _parse_skills(r.skills),
            }
            for r in rows
        ]

    def get_by_id(self, instruction_id: int) -> dict[str, Any] | None:
        row = self._session.get(m.Instruction, instruction_id)
        if row is None:
            return None
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
        item = m.Instruction(
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
        row = self._session.get(m.Instruction, instruction_id)
        if row is None:
            raise NotFoundError(f"Instruction {instruction_id} not found")
        if "description" in data:
            row.description = data["description"]
        if "execution_type" in data:
            row.execution_type = data["execution_type"]
        if "step_num" in data:
            row.step_num = data["step_num"]
        if "skills" in data:
            row.skills = _dump_skills(data["skills"])

    def delete(self, instruction_id: int) -> None:
        row = self._session.get(m.Instruction, instruction_id)
        if row is None:
            raise NotFoundError(f"Instruction {instruction_id} not found")
        self._session.delete(row)

    def delete_for_phase(self, phase_id: int) -> None:
        self._session.execute(
            text("DELETE FROM instructions WHERE phase_id = :pid"),
            {"pid": phase_id},
        )

    def reorder(self, phase_id: int, orders: builtins.list[tuple[int, int]]) -> None:
        """Reassign step_num values based on (instruction_id, new_step_num) pairs.

        Uses a two-stage raw-SQL update: first shift every instruction in the
        phase out of the target number range, then assign the final numbers.
        This avoids UNIQUE constraint collisions on (phase_id, step_num).
        """
        if not orders:
            return
        offset = len(orders) + 1000
        self._session.execute(
            text("UPDATE instructions SET step_num = step_num + :offset WHERE phase_id = :phase_id"),
            {"offset": offset, "phase_id": phase_id},
        )
        for instruction_id, new_step in orders:
            self._session.execute(
                text(
                    "UPDATE instructions SET step_num = :step "
                    "WHERE id = :id AND phase_id = :phase_id"
                ),
                {"step": new_step, "id": instruction_id, "phase_id": phase_id},
            )
        shifted_ids = (
            self._session.execute(
                select(m.Instruction.id)
                .where(
                    m.Instruction.phase_id == phase_id,
                    m.Instruction.step_num >= offset,
                )
                .order_by(m.Instruction.step_num)
            )
            .scalars()
            .all()
        )
        next_step = max((new_step for _, new_step in orders), default=0) + 1
        for instruction_id in shifted_ids:
            self._session.execute(
                text(
                    "UPDATE instructions SET step_num = :step "
                    "WHERE id = :id AND phase_id = :phase_id"
                ),
                {"step": next_step, "id": instruction_id, "phase_id": phase_id},
            )
            next_step += 1
        self._session.flush()

    def _next_step_num(self, phase_id: int) -> int:
        max_step = self._session.execute(
            select(m.Instruction.step_num)
            .where(m.Instruction.phase_id == phase_id)
            .order_by(m.Instruction.step_num.desc())
        ).scalar()
        return (max_step or 0) + 1


