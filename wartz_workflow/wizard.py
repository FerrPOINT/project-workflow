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
import os
import threading
from typing import Any, Optional

from . import conversation as convo
from . import schema
from .db import WorkflowDB
from .models import Phase
from .llm import OllamaClient, PromptBuilder, ResponseParser

from .wizard_types import PhaseContract, WizardAssessment, WizardFinding
from .wizard_context import WizardContextBuilder
from .wizard_contracts import PhaseContractBuilder, text_from_instruction, text_from_check, text_from_evidence
from .wizard_checks import check_coverage, extract_blockers, determine_verdict, build_verdict_message
from .wizard_store import WizardAssessmentStore

# Backward-compatible re-exports for existing tests
from .wizard_checks import BLOCKER_PATTERNS, DELEGATE_PATTERNS, normalize_text, extract_keywords

SMART_EVALUATE = os.getenv("SMART_EVALUATE", "").lower() in ("1", "true", "yes", "on")

VERDICT_LABELS = {
    "pass": "PASS",
    "partial": "PARTIAL",
    "blocked": "BLOCKED",
    "rollback": "ROLLBACK",
    "delegate": "DELEGATE",
}

# Backward-compatible re-exports for existing tests
from .wizard_checks import BLOCKER_PATTERNS, DELEGATE_PATTERNS, normalize_text, extract_keywords
from .models import Phase as _Phase  # noqa: F401


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

    def __init__(self, task_key: str, repo: Optional[str] = None):
        self.task_key = task_key
        self.repo = repo
        self.db = WorkflowDB()
        self.db.init()
        schema.ensure_phase_catalog(self.db)

        self.task = self._ensure_task()
        self.project = self.db.get_project(self.task["project_id"])
        self.workflow_id = self.project["workflow_id"] if self.project else None
        self.workflow = self.db.get_workflow(self.workflow_id) if self.workflow_id else None
        self._all_phases: list[Phase] | None = None
        self._phase_map: dict[str, Phase] | None = None
        self.current_phase = self._resolve_current_phase()
        self._cache = PromptCache()

    @property
    def all_phases(self) -> list[Phase]:
        if self._all_phases is None:
            self._all_phases = schema.load_phases_from_db(self.db, workflow_id=self.workflow_id)
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
        existing = self.db.get_task_by_key(self.task_key)
        if existing:
            if str(existing.get("current_phase") or "").strip() == "":
                current_phase = self._first_phase_code_for_project(existing["project_id"])
                self.db.update_task(existing["id"], {"current_phase": current_phase})
                return self.db.get_task(existing["id"]) or existing
            return existing

        project = self.db.match_project_for_task_key(self.task_key, strict=False)
        if not project:
            raise ValueError(f"Cannot resolve project for task key: {self.task_key}")
        current_phase = self._first_phase_code_for_project(project["id"])
        task_id = self.db.create_task(
            {
                "project": project["id"],
                "task_key": self.task_key,
                "title": self.task_key,
                "current_phase": current_phase,
                "status": "active",
            }
        )
        task = self.db.get_task(task_id)
        if not task:
            raise ValueError(f"Failed to create task: {self.task_key}")
        return task

    def _first_phase_code_for_project(self, project_id: int) -> str:
        project = self.db.get_project(project_id)
        workflow_id = project["workflow_id"] if project else None
        phases = schema.load_phases_from_db(self.db, workflow_id=workflow_id)
        return phases[0].code if phases else "-1"

    def _resolve_current_phase(self) -> str:
        current = str(self.task.get("current_phase") or "").strip()
        if current and current in self.phase_map:
            return current
        if self.all_phases:
            fallback = self.all_phases[0].code
            if current != fallback:
                self.db.update_task(self.task["id"], {"current_phase": fallback})
                self.task = self.db.get_task(self.task["id"]) or self.task
            return fallback
        return current or "-1"

    def _get_current_phase_obj(self) -> Phase | None:
        return self.phase_map.get(self.current_phase)

    def _phase_by_id(self, phase_id: int) -> Phase | None:
        for phase in self.all_phases:
            if int(phase.id) == int(phase_id):
                return phase
        return None

    def _get_previously_covered(self, phase_code: str) -> set[str]:
        """Return items already covered in previous supervisor runs for this phase."""
        previously: set[str] = set()
        task_id = int(self.task.get("id", 0))
        if not task_id:
            return previously
        runs = self.db.get_supervisor_runs(task_id=task_id, limit=20)
        for run in runs:
            if run.get("phase_code") != phase_code:
                continue
            covered = run.get("covered", [])
            for item in covered:
                if isinstance(item, str):
                    from .wizard_checks import normalize_text
                    previously.add(normalize_text(item))
        return previously

    @staticmethod
    def _text_from_instruction(item):
        return text_from_instruction(item)

    @staticmethod
    def _text_from_check(item):
        return text_from_check(item)

    @staticmethod
    def _text_from_evidence(item):
        return text_from_evidence(item)

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
        from .wizard_checks import has_delegate_signal
        return has_delegate_signal(report)

    def _build_fail_message(self, phase, missing, blockers):
        from .wizard_checks import build_fail_message
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
            "next_phase_name": next_phase_name if verdict == "pass" else (self.phase_map.get(rollback_target).name if rollback_target and self.phase_map.get(rollback_target) else None),
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

    def _build_phase_history(self):
        builder = WizardContextBuilder(
            db=self.db, task=self.task, project=self.project,
            workflow=self.workflow, all_phases=self.all_phases,
            current_phase=self.current_phase, task_key=self.task_key, repo=self.repo,
        )
        return builder._build_phase_history()

    def _build_recent_verdicts(self, limit=5):
        builder = WizardContextBuilder(
            db=self.db, task=self.task, project=self.project,
            workflow=self.workflow, all_phases=self.all_phases,
            current_phase=self.current_phase, task_key=self.task_key, repo=self.repo,
        )
        return builder._build_recent_verdicts(limit=limit)

    def _phase_status_lookup(self):
        builder = WizardContextBuilder(
            db=self.db, task=self.task, project=self.project,
            workflow=self.workflow, all_phases=self.all_phases,
            current_phase=self.current_phase, task_key=self.task_key, repo=self.repo,
        )
        return builder._phase_status_lookup()

    def _build_workflow_path(self):
        builder = WizardContextBuilder(
            db=self.db, task=self.task, project=self.project,
            workflow=self.workflow, all_phases=self.all_phases,
            current_phase=self.current_phase, task_key=self.task_key, repo=self.repo,
        )
        return builder._build_workflow_path()

    # ── Transition recording ─────────────────────────────────────────

    def _record_transition(self, phase: Phase, verdict: str, next_phase: str | None, rollback_target: str | None) -> None:
        from .phase_fsm import PhaseFSM
        fsm = PhaseFSM(initial="in_progress")
        fsm.apply_verdict(verdict)
        new_state = fsm.state
        task_id = int(self.task["id"])
        if new_state == "done":
            self.db.add_task_history(task_id, phase.code, "done")
            if next_phase:
                self.db.add_task_history(task_id, next_phase, "pending")
                self.db.update_task(task_id, {"current_phase": next_phase, "status": "active"})
            else:
                self.db.update_task(task_id, {"current_phase": phase.code, "status": "done"})
            return
        if new_state == "blocked":
            self.db.add_task_history(task_id, phase.code, "blocked")
            self.db.update_task(task_id, {"current_phase": phase.code, "status": "blocked"})
            return
        if new_state == "rollback":
            target = rollback_target or phase.code
            self.db.add_task_history(task_id, phase.code, "rollback")
            self.db.add_task_history(task_id, target, "pending")
            self.db.update_task(task_id, {"current_phase": target, "status": "active"})
            return
        if new_state == "delegated":
            self.db.add_task_history(task_id, phase.code, "delegated")
            self.db.update_task(task_id, {"current_phase": phase.code, "status": "active"})
            return
        # partial or in_progress
        self.db.add_task_history(task_id, phase.code, "partial")
        self.db.update_task(task_id, {"current_phase": phase.code, "status": "active"})

    def _record_parallel_transition(self, group: list[Phase], verdict: str, next_phase: str | None) -> None:
        from .phase_fsm import PhaseFSM
        fsm = PhaseFSM(initial="in_progress")
        fsm.apply_verdict(verdict)
        new_state = fsm.state
        task_id = int(self.task["id"])
        if new_state == "done":
            for phase in group:
                self.db.add_task_history(task_id, phase.code, "done")
            if next_phase:
                self.db.add_task_history(task_id, next_phase, "pending")
                self.db.update_task(task_id, {"current_phase": next_phase, "status": "active"})
            else:
                self.db.update_task(task_id, {"current_phase": group[-1].code, "status": "done"})
            return
        if new_state == "blocked":
            self.db.update_task(task_id, {"status": "blocked"})

    # ── Context / Prompt ─────────────────────────────────────────────

    def get_full_context(self, use_cache: bool = True) -> dict:
        if use_cache:
            cached = self._cache.get(self.task_key, self.current_phase)
            if cached:
                return cached
        builder = WizardContextBuilder(
            db=self.db,
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
        target_phase = self.phase_map.get(phase_id or self.current_phase)
        if not target_phase:
            return f"Фаза {phase_id or self.current_phase} не найдена в workflow."

        ctx = self.get_full_context()
        cb = PhaseContractBuilder(self.all_phases)
        is_parallel_target = target_phase.execution_type == "parallel"
        if is_parallel_target:
            group = cb.get_parallel_group(target_phase)
            contract = cb.build_parallel(group).to_dict()
            parallel_banner = (
                "\n⚡ ПАРАЛЛЕЛЬНАЯ ГРУППА ФАЗ\n"
                f"Выполняются одновременно: {', '.join(contract.get('group_phases') or [])}\n"
                f"Отчёт по этой группе присылается ОДНИМ сообщением.\n"
            )
        else:
            if target_phase.code == self.current_phase:
                raw = ctx.get("current_contract")
                if isinstance(raw, dict):
                    contract = raw
                else:
                    contract = raw.to_dict() if raw else cb.build(target_phase).to_dict()
            else:
                contract = cb.build(target_phase).to_dict()
            parallel_banner = ""

        workflow_lines = [
            f"- {item['code']}: {item['name']} [{item['status']}]"
            for item in ctx["workflow_path"]
        ]
        instructions = contract.get("instructions") or ["Нет отдельных инструкций — следуй описанию фазы и обязательным проверкам."]
        checks = contract.get("required_checks") or ["Нет явных checks."]
        evidence = contract.get("required_evidence") or ["Нет явных evidence items."]
        report_lines = [f"- {key}: {value}" for key, value in ctx["report_template"].items()]
        cli_actor = ctx.get("cli_actor") or {
            "description": "CLI user",
            "entrypoint": "wartz-workflow step --task TASK-KEY [--report TEXT]",
        }

        delegated = ""
        if contract.get("delegate_agent"):
            delegated = (
                f"\nДелегировано агенту: {contract['delegate_agent']}"
                + (f" | toolsets: {', '.join(contract['delegate_toolsets'])}" if contract.get("delegate_toolsets") else "")
            )

        return (
            f"Задача: {self.task_key}\n"
            f"Repo: {self.repo or '-'}\n"
            f"Workflow: {ctx['workflow_name'] or '-'}\n"
            f"Текущий шаг: {target_phase.code} — {target_phase.name}\n"
            f"Исполнитель CLI: {cli_actor['description']}\n"
            f"CLI entrypoint: {cli_actor['entrypoint']}\n\n"
            f"Полный путь workflow:\n" + "\n".join(workflow_lines) + "\n\n"
            f"Контракт текущей фазы:\n"
            f"- Описание: {contract.get('description') or '-'}\n"
            f"- Тип выполнения: {contract.get('execution_type')}\n"
            f"- Параллельно с: {contract.get('parallel_with') or '-'}\n"
            f"- Rollback target: {contract.get('rollback_target') or '-'}\n"
            f"- Next recommendation: {contract.get('next_recommendation') or '-'}"
            f"{delegated}\n"
            f"{parallel_banner}\n"
            f"Инструкции:\n" + "\n".join(f"- {item}" for item in instructions) + "\n\n"
            f"Checks:\n" + "\n".join(f"- {item}" for item in checks) + "\n\n"
            f"Evidence:\n" + "\n".join(f"- {item}" for item in evidence) + "\n\n"
            f"Правила supervisor:\n" + "\n".join(f"- {item}" for item in ctx["global_instructions"]) + "\n\n"
            f"Формат отчёта:\n" + "\n".join(report_lines)
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

        if SMART_EVALUATE:
            try:
                return self.evaluate_llm(report, phase)
            except Exception:
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

        # Record transition
        if is_parallel:
            self._record_parallel_transition(group, verdict, next_phase)
        else:
            self._record_transition(phase, verdict, next_phase, rollback_target)

        self.task = self.db.get_task(self.task["id"]) or self.task
        self.current_phase = self._resolve_current_phase()

        # Persist assessment
        store = WizardAssessmentStore(self.db)
        store.save(assessment)

        return result

    # ── LLM evaluate (optional) ──────────────────────────────────────

    def evaluate_llm(self, report: str, phase: Phase) -> dict:
        """LLM-based evaluate via Ollama + Kimi K2.5."""
        from .wizard_checks import normalize_text
        previously = self._get_previously_covered(phase.code)
        previously_items = [
            item for item in PhaseContractBuilder(self.all_phases).build_checklist(phase)
            if normalize_text(item) in previously
        ]

        system = PromptBuilder.SYSTEM_PROMPT
        user = PromptBuilder.build_user_prompt(
            self.task_key, phase, report, previously_covered=previously_items or None
        )

        client = OllamaClient()
        raw = client.chat(system=system, user=user, temperature=0.1)
        llm = ResponseParser.parse(raw)

        next_phase = llm.next_phase
        next_phase_name = llm.next_phase_name
        if llm.verdict == "PASS" and not next_phase:
            cb = PhaseContractBuilder(self.all_phases)
            next_phase, next_phase_name = cb.get_next_phase(phase.code)

        blockers = llm.blockers if llm.blockers else []
        if llm.verdict == "BLOCKED":
            blockers = llm.blockers if llm.blockers else ["LLM identified blocker"]

        result = {
            "verdict": VERDICT_LABELS.get(llm.verdict.lower(), llm.verdict),
            "task_key": self.task_key,
            "phase": phase.code,
            "phase_name": phase.name,
            "covered": llm.covered,
            "missing": llm.missing,
            "blockers": blockers,
            "current_phase": phase.code,
            "next_phase": next_phase,
            "next_phase_name": next_phase_name,
            "rollback_target": phase.rollback_target if llm.verdict == "ROLLBACK" else None,
            "message": llm.message,
            "confidence": llm.confidence,
        }

        verdict_key = llm.verdict.lower()
        if verdict_key == "pass":
            self._record_transition(phase, "pass", next_phase, None)
        elif verdict_key == "rollback":
            self._record_transition(phase, "rollback", None, phase.rollback_target)
        else:
            self._record_transition(phase, verdict_key, None, None)

        self.task = self.db.get_task(self.task["id"]) or self.task
        self.current_phase = self._resolve_current_phase()
        context_snapshot = {"phase": phase.code, "phase_name": phase.name, "current_contract": {"phase_code": phase.code}}
        self.db.create_supervisor_run(
            {
                "task_id": self.task["id"],
                "phase_id": phase.code,
                "verdict": verdict_key,
                "report": report,
                "covered": llm.covered,
                "missing": llm.missing,
                "blockers": blockers,
                "next_phase_id": next_phase if verdict_key == "pass" else None,
                "rollback_phase_id": phase.rollback_target if verdict_key == "rollback" else None,
                "context_snapshot": context_snapshot,
                "response": result,
            }
        )
        return result


# ═══════════════════════════════════════════════════════════════════════
# Public wrappers / CLI compatibility
# ═══════════════════════════════════════════════════════════════════════


def evaluate_report(task_key: str, report: str, repo: Optional[str] = None) -> dict:
    engine = WizardEngine(task_key, repo)
    return engine.evaluate(report)


def evaluate_report_formatted(task_key: str, report: str, repo: Optional[str] = None) -> str:
    """CLI shortcut — returns human-readable result."""
    result = evaluate_report(task_key, report, repo)
    return format_result(result)


def get_phase_instructions(task_key: str, phase_id: Optional[str] = None, repo: Optional[str] = None) -> str:
    engine = WizardEngine(task_key, repo)
    return engine.get_phase_prompt(phase_id)


def main(task_key: str, repo: Optional[str] = None, report: Optional[str] = None) -> None:
    import sys
    if report:
        result = evaluate_report(task_key, report, repo)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["verdict"] == "PASS" else 1)
    print(get_phase_instructions(task_key, repo=repo))


# ── Legacy format_result ───────────────────────────────────────────

def format_result(result: dict) -> str:
    """CLI evaluate → человекочитаемый вывод. Только инструкции, чекапы, доказательства."""
    verdict = result.get("verdict", "UNKNOWN")
    covered = result.get("covered", []) or []
    missing = result.get("missing", []) or []

    if verdict == "PASS":
        instructions = result.get("next_phase_contract", {}).get("instructions", [])
        checks = result.get("next_phase_contract", {}).get("required_checks", [])
        evidence = result.get("next_phase_contract", {}).get("required_evidence", [])
    else:
        instructions = result.get("instructions", []) or []
        checks = result.get("required_checks", []) or []
        evidence = result.get("required_evidence", []) or []

    lines: list[str] = []

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
