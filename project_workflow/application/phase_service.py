"""Phase CRUD helper for UI detail and edit routes."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from project_workflow.domain.exceptions import ConflictError, NotFoundError
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

    @staticmethod
    def _validate_nested_ids(
        phase_id: int,
        items: list[dict[str, Any]],
        existing: list[dict[str, Any]],
        label: str,
    ) -> dict[int, dict[str, Any]]:
        if any("id" not in item for item in items):
            raise ValueError(f"Поле id обязательно для каждого элемента: {label}")
        invalid_ids = [
            item["id"]
            for item in items
            if item["id"] is not None
            and (
                not isinstance(item["id"], int)
                or isinstance(item["id"], bool)
                or item["id"] <= 0
            )
        ]
        if invalid_ids:
            raise ValueError(f"Идентификаторы {label} должны быть положительными числами или null")
        existing_by_id = {int(row["id"]): row for row in existing}
        submitted_ids = [item["id"] for item in items if item["id"] is not None]
        if len(submitted_ids) != len(set(submitted_ids)):
            raise ValueError(f"Идентификаторы {label} должны быть уникальными")
        unknown = sorted(set(submitted_ids) - set(existing_by_id))
        if unknown:
            joined = ", ".join(str(item_id) for item_id in unknown)
            raise ConflictError(f"{label.capitalize()} {joined} не принадлежат фазе {phase_id}")
        return existing_by_id

    def _save_instructions(self, phase_id: int, items: list[dict[str, Any]]) -> list[int]:
        existing = list(self._uow.phase_instructions.list(phase_id))
        existing_by_id = self._validate_nested_ids(phase_id, items, existing, "инструкции")
        final_ids: list[int] = []
        for item in items:
            data = {
                "description": item["description"],
                "execution_type": item.get("execution_type", "sync"),
                "skills": self.normalize_skills(item.get("skills")),
            }
            item_id = item["id"]
            if item_id is None:
                item_id = self._uow.phase_instructions.create(phase_id, data)
            else:
                self._uow.phase_instructions.update(item_id, data)
            final_ids.append(item_id)
        for item_id in set(existing_by_id) - set(final_ids):
            self._uow.phase_instructions.delete(item_id)
        if final_ids:
            self._uow.phase_instructions.reorder(
                phase_id,
                [(item_id, position) for position, item_id in enumerate(final_ids, 1)],
            )
        return final_ids

    def _save_checks(self, phase_id: int, items: list[dict[str, Any]]) -> list[int]:
        existing = list(self._uow.phase_checks.list(phase_id))
        existing_by_id = self._validate_nested_ids(phase_id, items, existing, "проверки")
        self._validate_unique_descriptions(items, "проверки")
        submitted_existing_ids = {item["id"] for item in items if item["id"] is not None}
        for item_id in set(existing_by_id) - submitted_existing_ids:
            self._uow.phase_checks.delete(item_id)
        update_token = uuid4().hex
        for item_id in submitted_existing_ids:
            self._uow.phase_checks.update(
                item_id,
                {"description": f"__phase_check_update_{update_token}_{item_id}__"},
            )
        final_ids: list[int] = []
        for item in items:
            item_id = item["id"]
            if item_id is None:
                item_id = self._uow.phase_checks.create(phase_id, item)
            else:
                self._uow.phase_checks.update(item_id, item)
            final_ids.append(item_id)
        return final_ids

    def _save_evidence(self, phase_id: int, items: list[dict[str, Any]]) -> list[int]:
        existing = list(self._uow.phase_evidence_requirements.list(phase_id))
        existing_by_id = self._validate_nested_ids(phase_id, items, existing, "требования подтверждений")
        self._validate_unique_descriptions(items, "требования подтверждений")
        submitted_existing_ids = {item["id"] for item in items if item["id"] is not None}
        for item_id in set(existing_by_id) - submitted_existing_ids:
            self._uow.phase_evidence_requirements.delete(item_id)
        update_token = uuid4().hex
        for item_id in submitted_existing_ids:
            self._uow.phase_evidence_requirements.update(
                item_id,
                {"description": f"__phase_evidence_update_{update_token}_{item_id}__"},
            )
        final_ids: list[int] = []
        for item in items:
            item_id = item["id"]
            if item_id is None:
                item_id = self._uow.phase_evidence_requirements.create(phase_id, item)
            else:
                self._uow.phase_evidence_requirements.update(item_id, item)
            final_ids.append(item_id)
        return final_ids

    @staticmethod
    def _validate_unique_descriptions(items: list[dict[str, Any]], label: str) -> None:
        descriptions = [str(item["description"]).strip().casefold() for item in items]
        if len(descriptions) != len(set(descriptions)):
            raise ValueError(f"Описания {label} должны быть уникальными")

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
        for item in self._uow.phase_instructions.list(resolved):
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
                result["instructions"] = self._save_instructions(resolved, data["instructions"])
            if "checks" in data:
                result["checks"] = self._save_checks(resolved, data["checks"])
            if "evidence" in data:
                result["evidence"] = self._save_evidence(resolved, data["evidence"])
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
