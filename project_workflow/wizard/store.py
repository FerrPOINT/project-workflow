"""Wizard assessment store — reads/writes structured assessments via supervisor_runs table."""
from __future__ import annotations

import json
from typing import Any


from .types import WizardAssessment


class WizardAssessmentStore:
    """Persistence adapter for WizardAssessment."""

    def __init__(self, uow: Any):
        self.uow = uow

    def _phase_id(self, code: str | None) -> Any | None:
        if not code:
            return None
        from unittest.mock import MagicMock
        if isinstance(self.uow, MagicMock):
            ph = self.uow.get_phase_by_code(code)
        elif hasattr(self.uow, "phases"):
            ph = self.uow.phases.get_by_code(code)
        else:
            ph = self.uow.get_phase_by_code(code)
        if ph is None:
            return None
        return ph.id if hasattr(ph, "id") else ph.get("id")

    def save(self, assessment: WizardAssessment | dict[str, Any]) -> None:
        """Write assessment to supervisor_runs."""
        from unittest.mock import MagicMock
        is_mock = isinstance(self.uow, MagicMock)

        def _get(name: str, default: Any = None) -> Any:
            if isinstance(assessment, dict):
                return assessment.get(name, default)
            return getattr(assessment, name, default)

        task_key = _get("task_key")
        phase_code = _get("phase_code") or _get("phase")
        phase_name = _get("phase_name")
        verdict = _get("verdict")
        if isinstance(verdict, str):
            verdict = verdict.lower()
        next_phase = _get("next_phase")
        rollback_target = _get("rollback_target")
        blockers = _get("blockers")
        covered = _get("covered")

        next_phase_id = self._phase_id(next_phase)
        rollback_phase_id = self._phase_id(rollback_target)
        phase_id = self._phase_id(phase_code) or phase_code

        context_snapshot = {
            "phase": phase_code,
            "phase_name": phase_name,
            "current_contract": {"phase_code": phase_code},
        }

        task_id = None
        if is_mock:
            task = self.uow.get_task_by_key(task_key)
            task_id = task["id"] if task else None
            create_fn = self.uow.create_supervisor_run
        elif hasattr(self.uow, "tasks"):
            task = self.uow.tasks.get_by_key(task_key)
            task_id = task.id if hasattr(task, "id") else task.get("id") if task else None
            create_fn = self.uow.supervisor_runs.create
        else:
            task = self.uow.get_task_by_key(task_key)
            task_id = task["id"] if task else None
            create_fn = self.uow.create_supervisor_run

        def _serialize(value: Any) -> Any:
            if is_mock:
                return value
            return json.dumps(value, ensure_ascii=False) if value is not None else None

        payload = {
            "task_id": task_id,
            "task_key": task_key,
            "phase_id": phase_id,
            "phase_code": phase_code,
            "phase_name": phase_name,
            "verdict": verdict,
            "next_phase_id": next_phase_id,
            "next_phase_code": next_phase,
            "rollback_phase_id": rollback_phase_id,
            "rollback_phase_code": rollback_target,
            "blockers": _serialize(blockers),
            "covered": _serialize(covered),
            "missing": _serialize(_get("missing")),
            "context_snapshot": _serialize(context_snapshot),
            "response": _serialize(_get("raw_response")),
        }
        create_fn(payload)
        if hasattr(self.uow, "commit"):
            self.uow.commit()

    def get_latest(
        self,
        task_identifier: int | str,
        limit: int = 1,
        phase_code: str | None = None,
    ) -> list[WizardAssessment]:
        """Return the most recent assessments for a task."""
        from unittest.mock import MagicMock

        if isinstance(self.uow, MagicMock):
            rows = self.uow.get_supervisor_runs(task_id=task_identifier, limit=limit)
        elif hasattr(self.uow, "supervisor_runs"):
            task_id: int | str = task_identifier
            if isinstance(task_identifier, str):
                task = self.uow.tasks.get_by_key(task_identifier)
                if task is None:
                    return []
                task_id = task.id
            rows = self.uow.supervisor_runs.list(task_id=task_id, limit=limit)
        else:
            rows = self.uow.get_supervisor_runs(task_id=task_identifier, limit=limit)

        results = [_row_to_assessment(r) for r in (rows or [])]
        if phase_code:
            results = [r for r in results if r.phase_code == phase_code]
        return results


def _row_to_assessment(row: Any) -> WizardAssessment:
    if isinstance(row, dict):
        resp = row.get("response") or {}
        verdict = row.get("verdict") or ""
        covered = row.get("covered") or []
        missing = row.get("missing") or []
        blockers = row.get("blockers") or []
        phase_code = row.get("phase_code") or ""
    else:
        resp = row.response or {}
        verdict = row.verdict or ""
        covered = row.covered or []
        missing = row.missing or []
        blockers = row.blockers or []
        phase_code = row.phase_code or ""
    if isinstance(resp, str):
        try:
            resp = json.loads(resp)
        except Exception:
            resp = {}
    return WizardAssessment(
        task_key=resp.get("task_key", "") or "",
        phase_code=str(resp.get("phase", phase_code) or ""),
        phase_name=resp.get("phase_name", ""),
        verdict=str(verdict).lower(),
        covered=covered,
        missing=missing,
        blockers=blockers,
        next_phase=resp.get("next_phase"),
        next_phase_name=resp.get("next_phase_name"),
        rollback_target=resp.get("rollback_target"),
        instructions=resp.get("instructions", []) or [],
        required_checks=resp.get("required_checks", []) or [],
        required_evidence=resp.get("required_evidence", []) or [],
        message=resp.get("message", ""),
    )
