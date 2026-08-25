"""DB-backed workflow supervisor over the phase catalog.

Thin facade — orchestrates context → contract → checks → store.
Public surface:
- SupervisorEngine(task_key)
- SupervisorEngine.get_full_context()
- SupervisorEngine.get_phase_prompt()
- SupervisorEngine.evaluate(report)
"""

from __future__ import annotations

import threading
from typing import Any

from ..application.project import ProjectService
from ..application.task import TaskService
from ..application.workflow import WorkflowService
from ..domain.exceptions import ConflictError
from ..infrastructure.db import schema
from ..infrastructure.db.uow import SAUnitOfWork
from .context import SupervisorContextBuilder
from .contracts import PhaseContractBuilder
from .models import Phase
from .prompt import build_phase_prompt


class PromptCache:
    """Thread-safe prompt context cache with generation-based invalidation."""

    def __init__(self) -> None:
        self._cache: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._gen = 0

    def key(self, task_key: str, current_phase: str, gen: int) -> str:
        return f"{task_key}:{current_phase}:{gen}"

    def get(self, task_key: str, current_phase: str) -> dict | None:
        with self._lock:
            return self._cache.get(self.key(task_key, current_phase, self._gen))

    def set(self, task_key: str, current_phase: str, value: dict) -> None:
        with self._lock:
            self._cache[self.key(task_key, current_phase, self._gen)] = value

    def invalidate(self) -> None:
        with self._lock:
            self._gen += 1
            if self._gen > 1000:
                self._cache.clear()
                self._gen = 0


class SupervisorEngine:
    """Internal supervisor that evaluates workflow progress against DB phase contracts."""

    def __init__(
        self, task_key: str, uow: SAUnitOfWork | None = None, create_if_missing: bool = True
    ):
        self.task_key = task_key
        self.create_if_missing = create_if_missing
        self._uow = uow if uow is not None else SAUnitOfWork()

        self._workflow_service = WorkflowService(self._uow)
        self._project_service = ProjectService(self._uow)
        self._task_service = TaskService(self._uow)

        self.task = self._ensure_task() if create_if_missing else self._task_service.get_task_by_key(task_key)
        if self.task is None:
            raise ValueError(f"Задача {task_key} не найдена")
        self._uow.commit()
        self.project = (
            self._project_service.get_project(self.task["project_id"])
            if self.task and self.task.get("project_id")
            else None
        )
        self.workflow_id = self.project["workflow_id"] if self.project else None
        self.workflow = self._workflow_service.get_workflow(self.workflow_id) if self.workflow_id else None
        self._all_phases: list[Phase] | None = None
        self._phase_map: dict[str, Phase] | None = None
        self.current_phase = self._resolve_current_phase()
        self._cache = PromptCache()

    @property
    def db(self):
        """UoW accessor used by tests and internal callers."""
        return self._uow

    @db.setter
    def db(self, value) -> None:
        """Allow tests to inject a mock UoW."""
        self._uow = value
        if hasattr(self, "_task_service"):
            self._task_service = TaskService(self._uow)

    @property
    def all_phases(self) -> list[Phase]:
        if self._all_phases is None:
            self._all_phases = schema.load_phases_from_db(self._uow, workflow_id=self.workflow_id)
        return self._all_phases

    @all_phases.setter
    def all_phases(self, value: list[Phase]) -> None:
        self._all_phases = value
        self._phase_map = None

    @property
    def phase_map(self) -> dict[str, Phase]:
        if self._phase_map is None:
            self._phase_map = {phase.code: phase for phase in self.all_phases}
        return self._phase_map

    @phase_map.setter
    def phase_map(self, value: dict[str, Phase]) -> None:
        self._phase_map = value

    @property
    def workflow_revision(self) -> str:
        return str(self.workflow.get("name") or "") if self.workflow else ""

    @property
    def contract_builder(self) -> PhaseContractBuilder:
        return PhaseContractBuilder(self.all_phases, self.workflow_revision)

    # ── Setup / state helpers ────────────────────────────────────────

    def _ensure_task(self) -> dict:
        existing = self._task_service.get_task_by_key(self.task_key)
        if existing:
            return existing

        if not self.create_if_missing:
            raise ValueError(f"Задача {self.task_key} не найдена, а create_if_missing=False")

        project = self._resolve_project()
        if not project:
            raise ValueError(f"Не удалось определить проект для ключа задачи: {self.task_key}")
        current_phase = self._first_phase_code_for_project(project["id"])
        try:
            return self._task_service.create_task(
                {
                    "project_id": project["id"],
                    "task_key": self.task_key,
                    "title": self.task_key,
                    "current_phase": current_phase,
                    "status": "active",
                }
            )
        except ConflictError:
            existing = self._task_service.get_task_by_key(self.task_key)
            if existing is not None and existing.get("project_id") == project["id"]:
                return existing
            raise

    def _resolve_project(self) -> dict[str, Any] | None:
        # Try matching via project key prefixes first.
        for project in self._project_service.list_projects():
            for prefix in project.get("key_prefixes", []):
                if self.task_key.startswith(prefix + "-") or self.task_key == prefix:
                    return project
        return None

    def _first_phase_code_for_project(self, project_id: int) -> str:
        project = self._project_service.get_project(project_id)
        workflow_id = project["workflow_id"] if project else None
        phases = schema.load_phases_from_db(self._uow, workflow_id=workflow_id)
        if not phases:
            raise ValueError("Каталог фаз воркфлоу пуст")
        return phases[0].code

    def _resolve_current_phase(self) -> str:
        if not self.task:
            return ""
        current = str(self.task.get("current_phase") or "").strip()
        return current

    def _get_current_phase_obj(self) -> Phase | None:
        return self.phase_map.get(self.current_phase)

    def _get_previously_covered(self, phase_code: str) -> set[str]:
        """Return items already covered in previous supervisor runs for this phase."""
        previously: set[str] = set()
        if not self.task:
            return previously
        task_id = int(self.task.get("id", 0))
        if not task_id:
            return previously
        runs = [r.to_dict() for r in self._uow.supervisor_runs.list(task_id=task_id, limit=200)]
        for run in runs:
            run_phase_id = run.get("phase_id")
            if run_phase_id is None:
                continue
            phase = self._uow.phases.get_by_id(int(run_phase_id))
            if phase is None or str(phase.code) != str(phase_code):
                continue
            covered = run.get("covered", [])
            for item in covered:
                if isinstance(item, str):
                    from .checks import normalize_text

                    previously.add(normalize_text(item))
            snapshot = run.get("context_snapshot", {})
            if isinstance(snapshot, dict):
                for item_id in snapshot.get("covered_item_ids", []):
                    if isinstance(item_id, str):
                        previously.add(item_id)
        return previously

    def _get_next_phase(self, phase_code):
        return self.contract_builder.get_next_phase(phase_code)

    def _get_parallel_group(self, start_phase):
        return self.contract_builder.get_parallel_group(start_phase)

    def _get_next_phase_after_group(self, group):
        return self.contract_builder._next_after_group(group)

    def _build_checklist(self, phase):
        return self.contract_builder.build_checklist(phase)

    def _build_parallel_checklist(self, group):
        return self.contract_builder.build_parallel_checklist(group)

    def _record_transition(
        self,
        phase: Phase,
        verdict: str,
        next_phase: str | None,
        rollback_target: str | None,
        *,
        commit: bool = True,
    ) -> None:
        from .transitions import record_transition
        record_transition(
            db=self.db,
            task=self.task,
            phase=phase,
            verdict=verdict,
            next_phase=next_phase,
            rollback_target=rollback_target,
            phase_map=self.phase_map,
            commit=commit,
        )

    def _record_parallel_transition(
        self,
        group: list[Phase],
        verdict: str,
        next_phase: str | None,
        rollback_target: str | None = None,
        *,
        commit: bool = True,
    ) -> None:
        from .transitions import record_parallel_transition
        record_parallel_transition(
            db=self.db,
            task=self.task,
            group=group,
            phase_map=self.phase_map,
            verdict=verdict,
            next_phase=next_phase,
            rollback_target=rollback_target,
            commit=commit,
        )

    # ── Context / Prompt ─────────────────────────────────────────────────────

    def get_full_context(self, use_cache: bool = True) -> dict:
        if use_cache:
            cached = self._cache.get(self.task_key, self.current_phase)
            if cached:
                return cached
        builder = SupervisorContextBuilder(
            uow=self._uow,
            task=self.task,
            project=self.project,
            workflow=self.workflow,
            all_phases=self.all_phases,
            current_phase=self.current_phase,
            task_key=self.task_key,
        )
        ctx = builder.build()
        self._cache.set(self.task_key, self.current_phase, ctx)
        return ctx

    def get_phase_prompt(self, phase_id: str | None = None) -> str:
        ctx = self.get_full_context()
        return build_phase_prompt(
            task_key=self.task_key,
            phase_map=self.phase_map,
            all_phases=self.all_phases,
            current_phase=self.current_phase,
            ctx=ctx,
            phase_id=phase_id,
        )

    def get_phase_contract(self, phase_id: str | None = None) -> dict[str, Any] | None:
        """Return the structured executor contract for a phase or parallel group."""
        phase = self.phase_map.get(phase_id or self.current_phase)
        if phase is None:
            return None
        builder = self.contract_builder
        contract = (
            builder.build_parallel(builder.get_parallel_group(phase))
            if phase.execution_type == "parallel"
            else builder.build(phase)
        )
        result = contract.to_dict()
        recent = self.get_full_context().get("recent_verdicts") or []
        if recent:
            latest = recent[0]
            verdict = str(latest.get("verdict") or "").upper()
            destination = (
                latest.get("rollback_target")
                if verdict == "ROLLBACK"
                else latest.get("phase_code")
            )
            if verdict in {"PARTIAL", "BLOCKED", "ROLLBACK"} and destination == phase.code:
                result["evaluation_feedback"] = latest
        return result

    def format_current_phase_instructions(self) -> str:
        """Human-only instructions for `step --task X` without a report."""
        from .prompt import format_current_phase_instructions as _fmt

        return _fmt(
            task_key=self.task_key,
            phase_map=self.phase_map,
            all_phases=self.all_phases,
            current_phase=self.current_phase,
            ctx=self.get_full_context(),
        )

    def _blocked_result(self) -> dict[str, Any]:
        message = (
            "Каталог фаз воркфлоу пуст."
            if not self.all_phases
            else "Текущая фаза отсутствует в каталоге воркфлоу."
        )
        return {
            "verdict": "BLOCKED",
            "task_key": self.task_key,
            "phase": self.current_phase,
            "message": message,
            "covered": [],
            "missing": [],
            "blockers": ["phase-not-configured"],
            "current_phase": self.current_phase,
            "next_phase": None,
            "replayed": False,
            "retryable": True,
        }

    def _completed_result(self, phase: Phase | None) -> dict[str, Any]:
        contract = self.contract_builder.build(phase) if phase else None
        phase_code = phase.code if phase else self.current_phase
        return {
            "verdict": "PASS",
            "task_key": self.task_key,
            "phase": phase_code,
            "phase_name": phase.name if phase else None,
            "status": "done",
            "covered": [],
            "missing": [],
            "blockers": [],
            "current_phase": phase_code,
            "next_phase": None,
            "next_phase_name": None,
            "rollback_target": None,
            "message": "Воркфлоу уже завершён; новый отчёт не оценивался.",
            "confidence": 1.0,
            "instructions": contract.instructions if contract else [],
            "required_checks": contract.required_checks if contract else [],
            "required_evidence": contract.required_evidence if contract else [],
            "skills": contract.skills if contract else [],
            "group_phases": contract.group_phases if contract else None,
            "group_details": contract.group_details if contract else [],
            "replayed": False,
            "retryable": False,
        }

    def _resolve_transition(
        self, phase: Phase, verdict: str, group: list[Phase]
    ) -> tuple[str | None, str | None, str | None]:
        """Return (next_phase_code, next_phase_name, rollback_target_code)."""
        is_parallel = len(group) > 1
        if is_parallel:
            next_phase, next_phase_name = self._get_next_phase_after_group(group)
            rollback_target = group[0].rollback_target if verdict == "rollback" else None
            if verdict != "pass":
                next_phase = None
                next_phase_name = None
        else:
            next_phase, next_phase_name = self._get_next_phase(phase.code)
            rollback_target = phase.rollback_target if verdict == "rollback" else None

        if verdict == "pass" and next_phase:
            next_phase_obj = self.phase_map.get(next_phase)
            next_phase_name = next_phase_obj.name if next_phase_obj else next_phase_name
        return next_phase, next_phase_name, rollback_target

    def _record_evaluation(
        self,
        phase: Phase,
        verdict: str,
        next_phase: str | None,
        rollback_target: str | None,
        *,
        commit: bool = True,
    ) -> None:
        is_parallel = phase.execution_type == "parallel"
        if is_parallel:
            group = self._get_parallel_group(phase)
            self._record_parallel_transition(group, verdict, next_phase, rollback_target, commit=False)
        else:
            self._record_transition(phase, verdict, next_phase, rollback_target, commit=False)
        if commit:
            self._uow.commit()
            self._refresh_task_state()

    def _refresh_task_state(self) -> None:
        self._reload_task_state()
        self._cache.invalidate()

    def _reload_task_state(self) -> None:
        """Reload task state without changing the committed context cache."""
        if not self.task:
            return
        self._uow.refresh()
        self.task = self._task_service.get_task(self.task["id"]) or self.task
        self.current_phase = self._resolve_current_phase()

    def _reload_evaluation_state(self) -> None:
        """Reload task and catalog while the caller holds the workflow lock."""
        self._uow.refresh()
        if self.task:
            self.task = self._task_service.get_task(self.task["id"])
        self.project = (
            self._project_service.get_project(self.task["project_id"])
            if self.task and self.task.get("project_id")
            else None
        )
        self.workflow_id = self.project["workflow_id"] if self.project else None
        self.workflow = self._workflow_service.get_workflow(self.workflow_id) if self.workflow_id else None
        self._all_phases = (
            schema.load_phases_from_db(self._uow, workflow_id=self.workflow_id)
            if self.workflow_id
            else []
        )
        self._phase_map = None
        self.current_phase = self._resolve_current_phase()

    def evaluate(self, report: str) -> dict:
        if self.task and self.task.get("status") == "done":
            return self._completed_result(self._get_current_phase_obj())

        phase = self._get_current_phase_obj()
        if not phase:
            return self._blocked_result()

        return self.evaluate_llm(report, phase)

    # ── LLM evaluate ─────────────────────────────────────────────────

    def evaluate_llm(self, report: str, phase: Phase) -> dict:
        """Evaluate through the configured LLM without a local fallback."""
        from .evaluate import evaluate_llm_report

        return evaluate_llm_report(report, phase, self)
