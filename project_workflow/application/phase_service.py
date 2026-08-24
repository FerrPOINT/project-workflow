"""Phase CRUD helper for UI detail and edit routes."""

from __future__ import annotations

from typing import Any

from project_workflow.domain.repositories import UnitOfWork


class PhaseService:
    """CRUD operations for phases, instructions, checks, evidence."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    # ── Bulk save helpers (atomic) ─────────────────────────────────────

    def _resolve_phase_id(self, phase_id: int) -> int:
        if not isinstance(phase_id, int) or isinstance(phase_id, bool):
            raise ValueError(f"Phase id must be numeric: {phase_id}")
        phase = self._uow.phases.get_by_id(phase_id)
        if not phase or phase.id is None:
            raise ValueError(f"Phase not found: {phase_id}")
        return phase.id

    def save_instructions(
        self, phase_id: int, items: list[dict[str, Any]], *, commit: bool = True
    ) -> list[int]:
        """Replace all instructions for a phase.  Returns new ids in order."""
        resolved = self._resolve_phase_id(phase_id)
        self._uow.instructions.delete_for_phase(resolved)
        ids: list[int] = []
        for idx, item in enumerate(items, 1):
            new_id = self._uow.instructions.create(
                resolved,
                {
                    "step_num": idx,
                    "description": item["description"],
                    "execution_type": item.get("execution_type", "sync"),
                    "skills": self.normalize_skills(item.get("skills")),
                },
            )
            ids.append(new_id)
        if commit:
            self._uow.commit()
        return ids

    def save_checks(self, phase_id: int, items: list[dict[str, Any]], *, commit: bool = True) -> list[int]:
        """Replace all checks for a phase."""
        resolved = self._resolve_phase_id(phase_id)
        ids: list[int] = []
        self._uow.phases.set_checks(resolved, items)
        # Reload to return ids in order.
        for row in self._uow.phases.get_checks(resolved):
            ids.append(int(row["id"]))
        if commit:
            self._uow.commit()
        return ids

    def save_evidence(self, phase_id: int, items: list[dict[str, Any]], *, commit: bool = True) -> list[int]:
        """Replace all evidence for a phase."""
        resolved = self._resolve_phase_id(phase_id)
        ids: list[int] = []
        self._uow.phases.set_evidence(resolved, items)
        for row in self._uow.phases.get_evidence(resolved):
            ids.append(int(row["id"]))
        if commit:
            self._uow.commit()
        return ids

    # ── Read helpers ─────────────────────────────────────────────────

    def get_phase_detail(self, phase_id: int) -> dict[str, Any]:
        """Return a phase with nested content."""
        try:
            resolved = self._resolve_phase_id(phase_id)
        except ValueError:
            return {}
        phase = self._uow.phases.get_by_id(resolved)
        if not phase:
            return {}
        phase_dict = phase.to_dict()
        instructions = []
        for item in self._uow.instructions.list(resolved):
            normalized = dict(item)
            normalized["skills"] = self.normalize_skills(item.get("skills"))
            instructions.append(normalized)
        checks = [
            {"id": r["id"], "phase_id": r["phase_id"], "description": r["description"]}
            for r in self._uow.phases.get_checks(resolved)
        ]
        evidence = [
            {"id": r["id"], "phase_id": r["phase_id"], "description": r["description"]}
            for r in self._uow.phases.get_evidence(resolved)
        ]
        return {
            **phase_dict,
            "instructions": instructions,
            "checks": checks,
            "evidence": evidence,
        }

    def update_phase(self, phase_id: int, data: dict[str, Any], *, commit: bool = True) -> None:
        from project_workflow.application.phase import PhaseServiceApp

        resolved = self._resolve_phase_id(phase_id)
        PhaseServiceApp(self._uow).update_phase(resolved, data, commit=commit)

    @staticmethod
    def normalize_skills(raw: Any) -> list[str]:
        if raw in (None, []):
            return []
        if isinstance(raw, list):
            if not all(isinstance(item, str) for item in raw):
                raise TypeError("skills must contain strings only")
            return [item.strip() for item in raw if item.strip()]
        raise TypeError("skills must be a list of strings or null")
