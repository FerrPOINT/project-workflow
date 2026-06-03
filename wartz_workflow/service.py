"""Service layer — бизнес-логика workflow.

Тонкие контроллеры (ui.py) → Service (service.py) → Data Access (db.py)
"""

from __future__ import annotations

import json
from typing import Any

from . import db


class PhaseService:
    """Бизнес-логика фаз: bulk сохранение, порядок step_num, compose деталей."""

    def __init__(self, wdb: db.WorkflowDB):
        self._db = wdb

    # ── Bulk сохранение инструкций (atomic) ─────────────────────────────

    def save_instructions(self, phase_id: str, items: list[dict[str, Any]]) -> list[int]:
        """Полностью перезаписать инструкции фазы. Возвращает новые id в порядке items.

        items: [{description, execution_type?, tool?}, ...]
        step_num = индекс (1-based).
        """
        conn = self._db._conn()
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM instructions WHERE phase_id = ?", (phase_id,))
            ids = []
            for idx, item in enumerate(items, 1):
                c = conn.execute(
                    """
                    INSERT INTO instructions (phase_id, step_num, description, execution_type, tool)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        phase_id,
                        idx,
                        item["description"],
                        item.get("execution_type", "sync"),
                        item.get("tool"),
                    ),
                )
                ids.append(c.lastrowid)
            conn.commit()
            return ids
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def save_checks(self, phase_id: str, items: list[dict[str, Any]]) -> list[int]:
        """Перезаписать checks фазы. Возвращает новые id."""
        conn = self._db._conn()
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM checks WHERE phase_id = ?", (phase_id,))
            ids = []
            for item in items:
                c = conn.execute(
                    """
                    INSERT INTO checks (phase_id, description, command)
                    VALUES (?, ?, ?)
                    """,
                    (phase_id, item["description"], item.get("command")),
                )
                ids.append(c.lastrowid)
            conn.commit()
            return ids
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def save_evidence(self, phase_id: str, items: list[dict[str, Any]]) -> list[int]:
        """Перезаписать evidence фазы. Возвращает новые id."""
        conn = self._db._conn()
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM evidence WHERE phase_id = ?", (phase_id,))
            ids = []
            for item in items:
                c = conn.execute(
                    """
                    INSERT INTO evidence (phase_id, description, validator)
                    VALUES (?, ?, ?)
                    """,
                    (phase_id, item["description"], item.get("validator")),
                )
                ids.append(c.lastrowid)
            conn.commit()
            return ids
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Составные данные ────────────────────────────────────────────────

    def get_phase_detail(self, phase_id: str) -> dict[str, Any] | None:
        """Полная деталь фазы с инструкциями, checks, evidence, checkups."""
        phase = self._db.get_phase(phase_id)
        if not phase:
            return None

        phase["phase_num"] = phase["phase_order"]
        phase["skills"] = json.loads(phase["skills"]) if phase["skills"] else []

        # Доп поля из БД (defaults)
        for key in (
            "delegate_agent", "delegate_timeout", "delegate_max_cycles",
            "delegate_toolsets", "parallel_with", "rollback_target",
            "next_recommendation",
        ):
            if key not in phase:
                phase[key] = None

        phase["instructions"] = self._db.get_phase_instructions(phase_id)
        phase["checks"] = self._db.get_phase_checks(phase_id)
        phase["evidence"] = self._db.get_phase_evidence(phase_id)
        phase["checkups"] = self._db.get_phase_checkups(phase_id)
        return phase

    # ── Singleton helpers ───────────────────────────────────────────────

    def delete_instruction(self, inst_id: int) -> None:
        self._db.delete_instruction(inst_id)

    def delete_check(self, check_id: int) -> None:
        self._db.delete_check(check_id)

    def delete_evidence(self, ev_id: int) -> None:
        self._db.delete_evidence(ev_id)

    def update_phase(self, phase_id: str, data: dict[str, Any]) -> None:
        """Обновить фазу. skills сериализуется в JSON-строку."""
        clean = {k: (json.dumps(v) if k == "skills" and isinstance(v, list) else v) for k, v in data.items()}
        self._db.update_phase(phase_id, clean)
