"""DB-backed workflow supervisor over the phase catalog."""

from __future__ import annotations

from typing import Any

from ..application.project import ProjectService
from ..application.task import TaskService
from ..application.workflow import WorkflowService
from ..domain.validation import get_project_for_task_key
from ..infrastructure.db import schema
from ..infrastructure.db.uow import SAUnitOfWork
from .context import WizardContextBuilder
from .contracts import PhaseContractBuilder
from .models import Phase
from .prompt import build_phase_prompt


class WizardEngine:
    """Internal supervisor that evaluates workflow progress against DB phase contracts."""

    def __init__(
        self, task_key: str, repo: str | None = None, uow: SAUnitOfWork | None = None, create_if_missing: bool = True
    ):
        self.task_key = task_key
        self.repo = repo
        self.create_if_missing = create_if_missing
        self._uow = uow if uow is not None else SAUnitOfWork()

        self._uow.create_all()
        schema.ensure_phase_catalog(self._uow)

        self._workflow_service = WorkflowService(self._uow)
        self._project_service = ProjectService(self._uow)
        self._task_service = TaskService(self._uow)

        self.task = self._ensure_task() if create_if_missing else self._task_service.get_task_by_key(task_key)
        if self.task is None:
            raise ValueError(f"Task {task_key} not found")
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

    # ── Setup / state helpers ────────────────────────────────────────

    def _ensure_task(self) -> dict:
        existing = self._task_service.get_task_by_key(self.task_key)
        if existing:
            if str(existing.get("current_phase") or "").strip() == "":
                current_phase = self._first_phase_code_for_project(existing["project_id"])
                self._task_service.update_task(existing["id"], {"current_phase": current_phase})
                self._uow.commit()
                return self._task_service.get_task(existing["id"]) or existing
            return existing

        if not self.create_if_missing:
            raise ValueError(f"Task {self.task_key} not found and create_if_missing=False")

        project = self._resolve_project()
        if not project:
            raise ValueError(f"Cannot resolve project for task key: {self.task_key}")
        current_phase = self._first_phase_code_for_project(project["id"])
        task = self._task_service.create_task(
            {
                "project_id": project["id"],
                "task_key": self.task_key,
                "title": self.task_key,
                "current_phase": current_phase,
                "status": "active",
            }
        )
        self._uow.commit()
        return task

    def _resolve_project(self) -> dict[str, Any] | None:
        return get_project_for_task_key(self._uow, self.task_key)

    def _first_phase_code_for_project(self, project_id: int) -> str:
        project = self._project_service.get_project(project_id)
        workflow_id = project["workflow_id"] if project else None
        phases = schema.load_phases_from_db(self._uow, workflow_id=workflow_id)
        if not phases:
            raise ValueError(f"Project {project_id} has no configured workflow phases")
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
        runs = [r.to_dict() for r in self._uow.supervisor_runs.list(task_id=task_id, limit=20)]
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
                    previously.add(item.strip())
        return previously

    def _get_next_phase(self, phase_code):
        cb = PhaseContractBuilder(self.all_phases)
        return cb.get_next_phase(phase_code)

    def _get_parallel_group(self, start_phase):
        cb = PhaseContractBuilder(self.all_phases)
        return cb.get_parallel_group(start_phase)

    def _get_next_phase_after_group(self, group):
        cb = PhaseContractBuilder(self.all_phases)
        return cb._next_after_group(group)

    def _record_transition(
        self, phase: Phase, verdict: str, next_phase: str | None, rollback_target: str | None
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
        )

    def _record_parallel_transition(self, group: list[Phase], verdict: str, next_phase: str | None) -> None:
        from .transitions import record_parallel_transition
        record_parallel_transition(
            db=self.db,
            task=self.task,
            group=group,
            phase_map=self.phase_map,
            verdict=verdict,
            next_phase=next_phase,
        )

    # ── Context / Prompt ─────────────────────────────────────────────────────

    def get_full_context(self) -> dict:
        builder = WizardContextBuilder(
            uow=self._uow,
            task=self.task,
            project=self.project,
            workflow=self.workflow,
            all_phases=self.all_phases,
            current_phase=self.current_phase,
            task_key=self.task_key,
            repo=self.repo,
        )
        return builder.build()

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
        return {
            "verdict": "BLOCKED",
            "task_key": self.task_key,
            "phase": self.current_phase,
            "message": "Current phase is not configured in the workflow catalog.",
            "covered": [],
            "missing": [],
            "blockers": ["phase-not-configured"],
            "current_phase": self.current_phase,
            "next_phase": None,
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
        self, phase: Phase, verdict: str, next_phase: str | None, rollback_target: str | None
    ) -> None:
        is_parallel = phase.execution_type == "parallel"
        if is_parallel:
            group = self._get_parallel_group(phase)
            target = next_phase if verdict == "pass" else rollback_target
            self._record_parallel_transition(group, verdict, target)
        else:
            self._record_transition(phase, verdict, next_phase, rollback_target)
        self._uow.commit()
        if self.task:
            self.task = self._task_service.get_task(self.task["id"]) or self.task
            self.current_phase = self._resolve_current_phase()

    def evaluate(self, report: str) -> dict:
        phase = self._get_current_phase_obj()
        if not phase:
            return self._blocked_result()

        return self.evaluate_llm(report, phase)

    # ── LLM evaluate ─────────────────────────────────────────────────

    def evaluate_llm(self, report: str, phase: Phase) -> dict:
        """Evaluate via the configured Ollama endpoint without a local fallback."""
        from .evaluate import evaluate_llm_report

        return evaluate_llm_report(report, phase, self)
