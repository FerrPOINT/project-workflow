"""PhaseService — CRUD helper for UI phase detail/edit routes.

Re-implemented on top of the SQLAlchemy UnitOfWork; the old sqlite3/raw-SQL
implementation has been removed.
"""
from __future__ import annotations

import json
import logging
from typing import Any, cast

from . import models as m
from .uow import SAUnitOfWork

logger = logging.getLogger(__name__)


class PhaseService:
    """CRUD operations for phases, instructions, checks, evidence."""

    def __init__(self, uow_or_state: SAUnitOfWork | Any):
        """Accept either a UnitOfWork or an _AppState instance."""
        if type(uow_or_state).__name__ == "_AppState":
            self._uow: SAUnitOfWork = cast(SAUnitOfWork, cast(Any, uow_or_state).get_uow())
        else:
            self._uow = uow_or_state

    # ── Bulk save helpers (atomic) ─────────────────────────────────────

    def _resolve_phase_id(self, phase_id: int | str) -> int:
        with self._uow:
            if not (isinstance(phase_id, int) or str(phase_id).lstrip("-").isdigit()):
                phase = self._uow.phases.get_by_code(str(phase_id))
                if not phase or phase.id is None:
                    raise ValueError(f"Phase not found: {phase_id}")
                return phase.id
            candidate = int(phase_id)
            phase = self._uow.phases.get_by_id(candidate)
            if not phase or phase.id is None:
                raise ValueError(f"Phase not found: {phase_id}")
            return phase.id

    def save_instructions(
        self, phase_id: int | str, items: list[dict[str, Any]]
    ) -> list[int]:
        """Replace all instructions for a phase.  Returns new ids in order."""
        resolved = self._resolve_phase_id(phase_id)
        with self._uow:
            self._uow.instructions.delete_for_phase(resolved)
            ids: list[int] = []
            for idx, item in enumerate(items, 1):
                new_id = self._uow.instructions.create(
                    resolved,
                    {
                        "step_num": idx,
                        "description": item["description"],
                        "execution_type": item.get("execution_type", "sync"),
                        "skills": self.serialize_skills(
                            self.normalize_skills(item.get("skills"))
                        ),
                    },
                )
                ids.append(new_id)
            return ids

    def save_checks(self, phase_id: int | str, items: list[dict[str, Any]]) -> list[int]:
        """Replace all checks for a phase."""
        resolved = self._resolve_phase_id(phase_id)
        with self._uow:
            self._delete_checks(resolved)
            ids: list[int] = []
            for item in items:
                chk = m.Check(phase_id=resolved, description=item["description"])
                self._uow._session.add(chk)
                self._uow._session.flush()
                ids.append(int(chk.id))
            return ids

    def save_evidence(self, phase_id: int | str, items: list[dict[str, Any]]) -> list[int]:
        """Replace all evidence for a phase."""
        resolved = self._resolve_phase_id(phase_id)
        with self._uow:
            self._delete_evidence(resolved)
            ids: list[int] = []
            for item in items:
                ev = m.Evidence(phase_id=resolved, description=item["description"])
                self._uow._session.add(ev)
                self._uow._session.flush()
                ids.append(int(ev.id))
            return ids

    def _delete_checks(self, phase_id: int) -> None:
        from sqlalchemy import text

        self._uow._session.execute(
            text("DELETE FROM checks WHERE phase_id = :pid"),
            {"pid": phase_id},
        )

    def _delete_evidence(self, phase_id: int) -> None:
        from sqlalchemy import text

        self._uow._session.execute(
            text("DELETE FROM evidence WHERE phase_id = :pid"),
            {"pid": phase_id},
        )

    # ── Read helpers ─────────────────────────────────────────────────

    def get_phase_detail(self, phase_id: int | str) -> dict[str, Any]:
        """Return a phase with nested content."""
        try:
            resolved = self._resolve_phase_id(phase_id)
        except ValueError:
            return {}
        with self._uow:
            phase = self._uow.phases.get_by_id(resolved)
            if not phase:
                return {}
            phase_dict = phase.to_dict()
            instructions = []
            for item in self._uow.instructions.list(resolved):
                normalized = dict(item)
                normalized["skills"] = self.normalize_skills(item.get("skills"))
                instructions.append(normalized)
            checks = [{"id": r["id"], "phase_id": r["phase_id"], "description": r["description"]} for r in self._uow.phases.get_checks(resolved)]
            evidence = [{"id": r["id"], "phase_id": r["phase_id"], "description": r["description"]} for r in self._uow.phases.get_evidence(resolved)]
            return {
                **phase_dict,
                "instructions": instructions,
                "checks": checks,
                "evidence": evidence,
            }

    def update_phase(self, phase_id: int | str, data: dict[str, Any]) -> None:
        resolved = self._resolve_phase_id(phase_id)
        with self._uow:
            self._uow.phases.update(resolved, data)

    def get_all_phases(self) -> list[dict[str, Any]]:
        """All phases with content (for API)."""
        with self._uow:
            rows = self._uow.phases.list()
            return [self.get_phase_detail(r.id) for r in rows if r.id is not None]

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
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Failed to parse skills JSON: %s", exc)
            return []
        return parsed if isinstance(parsed, list) else []

    @staticmethod
    def serialize_skills(skills: list[str] | None) -> str | None:
        normalized = PhaseService.normalize_skills(skills)
        if not normalized:
            return None
        return json.dumps(normalized, ensure_ascii=False)
