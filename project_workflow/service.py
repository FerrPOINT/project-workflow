"""PhaseService — бизнес-логика для работы с фазами.

Удалены: questions, answers, checkups. Только CRUD для фаз/инструкций/checks/evidence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from project_workflow.db import WorkflowDB


class PhaseService:
    """CRUD operations for phases, instructions, checks, evidence."""

    def __init__(self, db: "WorkflowDB"):
        self._db = db

    # ── Bulk сохранение инструкций (atomic) ─────────────────────────────

    def save_instructions(self, phase_id: int | str, items: list[dict[str, Any]]) -> list[int]:
        """Полностью перезаписать инструкции фазы. Возвращает новые id в порядке items."""
        # Resolve phase_id (code or int) to integer DB id
        phase_row = self._db.get_phase(phase_id)
        if not phase_row:
            raise ValueError(f"Phase not found: {phase_id}")
        resolved = phase_row["id"]
        # Prefer SQLAlchemy if the DB handle exposes a SQLAlchemy engine (UI/SA path).
        sa_engine = getattr(self._db, "_sa_engine", None)
        if sa_engine is not None:
            return self._save_instructions_sa(resolved, items, sa_engine)

        with self._db._conn() as conn:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM instructions WHERE phase_id = ?", (resolved,))
            ids = []
            for idx, item in enumerate(items, 1):
                c = conn.execute(
                    """
                    INSERT INTO instructions (phase_id, step_num, description, execution_type, skills)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        resolved,
                        idx,
                        item["description"],
                        item.get("execution_type", "sync"),
                        self.serialize_skills(self.normalize_skills(item.get("skills"))),
                    ),
                )
                ids.append(c.lastrowid)
            conn.commit()
            return ids

    def _save_instructions_sa(self, resolved: int, items: list[dict[str, Any]], engine) -> list[int]:
        from project_workflow.infrastructure.db import models as m
        from sqlalchemy.orm import Session

        with Session(engine, expire_on_commit=False) as session:
            session.query(m.Instruction).filter(m.Instruction.phase_id == resolved).delete()
            ids: list[int] = []
            for idx, item in enumerate(items, 1):
                inst = m.Instruction(
                    phase_id=resolved,
                    step_num=idx,
                    description=item["description"],
                    execution_type=item.get("execution_type", "sync"),
                    skills=self.serialize_skills(self.normalize_skills(item.get("skills"))),
                )
                session.add(inst)
                session.flush()
                ids.append(int(inst.id))
            session.commit()
            return ids

    def save_checks(self, phase_id: int | str, items: list[dict[str, Any]]) -> list[int]:
        """Перезаписать checks фазы. Возвращает новые id."""
        phase_row = self._db.get_phase(phase_id)
        if not phase_row:
            raise ValueError(f"Phase not found: {phase_id}")
        resolved = phase_row["id"]
        sa_engine = getattr(self._db, "_sa_engine", None)
        if sa_engine is not None:
            return self._save_checks_sa(resolved, items, sa_engine)

        with self._db._conn() as conn:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM checks WHERE phase_id = ?", (resolved,))
            ids = []
            for item in items:
                c = conn.execute(
                    "INSERT INTO checks (phase_id, description) VALUES (?, ?)",
                    (resolved, item["description"]),
                )
                ids.append(c.lastrowid)
            conn.commit()
            return ids

    def _save_checks_sa(self, resolved: int, items: list[dict[str, Any]], engine) -> list[int]:
        from project_workflow.infrastructure.db import models as m
        from sqlalchemy.orm import Session

        with Session(engine, expire_on_commit=False) as session:
            session.query(m.Check).filter(m.Check.phase_id == resolved).delete()
            ids: list[int] = []
            for item in items:
                chk = m.Check(phase_id=resolved, description=item["description"])
                session.add(chk)
                session.flush()
                ids.append(int(chk.id))
            session.commit()
            return ids

    def save_evidence(self, phase_id: int | str, items: list[dict[str, Any]]) -> list[int]:
        """Сохранить evidence фазы."""
        phase_row = self._db.get_phase(phase_id)
        if not phase_row:
            raise ValueError(f"Phase not found: {phase_id}")
        resolved = phase_row["id"]
        sa_engine = getattr(self._db, "_sa_engine", None)
        if sa_engine is not None:
            return self._save_evidence_sa(resolved, items, sa_engine)

        with self._db._conn() as conn:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM evidence WHERE phase_id = ?", (resolved,))
            ids = []
            for item in items:
                c = conn.execute(
                    "INSERT INTO evidence (phase_id, description) VALUES (?, ?)",
                    (resolved, item["description"]),
                )
                ids.append(c.lastrowid)
            conn.commit()
            return ids

    def _save_evidence_sa(self, resolved: int, items: list[dict[str, Any]], engine) -> list[int]:
        from project_workflow.infrastructure.db import models as m
        from sqlalchemy.orm import Session

        with Session(engine, expire_on_commit=False) as session:
            session.query(m.Evidence).filter(m.Evidence.phase_id == resolved).delete()
            ids: list[int] = []
            for item in items:
                ev = m.Evidence(phase_id=resolved, description=item["description"])
                session.add(ev)
                session.flush()
                ids.append(int(ev.id))
            session.commit()
            return ids

    # ── Read helpers ──────────────────────────────────────────────────

    def get_phase_detail(self, phase_id: int | str) -> dict:
        """Вернуть фазу со всем вложенным контентом."""
        phase = self._db.get_phase(phase_id)
        if not phase:
            return {}

        instructions = []
        for item in self._db.get_phase_instructions(phase_id):
            normalized = dict(item)
            normalized["skills"] = self.normalize_skills(item.get("skills"))
            instructions.append(normalized)

        return {
            **phase,
            "instructions": instructions,
            "checks": self._db.get_phase_checks(phase_id),
            "evidence": self._db.get_phase_evidence(phase_id),
        }

    # ── Update phase (metadata) ──────────────────────────────────────

    def update_phase(self, phase_id: int | str, data: dict) -> None:
        self._db.update_phase(phase_id, data)

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def normalize_skills(raw: Any) -> list[str]:
        if raw in (None, "", []):
            return []
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        if isinstance(raw, str):
            parsed = PhaseService.parse_skills(raw)
            return [str(item).strip() for item in parsed if str(item).strip()]
        return []

    @staticmethod
    def parse_skills(raw: str | None) -> list[str]:
        if not raw:
            return []
        import json
        try:
            parsed = json.loads(raw)
        except Exception:
            return []
        return parsed if isinstance(parsed, list) else []

    @staticmethod
    def serialize_skills(skills: list[str] | None) -> str | None:
        normalized = PhaseService.normalize_skills(skills)
        if not normalized:
            return None
        import json
        return json.dumps(normalized, ensure_ascii=False)

    def get_all_phases(self) -> list[dict]:
        """Все фазы с контентом (для API)."""
        rows = self._db.get_phases()
        return [self.get_phase_detail(r["id"]) for r in rows]
