"""DB-backed workflow supervisor over the phase catalog.

Thin facade — orchestrates context → contract → checks → store.
Public surface kept compatible:
- WizardEngine(task_key, repo)
- WizardEngine.get_full_context()
- WizardEngine.get_phase_prompt()
- WizardEngine.evaluate(report)
- evaluate_report(...), get_phase_instructions(...), main(...)
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

from ..infrastructure.db import schema
from ..infrastructure.db.uow import SAUnitOfWork
from ..application.workflow import WorkflowService
from ..application.phase import PhaseServiceApp
from ..application.project import ProjectService
from ..application.task import TaskService
from ..application.agent import AgentService
from .models import Phase  # noqa: F401
from ..infrastructure import conversation as convo  # noqa: F401 — used by tests via monkeypatch

# Backward-compatible re-exports for existing tests
from .checks import normalize_text, extract_keywords, BLOCKER_PATTERNS as _BLOCKER_PATTERNS, DELEGATE_PATTERNS as _DELEGATE_PATTERNS  # noqa: F401

from .types import WizardAssessment
from .context import WizardContextBuilder
from .contracts import PhaseContractBuilder, text_from_instruction, text_from_check, text_from_evidence
from .checks import check_coverage, extract_blockers, determine_verdict, build_verdict_message
from .store import WizardAssessmentStore
from .prompt import build_phase_prompt

logger = logging.getLogger(__name__)

VERDICT_LABELS = {
    "pass": "PASS",
    "partial": "PARTIAL",
    "blocked": "BLOCKED",
    "rollback": "ROLLBACK",
    "delegate": "DELEGATE",
}


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


class WizardEngine:
    """Internal supervisor that evaluates workflow progress against DB phase contracts."""

    def __init__(self, task_key: str, repo: Optional[str] = None, uow: SAUnitOfWork | None = None, create_if_missing: bool = True):
        self.task_key = task_key
        self.repo = repo
        self.create_if_missing = create_if_missing
        self._uow = uow if uow is not None else SAUnitOfWork()
        self._store = WizardAssessmentStore(self._uow)

        self._uow.create_all()
        self._bootstrap_smoke_project_and_workflow()
        schema.ensure_phase_catalog(self._uow)
        self._ensure_smoke_phases()

        self._workflow_service = WorkflowService(self._uow)
        self._phase_service = PhaseServiceApp(self._uow)
        self._project_service = ProjectService(self._uow)
        self._task_service = TaskService(self._uow)
        self._agent_service = AgentService(self._uow)

        self.task = self._ensure_task() if create_if_missing else self._task_service.get_task_by_key(task_key)
        if self.task is None:
            raise ValueError(f"Task {task_key} not found")
        self._uow.commit()
        self.project = self._project_service.get_project(self.task["project_id"]) if self.task and self.task.get("project_id") else None
        self.workflow_id = self.project["workflow_id"] if self.project else None
        self.workflow = self._workflow_service.get_workflow(self.workflow_id) if self.workflow_id else None
        self._all_phases: list[Phase] | None = None
        self._phase_map: dict[str, Phase] | None = None
        self.current_phase = self._resolve_current_phase()
        self._cache = PromptCache()

    @property
    def db(self):
        """Backward-compat accessor for legacy tests."""
        return self._uow

    @db.setter
    def db(self, value) -> None:
        """Allow legacy tests to inject a mock DB."""
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
        # Try matching via project key prefixes first.
        for project in self._project_service.list_projects():
            for prefix in project.get("key_prefixes", []):
                if self.task_key.startswith(prefix + "-") or self.task_key == prefix:
                    return project
        # Fall back to the default workflow/project.
        default_wf = self._workflow_service.ensure_default_exists()
        default_wf_id = default_wf.get("id") if default_wf else None
        for project in self._project_service.list_projects():
            if default_wf_id and project.get("workflow_id") == default_wf_id:
                return project
        # Create a default project under the default workflow.
        return self._project_service.create_project({
            "code": "default",
            "name": "Default Project",
        })

    def _bootstrap_smoke_project_and_workflow(self) -> None:
        from project_workflow import config
        smoke_wf = self._uow.workflows.get_by_name(config.SMOKE_WORKFLOW_NAME)
        if smoke_wf:
            smoke_wf_id = smoke_wf.id
        else:
            smoke_wf_id = self._uow.workflows.create({
                "name": config.SMOKE_WORKFLOW_NAME,
                "description": "Smoke test workflow",
                "_skip_default_phase": True,
            })
        smoke_project = self._uow.projects.get_by_code(config.SMOKE_PROJECT_CODE)
        if smoke_project is None:
            self._uow.projects.create({
                "workflow_id": smoke_wf_id,
                "code": config.SMOKE_PROJECT_CODE,
                "name": config.SMOKE_PROJECT_NAME,
                "key_prefixes": list(config.SMOKE_TASK_KEY_PREFIXES),
                "workflow_name": config.SMOKE_WORKFLOW_NAME,
            })
            self._uow.commit()
        self._ensure_smoke_phases()

    def _ensure_smoke_phases(self) -> None:
        from project_workflow import config
        smoke_wf = self._uow.workflows.get_by_name(config.SMOKE_WORKFLOW_NAME)
        if not smoke_wf:
            return
        smoke_phases = list(self._uow.phases.list(workflow_id=smoke_wf.id))
        if smoke_phases:
            return
        seed_phases = schema.load_phases_from_seed(config.SMOKE_SEED_PATH)
        for order, phase in enumerate(seed_phases, start=1):
            data = {
                "workflow_id": smoke_wf.id,
                "code": phase.code,
                "name": phase.name,
                "description": phase.description,
                "min_time_min": phase.min_time_min,
                "phase_order": order,
                "next_recommendation": phase.next_recommendation,
                "parallel_with": phase.parallel_with,
                "rollback_target": phase.rollback_target,
                "execution_type": phase.execution_type,
                "is_seed_managed": True,
            }
            if phase.delegate:
                agent = self._uow.agents.get_by_name(phase.delegate.agent)
                if agent:
                    data["agent_id"] = agent.id
            phase_id = self._uow.phases.create(data)
            for idx, instr in enumerate(phase.instructions, start=1):
                self._uow.instructions.create(
                    int(phase_id),
                    {
                        "step_num": idx,
                        "description": instr.step,
                        "example": instr.example,
                        "execution_type": instr.execution_type,
                        "skills": instr.skills,
                    },
                )
            self._uow.phases.set_checks(
                int(phase_id),
                [{"description": c.description} for c in phase.checks],
            )
            self._uow.phases.set_evidence(
                int(phase_id),
                [{"description": e.item} for e in phase.evidence],
            )
        self._uow.commit()

    def _first_phase_code_for_project(self, project_id: int) -> str:
        project = self._project_service.get_project(project_id)
        workflow_id = project["workflow_id"] if project else None
        phases = schema.load_phases_from_db(self._uow, workflow_id=workflow_id)
        return phases[0].code if phases else "-1"

    def _resolve_current_phase(self) -> str:
        if not self.task:
            return "-1"
        current = str(self.task.get("current_phase") or "").strip()
        if current and current in self.phase_map:
            return current
        if self.all_phases:
            fallback = self.all_phases[0].code
            if current != fallback:
                self._task_service.update_task(self.task["id"], {"current_phase": fallback})
                self.task = self._task_service.get_task(self.task["id"]) or self.task
            return fallback
        return current or "-1"

    def _get_current_phase_obj(self) -> Phase | None:
        return self.phase_map.get(self.current_phase)

    def _phase_by_id(self, phase_id: int) -> Phase | None:
        needle = int(phase_id)
        for phase in self.all_phases:
            if phase.id is not None and int(phase.id) == needle:
                return phase
        return None

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
                    from .checks import normalize_text
                    previously.add(normalize_text(item))
        return previously

    @staticmethod
    def _normalize_text(text):
        return normalize_text(text)

    @staticmethod
    def _extract_keywords(text):
        return extract_keywords(text)

    @staticmethod
    def _check_coverage(report, checklist, previously_covered=None):
        return check_coverage(report, checklist, previously_covered)

    @staticmethod
    def _extract_blockers(report):
        return extract_blockers(report)

    def _has_delegate_signal(self, report):
        from .checks import has_delegate_signal
        return has_delegate_signal(report)

    def _build_fail_message(self, phase, missing, blockers):
        from .checks import build_fail_message
        phase_name = getattr(phase, "name", phase) if hasattr(phase, "name") else phase
        return build_fail_message(phase_name, missing, blockers)

    def _determine_verdict(self, phase, covered, missing, blockers, report):
        return determine_verdict(
            covered=covered,
            missing=missing,
            blockers=blockers,
            report=report,
            is_delegated=getattr(phase, "is_delegated", False),
            rollback_target=getattr(phase, "rollback_target", None),
        )

    def _get_next_phase(self, phase_code):
        cb = PhaseContractBuilder(self.all_phases)
        return cb.get_next_phase(phase_code)

    def _get_parallel_group(self, start_phase):
        cb = PhaseContractBuilder(self.all_phases)
        return cb.get_parallel_group(start_phase)

    def _get_next_phase_after_group(self, group):
        cb = PhaseContractBuilder(self.all_phases)
        return cb._next_after_group(group)

    def _build_result(self, *, phase, verdict, covered, missing, blockers, next_phase, next_phase_name, rollback_target):
        result = {
            "verdict": VERDICT_LABELS[verdict],
            "task_key": self.task_key,
            "phase": phase.code,
            "phase_name": phase.name,
            "covered": covered,
            "missing": missing,
            "blockers": blockers,
            "current_phase": phase.code,
            "next_phase": next_phase,
            "next_phase_name": next_phase_name,
            "rollback_target": rollback_target,
            "required_evidence": [text_from_evidence(item) for item in phase.evidence],
            "required_checks": [text_from_check(item) for item in phase.checks],
            "instructions": [text_from_instruction(item) for item in phase.instructions],
            "next_step": next_phase or rollback_target or phase.code,
        }
        if verdict == "pass":
            result["message"] = phase.next_recommendation or f"Phase {phase.code} accepted."
        elif verdict == "rollback":
            result["message"] = f"Phase {phase.code} failed gate and must roll back to {rollback_target}."
        elif verdict == "delegate":
            result["message"] = f"Delegate work for phase {phase.code} before continuing."
        else:
            result["message"] = build_verdict_message(verdict, phase.name, phase.code, blockers, missing, next_phase, rollback_target)
        return result

    def _build_parallel_result(self, group, verdict, covered, missing, blockers, next_phase, next_phase_name, rollback_target):
        first = group[0]
        phase_codes = [p.code for p in group]
        rollback_phase_obj = self.phase_map.get(rollback_target) if rollback_target else None
        result = {
            "verdict": VERDICT_LABELS[verdict],
            "task_key": self.task_key,
            "phase": first.code,
            "phase_name": f"Parallel group: {', '.join(phase_codes)}",
            "covered": covered,
            "missing": missing,
            "blockers": blockers,
            "current_phase": first.code,
            "next_phase": next_phase if verdict == "pass" else rollback_target if verdict == "rollback" else None,
            "next_phase_name": next_phase_name if verdict == "pass" else (rollback_phase_obj.name if rollback_phase_obj else None),
            "rollback_target": rollback_target,
            "required_evidence": list({text_from_evidence(ev) for p in group for ev in p.evidence}),
            "required_checks": list({text_from_check(chk) for p in group for chk in p.checks}),
            "instructions": [text_from_instruction(inst) for p in group for inst in p.instructions],
            "next_step": next_phase or rollback_target or first.code,
        }
        if verdict == "pass":
            result["message"] = f"Parallel group ({', '.join(phase_codes)}) accepted. Proceed to {next_phase or 'completion'}."
        elif verdict == "rollback":
            result["message"] = f"Parallel group ({', '.join(phase_codes)}) failed. Roll back to {rollback_target}."
        elif verdict == "blocked":
            issues = missing or blockers or phase_codes
            result["message"] = f"BLOCKED: {'; '.join(issues)}. Fix and resubmit."
        elif verdict == "delegate":
            result["message"] = f"Delegate work for parallel group ({', '.join(phase_codes)}) before continuing."
        else:
            issues = missing or ["unspecified items"]
            result["message"] = f"PARTIAL: {'; '.join(issues)}. Complete before continuing."
        return result

    def _build_checklist(self, phase):
        cb = PhaseContractBuilder(self.all_phases)
        return cb.build_checklist(phase)

    def _build_parallel_checklist(self, group):
        cb = PhaseContractBuilder(self.all_phases)
        return cb.build_parallel_checklist(group)

    def _build_current_contract(self, phase):
        cb = PhaseContractBuilder(self.all_phases)
        if not phase:
            return cb.build_missing(self.current_phase).to_dict()
        return cb.build(phase).to_dict()

    @property
    def _context_builder(self):
        return WizardContextBuilder(
            uow=self._uow,
            task=self.task,
            project=self.project,
            workflow=self.workflow,
            all_phases=self.all_phases,
            current_phase=self.current_phase,
            task_key=self.task_key,
            repo=self.repo,
        )

    def _build_phase_history(self) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        if not self.task:
            return history
        for row in self._uow.get_task_history(self.task["id"]):
            phase = self._phase_by_id(row["phase_id"])
            if not phase:
                continue
            history.append({
                "phase_code": phase.code,
                "phase_name": phase.name,
                "status": row["status"],
                "completed_at": row["completed_at"],
            })
        return history

    def _build_recent_verdicts(self, limit: int = 5) -> list[dict[str, Any]]:
        verdicts: list[dict[str, Any]] = []
        if not self.task:
            return verdicts
        for row in self._uow.get_supervisor_runs(task_id=self.task["id"], limit=limit):
            if isinstance(row, dict):
                verdicts.append({
                    "phase_code": row.get("phase_code"),
                    "verdict": str(row.get("verdict") or "").upper(),
                    "blockers": row.get("blockers") or [],
                    "missing": row.get("missing") or [],
                    "next_phase": row.get("next_phase_code"),
                    "rollback_target": row.get("rollback_phase_code"),
                    "created_at": row.get("created_at"),
                })
            else:
                verdicts.append({
                    "phase_code": row.phase_code,
                    "verdict": str(row.verdict or "").upper(),
                    "blockers": row.blockers or [],
                    "missing": row.missing or [],
                    "next_phase": row.next_phase_code,
                    "rollback_target": row.rollback_phase_code,
                    "created_at": row.created_at,
                })
        return verdicts

    def _phase_status_lookup(self) -> dict[str, str]:
        statuses: dict[str, str] = {}
        if not self.task:
            return statuses
        for row in self._uow.get_task_history(self.task["id"]):
            phase = self._phase_by_id(row["phase_id"])
            if phase:
                statuses[phase.code] = str(row["status"])
        current_phase = str(self.task.get("current_phase") or self.current_phase)
        if current_phase in self.phase_map and current_phase not in statuses and self.task.get("status") != "done":
            statuses[current_phase] = "current"
        return statuses

    def _build_workflow_path(self) -> list[dict[str, Any]]:
        status_lookup = self._phase_status_lookup()
        path: list[dict[str, Any]] = []
        for phase in self.all_phases:
            path.append({
                "code": phase.code,
                "name": phase.name,
                "status": status_lookup.get(phase.code, "pending"),
                "parallel_with": phase.parallel_with,
                "rollback_target": phase.rollback_target,
            })
        return path

    def _record_transition(self, phase: Phase, verdict: str, next_phase: str | None, rollback_target: str | None) -> None:
        from ..domain.fsm import PhaseFSM
        fsm = PhaseFSM(initial="in_progress")
        fsm.apply_verdict(verdict)
        new_state = fsm.state
        if not self.task:
            return
        task_id = int(self.task["id"])
        # Resolve str phase codes to int ids for FK columns
        next_phase_obj = self.phase_map.get(next_phase) if next_phase and next_phase in self.phase_map else None
        next_phase_id = next_phase_obj.id if next_phase_obj else None
        if new_state == "done":
            self.db.add_task_history(task_id, phase.id, "done")
            if next_phase_id:
                self.db.add_task_history(task_id, next_phase_id, "pending")
                self.db.update_task(task_id, {"current_phase": next_phase, "status": "active"})
            else:
                self.db.update_task(task_id, {"current_phase": phase.code, "status": "done"})
            self._uow.commit()
            return
        if new_state == "blocked":
            self.db.add_task_history(task_id, phase.id, "blocked")
            self.db.update_task(task_id, {"current_phase": phase.code, "status": "blocked"})
            self._uow.commit()
            return
        if new_state == "rollback":
            target_phase = self.phase_map.get(rollback_target) if rollback_target else None
            target_id = target_phase.id if target_phase else phase.id
            self.db.add_task_history(task_id, phase.id, "rollback")
            self.db.add_task_history(task_id, target_id, "pending")
            self.db.update_task(task_id, {"current_phase": rollback_target or phase.code, "status": "active"})
            self._uow.commit()
            return
        if new_state == "delegated":
            self.db.add_task_history(task_id, phase.id, "delegated")
            self.db.update_task(task_id, {"current_phase": phase.code, "status": "active"})
            self._uow.commit()
            return
        # partial or in_progress
        self.db.add_task_history(task_id, phase.id, "partial")
        self.db.update_task(task_id, {"current_phase": phase.code, "status": "active"})
        self._uow.commit()

    def _record_parallel_transition(self, group: list[Phase], verdict: str, next_phase: str | None) -> None:
        from ..domain.fsm import PhaseFSM
        fsm = PhaseFSM(initial="in_progress")
        fsm.apply_verdict(verdict)
        new_state = fsm.state
        if not self.task:
            return
        task_id = int(self.task["id"])
        if new_state == "done":
            for phase in group:
                self.db.add_task_history(task_id, phase.id, "done")
            if next_phase:
                next_phase_obj = self.phase_map.get(next_phase)
                next_phase_id = next_phase_obj.id if next_phase_obj else None
                if next_phase_id:
                    self.db.add_task_history(task_id, next_phase_id, "pending")
                self.db.update_task(task_id, {"current_phase": next_phase, "status": "active"})
            else:
                self.db.update_task(task_id, {"current_phase": group[-1].code, "status": "done"})
            self._uow.commit()
            return
        if new_state == "blocked":
            self.db.update_task(task_id, {"current_phase": group[0].code, "status": "blocked"})
            self._uow.commit()
            return
        if new_state == "rollback":
            target_phase = self.phase_map.get(next_phase) if next_phase else None
            target_code = target_phase.code if target_phase else group[-1].code
            self.db.update_task(task_id, {"current_phase": target_code, "status": "active"})
            self._uow.commit()
            return
        # partial: legacy tests expect no DB side effects at all.
        return

    # ── Context / Prompt ─────────────────────────────────────────────────────

    def get_full_context(self, use_cache: bool = True) -> dict:
        if use_cache:
            cached = self._cache.get(self.task_key, self.current_phase)
            if cached:
                return cached
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
        ctx = builder.build()
        self._cache.set(self.task_key, self.current_phase, ctx)
        return ctx

    def get_phase_prompt(self, phase_id: Optional[str] = None) -> str:
        ctx = self.get_full_context()
        return build_phase_prompt(
            task_key=self.task_key,
            phase_map=self.phase_map,
            all_phases=self.all_phases,
            current_phase=self.current_phase,
            ctx=ctx,
            phase_id=phase_id,
        )

    # ── Evaluate ─────────────────────────────────────────────────────

    def evaluate(self, report: str) -> dict:
        phase = self._get_current_phase_obj()
        if not phase:
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

        import project_workflow.wizard as _wizard_mod
        if _wizard_mod.SMART_EVALUATE:
            try:
                return self.evaluate_llm(report, phase)
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM evaluate failed: %s", exc)
                pass

        is_parallel = phase.execution_type == "parallel"
        if is_parallel:
            group = self._get_parallel_group(phase)
            checklist = self._build_parallel_checklist(group)
        else:
            group = [phase]
            checklist = self._build_checklist(phase)

        previously_covered = self._get_previously_covered(phase.code)
        covered, missing = self._check_coverage(report, checklist, previously_covered)
        blockers = self._extract_blockers(report)
        verdict = self._determine_verdict(phase, covered, missing, blockers, report)

        if is_parallel:
            next_phase, next_phase_name = self._get_next_phase_after_group(group)
            if verdict == "rollback":
                rollback_target = group[0].rollback_target
            else:
                rollback_target = None
            if verdict != "pass":
                next_phase = None
                next_phase_name = None
        else:
            next_phase, next_phase_name = self._get_next_phase(phase.code)
            rollback_target = phase.rollback_target if verdict == "rollback" else None

        cb = PhaseContractBuilder(self.all_phases)
        next_phase_contract = cb.build_next_contract(next_phase) if verdict == "pass" else None

        # Build structured assessment
        phase_name = phase.name
        if is_parallel:
            phase_name = f"Parallel group: {', '.join(p.code for p in group)}"

        if verdict == "pass" and next_phase:
            next_phase_obj = self.phase_map.get(next_phase)
            next_phase_name = next_phase_obj.name if next_phase_obj else next_phase_name

        assessment = WizardAssessment(
            task_key=self.task_key,
            phase_code=phase.code,
            phase_name=phase_name,
            verdict=verdict,
            covered=covered,
            missing=missing,
            blockers=blockers,
            next_phase=next_phase if verdict == "pass" else (rollback_target if verdict == "rollback" else None),
            next_phase_name=next_phase_name if verdict == "pass" else None,
            rollback_target=rollback_target,
            next_phase_contract=next_phase_contract,
            instructions=[text_from_instruction(i) for i in phase.instructions],
            required_checks=[text_from_check(c) for c in phase.checks],
            required_evidence=[text_from_evidence(e) for e in phase.evidence],
            message=build_verdict_message(
                verdict=verdict,
                phase_name=phase_name,
                phase_code=phase.code,
                blockers=blockers,
                missing=missing,
                next_phase=next_phase,
                rollback_target=rollback_target,
                is_parallel=is_parallel,
                group_codes=[p.code for p in group] if is_parallel else None,
            ),
        )

        result = assessment.to_result_dict()
        if next_phase_contract is not None:
            result["next_phase_contract"] = next_phase_contract.to_dict() if hasattr(next_phase_contract, "to_dict") else next_phase_contract

        # Record transition
        if is_parallel:
            self._record_parallel_transition(group, verdict, next_phase)
        else:
            self._record_transition(phase, verdict, next_phase, rollback_target)

        self._uow.commit()
        if not self.task:
            return result
        self.task = self._task_service.get_task(self.task["id"]) or self.task
        self.current_phase = self._resolve_current_phase()

        # Persist assessment
        next_phase_obj = self.phase_map.get(next_phase) if next_phase and next_phase in self.phase_map else None
        rollback_phase_obj = self.phase_map.get(rollback_target) if rollback_target and rollback_target in self.phase_map else None
        self.db.create_supervisor_run(
            task_id=self.task["id"],
            phase_id=phase.id,
            verdict=assessment.verdict,
            report=assessment.message or "",
            covered=assessment.covered,
            missing=assessment.missing,
            blockers=assessment.blockers,
            next_phase_id=next_phase_obj.id if next_phase_obj else None,
            rollback_phase_id=rollback_phase_obj.id if rollback_phase_obj else None,
            context_snapshot={
                "phase": assessment.phase_code,
                "phase_name": assessment.phase_name,
                "current_contract": {"phase_code": assessment.phase_code},
            },
            response=assessment.to_result_dict(),
        )

        return result

    # ── LLM evaluate (optional) ──────────────────────────────────────

    def evaluate_llm(self, report: str, phase: Phase) -> dict:
        """LLM-based evaluate via Ollama + Kimi K2.5."""
        from .evaluate import evaluate_llm_report
        return evaluate_llm_report(report, phase, self)


# ═══════════════════════════════════════════════════════════════════════
# Public wrappers / CLI compatibility
# ═══════════════════════════════════════════════════════════════════════


def evaluate_report(task_key: str, report: str, repo: Optional[str] = None) -> dict:
    import project_workflow.wizard as _wizard_pkg
    engine = _wizard_pkg.WizardEngine(task_key, repo)
    return engine.evaluate(report)


def evaluate_report_formatted(task_key: str, report: str, repo: Optional[str] = None) -> str:
    """CLI shortcut — returns human-readable result."""
    result = evaluate_report(task_key, report, repo)
    return format_result(result)


def get_phase_instructions(task_key: str, phase_id: Optional[str] = None, repo: Optional[str] = None) -> str:
    import project_workflow.wizard as _wizard_pkg
    engine = _wizard_pkg.WizardEngine(task_key, repo)
    return engine.get_phase_prompt(phase_id)


def main(task_key: str, repo: Optional[str] = None, report: Optional[str] = None) -> None:
    """Deprecated compatibility entrypoint.

    Kept only for existing scripts/tests that call wizard.main() directly.
    New code should use WizardEngine(task_key).get_phase_prompt() or
    WizardEngine(task_key).evaluate(report).
    """
    import sys
    import project_workflow.wizard as _wizard_pkg
    if report:
        result = evaluate_report(task_key, report, repo)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["verdict"] == "PASS" else 1)
    print(_wizard_pkg.get_phase_instructions(task_key, repo=repo))


# ── Legacy format_result ───────────────────────────────────────────

def format_result(result: dict) -> str:
    """CLI evaluate → человекочитаемый вывод. Только инструкции, чекапы, доказательства."""
    verdict = result.get("verdict", "UNKNOWN")
    covered = result.get("covered", []) or []
    missing = result.get("missing", []) or []

    if verdict == "PASS":
        npc = result.get("next_phase_contract") or {}
        instructions = npc.get("instructions", [])
        checks = npc.get("required_checks", [])
        evidence = npc.get("required_evidence", [])
    else:
        instructions = result.get("instructions", []) or []
        checks = result.get("required_checks", []) or []
        evidence = result.get("required_evidence", []) or []

    lines: list[str] = []

    message = result.get("message", "")
    if message and verdict != "PASS":
        lines.append(message)
        lines.append("")

    if verdict == "PARTIAL":
        lines.append("Ты сделал часть, доделай:")
        lines.append("")

    next_contract = result.get("next_phase_contract") or {}
    next_exec = next_contract.get("execution_type", "")
    next_parallel_with = next_contract.get("parallel_with")
    if verdict == "PASS" and next_exec == "parallel":
        if next_parallel_with:
            lines.append(f"Параллельно с {next_parallel_with}")
        else:
            lines.append("Параллельная фаза")
        lines.append("")

    current_phase_name = result.get("phase_name", "")
    current_phase = result.get("phase", "")
    if verdict == "PASS" and next_exec == "sync" and ("Parallel" in current_phase_name or current_phase.startswith(("smoke.parallel", "parallel"))):
        lines.append("Следующая фаза выполняется после завершения параллельного блока")
        lines.append("")

    if instructions:
        lines.append("Инструкции:")
        for item in instructions:
            lines.append(f"  • {item}")

    if checks:
        if verdict == "PASS":
            lines.append("")
            lines.append("Чекапы:")
            for item in checks:
                status = "✓" if item in covered else ("✗" if item in missing else "·")
                lines.append(f"  {status} {item}")
        else:
            not_done = [item for item in checks if item not in covered]
            if not_done:
                lines.append("")
                lines.append("Чекапы:")
                for item in not_done:
                    lines.append(f"  ✗ {item}")

    if evidence:
        if verdict == "PASS":
            lines.append("")
            lines.append("Доказательства:")
            for item in evidence:
                status = "✓" if item in covered else ("✗" if item in missing else "·")
                lines.append(f"  {status} {item}")
        else:
            not_done = [item for item in evidence if item not in covered]
            if not_done:
                lines.append("")
                lines.append("Доказательства:")
                for item in not_done:
                    lines.append(f"  ✗ {item}")

    return "\n".join(lines)
