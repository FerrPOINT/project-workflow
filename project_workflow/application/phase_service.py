"""Phase CRUD helper for UI detail and edit routes."""

from __future__ import annotations

from typing import Any

from project_workflow.domain.exceptions import NotFoundError
from project_workflow.domain.repositories import UnitOfWork


class PhaseService:
    """CRUD operations for phases, instructions, checks, evidence."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    # ── Bulk save helpers (atomic) ─────────────────────────────────────

    def _resolve_phase_id(self, phase_id: int) -> int:
        if not isinstance(phase_id, int) or isinstance(phase_id, bool):
            raise ValueError(f"Идентификатор фазы должен быть числом: {phase_id}")
        phase = self._uow.phases.get_by_id(phase_id)
        if not phase or phase.id is None:
            raise ValueError(f"Фаза не найдена: {phase_id}")
        return phase.id

    def _lock_phase(self, phase_id: int) -> int:
        """Lock the owning workflow and return a freshly read phase id."""
        if not isinstance(phase_id, int) or isinstance(phase_id, bool):
            raise ValueError(f"Идентификатор фазы должен быть числом: {phase_id}")
        initial = self._uow.phases.get_by_id(phase_id)
        if initial is None or initial.workflow_id is None:
            raise NotFoundError(f"Фаза {phase_id} не найдена")
        workflow = self._uow.workflows.lock(initial.workflow_id)
        if workflow is None:
            raise NotFoundError(f"Воркфлоу {initial.workflow_id} не найден")
        fresh = next(
            (phase for phase in self._uow.phases.list(initial.workflow_id) if phase.id == phase_id),
            None,
        )
        if fresh is None or fresh.id is None:
            raise NotFoundError(f"Фаза {phase_id} не найдена")
        return fresh.id

    def _replace_instructions(self, phase_id: int, items: list[dict[str, Any]]) -> list[int]:
        self._uow.instructions.delete_for_phase(phase_id)
        ids: list[int] = []
        for idx, item in enumerate(items, 1):
            ids.append(
                self._uow.instructions.create(
                    phase_id,
                    {
                        "step_num": idx,
                        "description": item["description"],
                        "execution_type": item.get("execution_type", "sync"),
                        "skills": self.normalize_skills(item.get("skills")),
                    },
                )
            )
        return ids

    def _replace_checks(self, phase_id: int, items: list[dict[str, Any]]) -> list[int]:
        self._uow.phases.set_checks(phase_id, items)
        return [int(row["id"]) for row in self._uow.phases.get_checks(phase_id)]

    def _replace_evidence(self, phase_id: int, items: list[dict[str, Any]]) -> list[int]:
        self._uow.phases.set_evidence(phase_id, items)
        return [int(row["id"]) for row in self._uow.phases.get_evidence(phase_id)]

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

    def update_phase_detail(self, phase_id: int, data: dict[str, Any]) -> dict[str, list[int]]:
        """Update the complete phase aggregate in one locked transaction."""
        from project_workflow.application.phase import PhaseServiceApp

        nested_fields = {"instructions", "checks", "evidence"}
        scalar = {key: value for key, value in data.items() if key not in nested_fields}
        try:
            if scalar:
                PhaseServiceApp(self._uow).update_phase(phase_id, scalar, commit=False)
                resolved = phase_id
            else:
                resolved = self._lock_phase(phase_id)
            result: dict[str, list[int]] = {"instructions": [], "checks": [], "evidence": []}
            if "instructions" in data:
                result["instructions"] = self._replace_instructions(resolved, data["instructions"])
            if "checks" in data:
                result["checks"] = self._replace_checks(resolved, data["checks"])
            if "evidence" in data:
                result["evidence"] = self._replace_evidence(resolved, data["evidence"])
            self._uow.commit()
            return result
        except Exception:
            self._uow.rollback()
            raise

    @staticmethod
    def normalize_skills(raw: Any) -> list[str]:
        if raw in (None, []):
            return []
        if isinstance(raw, list):
            if not all(isinstance(item, str) for item in raw):
                raise TypeError("skills должен содержать только строки")
            return [item.strip() for item in raw if item.strip()]
        raise TypeError("skills должен быть массивом строк или null")
