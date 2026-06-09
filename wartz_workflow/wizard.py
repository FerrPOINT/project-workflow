"""DB-backed workflow supervisor over the phase catalog.

Public surface is intentionally kept compatible with the previous wizard module:
- WizardEngine(task_key, repo)
- WizardEngine.get_full_context()
- WizardEngine.get_phase_prompt()
- WizardEngine.evaluate(report)
- evaluate_report(...), get_phase_instructions(...), main(...)
"""

from __future__ import annotations

import json
import re
import threading
from typing import Any, Optional

from . import conversation as convo
from . import schema
from .db import WorkflowDB
from .models import Phase


VERDICT_LABELS = {
    "pass": "PASS",
    "partial": "PARTIAL",
    "blocked": "BLOCKED",
    "rollback": "ROLLBACK",
    "delegate": "DELEGATE",
}

BLOCKER_PATTERNS = (
    "blocked by",
    "blocker remains",
    "blocker",
    "cannot",
    "can't",
    "stuck",
    "failed",
    "failure",
    "блокер",
    "заблокировано",
    "заблокирована",
    "заблокирован",
    "не могу",
    "ошибка",
    "ошибки",
    "ошибок",
)

DELEGATE_PATTERNS = ("delegate", "delegated", "delegation", "передал", "делег")


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
        """Bump generation — old keys become unreachable."""
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
        self.all_phases = schema.load_phases_from_db(self.db, workflow_id=self.workflow_id)
        self.phase_map = {phase.code: phase for phase in self.all_phases}
        self.current_phase = self._resolve_current_phase()
        # Important: WizardEngine is often reconstructed per CLI call, so cache is ephemeral.
        # For long-lived engines, invalidate() must be called after any mutation.
        self._cache = PromptCache()

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

    def _phase_by_id(self, phase_id: int) -> Phase | None:
        for phase in self.all_phases:
            if int(phase.id) == int(phase_id):
                return phase
        return None

    def _get_current_phase_obj(self) -> Phase | None:
        return self.phase_map.get(self.current_phase)

    # ── Context builders ─────────────────────────────────────────────

    @staticmethod
    def _text_from_instruction(item: Any) -> str:
        return str(getattr(item, "step", "") or "").strip()

    @staticmethod
    def _text_from_check(item: Any) -> str:
        return str(getattr(item, "description", "") or "").strip()

    @staticmethod
    def _text_from_evidence(item: Any) -> str:
        return str(getattr(item, "item", "") or "").strip()

    def _phase_to_dict(self, phase: Phase) -> dict:
        agent_name = phase.delegate.agent if phase.delegate else None
        return {
            "id": phase.id,
            "code": phase.code,
            "name": phase.name,
            "description": phase.description,
            "instructions": [self._text_from_instruction(item) for item in phase.instructions],
            "checks": [self._text_from_check(item) for item in phase.checks],
            "evidence": [self._text_from_evidence(item) for item in phase.evidence],
            "execution_type": phase.execution_type,
            "next_recommendation": phase.next_recommendation,
            "parallel_with": phase.parallel_with,
            "rollback_target": phase.rollback_target,
            "delegate_agent": agent_name,
            "delegate_toolsets": list(phase.delegate.toolsets) if phase.delegate else [],
        }

    def _phase_status_lookup(self) -> dict[str, str]:
        statuses: dict[str, str] = {}
        for row in self.db.get_task_history(self.task["id"]):
            phase = self._phase_by_id(row["phase_id"])
            if phase:
                statuses[phase.code] = str(row["status"])
        current_phase = str(self.task.get("current_phase") or self.current_phase)
        if current_phase in self.phase_map and current_phase not in statuses and self.task.get("status") != "done":
            statuses[current_phase] = "current"
        return statuses

    def _build_phase_history(self) -> list[dict]:
        history: list[dict] = []
        for row in self.db.get_task_history(self.task["id"]):
            phase = self._phase_by_id(row["phase_id"])
            if not phase:
                continue
            history.append(
                {
                    "phase_code": phase.code,
                    "phase_name": phase.name,
                    "status": row["status"],
                    "completed_at": row["completed_at"],
                }
            )
        return history

    def _build_recent_verdicts(self, limit: int = 5) -> list[dict]:
        verdicts: list[dict] = []
        for row in self.db.get_supervisor_runs(task_id=self.task["id"], limit=limit):
            verdicts.append(
                {
                    "phase_code": row.get("phase_code"),
                    "verdict": VERDICT_LABELS.get(str(row.get("verdict")), str(row.get("verdict", "")).upper()),
                    "blockers": row.get("blockers", []),
                    "missing": row.get("missing", []),
                    "next_phase": row.get("next_phase_code"),
                    "rollback_target": row.get("rollback_phase_code"),
                    "created_at": row.get("created_at"),
                }
            )
        return verdicts

    def _build_workflow_path(self) -> list[dict]:
        status_lookup = self._phase_status_lookup()
        path: list[dict] = []
        for phase in self.all_phases:
            path.append(
                {
                    "code": phase.code,
                    "name": phase.name,
                    "status": status_lookup.get(phase.code, "pending"),
                    "parallel_with": phase.parallel_with,
                    "rollback_target": phase.rollback_target,
                }
            )
        return path

    def _build_current_contract(self, phase: Phase | None) -> dict:
        if not phase:
            return {
                "phase_code": self.current_phase,
                "phase_name": "Unknown phase",
                "description": "",
                "instructions": [],
                "required_checks": [],
                "required_evidence": [],
                "execution_type": "sync",
                "delegate_agent": None,
                "delegate_toolsets": [],
                "next_recommendation": "",
                "parallel_with": None,
                "rollback_target": None,
            }

        return {
            "phase_code": phase.code,
            "phase_name": phase.name,
            "description": phase.description,
            "instructions": [self._text_from_instruction(item) for item in phase.instructions],
            "required_checks": [self._text_from_check(item) for item in phase.checks],
            "required_evidence": [self._text_from_evidence(item) for item in phase.evidence],
            "execution_type": phase.execution_type,
            "delegate_agent": phase.delegate.agent if phase.delegate else None,
            "delegate_toolsets": list(phase.delegate.toolsets) if phase.delegate else [],
            "next_recommendation": phase.next_recommendation,
            "parallel_with": phase.parallel_with,
            "rollback_target": phase.rollback_target,
        }

    def _global_instructions(self) -> list[str]:
        return [
            "Do not skip phases or invent completed evidence.",
            "Evaluate progress strictly against the current phase contract from the DB phase catalog.",
            "Treat the CLI actor as the source of the report whether it is a human user or automation; do not assume a specific model/provider.",
            "Return a structured phase report with summary, completed items, evidence, blockers, and next step.",
            "If the phase is blocked, say exactly which checks/evidence are missing and whether rollback is required.",
        ]

    def _cli_actor(self) -> dict:
        return {
            "kind": "cli-user",
            "description": (
                "Любой пользователь или автоматизация, которая вызывает WARTZ Workflow CLI "
                "и отправляет report по текущей фазе. Supervisor не предполагает конкретную модель, "
                "Ollama или другого провайдера."
            ),
            "entrypoint": "wartz-workflow step --task TASK-KEY [--report TEXT]",
        }

    def _report_template(self) -> dict:
        return {
            "summary": "What was achieved in this phase.",
            "completed": "Bullet list of completed contract items.",
            "evidence": "Concrete evidence produced in this phase.",
            "blockers": "Explicit blockers or 'none'.",
            "next_step": "Single next recommended action.",
        }

    def get_full_context(self, use_cache: bool = True) -> dict:
        if use_cache:
            cached = self._cache.get(self.task_key, self.current_phase)
            if cached:
                return cached
        phase = self._get_current_phase_obj()
        workflow_path = self._build_workflow_path()
        completed_phases = [item["code"] for item in workflow_path if item["status"] == "done"]

        messages = []
        try:
            messages = convo.get_messages(self.task_key, limit=20)
        except Exception:
            messages = []

        ctx = {
            "task_key": self.task_key,
            "repo": self.repo,
            "project_code": self.project.get("code") if self.project else None,
            "project_name": self.project.get("name") if self.project else None,
            "workflow_name": self.workflow.get("name") if self.workflow else None,
            "workflow_id": self.workflow_id,
            "task_status": self.task.get("status"),
            "current_phase": self.current_phase,
            "current_phase_name": phase.name if phase else "Unknown phase",
            "completed_phases": completed_phases,
            "all_phases": [self._phase_to_dict(item) for item in self.all_phases],
            "workflow_path": workflow_path,
            "phase_history": self._build_phase_history(),
            "recent_verdicts": self._build_recent_verdicts(),
            "current_contract": self._build_current_contract(phase),
            "cli_actor": self._cli_actor(),
            "global_instructions": self._global_instructions(),
            "report_template": self._report_template(),
            "messages": messages,
            "total_phases": len(self.all_phases),
            "completed_count": len(completed_phases),
        }
        self._cache.set(self.task_key, self.current_phase, ctx)
        return ctx

    def _build_checklist(self, phase: Phase) -> list[str]:
        items: list[str] = []
        items.extend(self._text_from_instruction(item) for item in phase.instructions)
        items.extend(self._text_from_check(item) for item in phase.checks)
        items.extend(self._text_from_evidence(item) for item in phase.evidence)
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            k = item.strip().lower()
            if k and k not in seen:
                seen.add(k)
                deduped.append(item.strip())
        return deduped

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\wа-яА-Я0-9]+", " ", text.lower())).strip()

    def _extract_keywords(self, text: str) -> list[str]:
        normalized = self._normalize_text(text)
        words = [word for word in normalized.split() if len(word) >= 4]
        unique: list[str] = []
        for word in words:
            if word not in unique:
                unique.append(word)
        return unique[:6]

    def _get_previously_covered(self, phase_code: str) -> set[str]:
        """Return items already covered in previous supervisor runs for this phase."""
        previously: set[str] = set()
        task_id = int(self.task.get("id", 0))
        if not task_id:
            return previously
        # Find phase_id for this code
        phase_id = None
        for p in self.all_phases:
            if p.code == phase_code:
                phase_id = p.id
                break
        if not phase_id:
            return previously
        runs = self.db.get_supervisor_runs(task_id=task_id, limit=20)
        for run in runs:
            if run.get("phase_code") != phase_code:
                continue
            covered = run.get("covered", [])
            if isinstance(covered, str):
                try:
                    covered = json.loads(covered)
                except Exception:
                    covered = []
            for item in covered:
                if isinstance(item, str):
                    previously.add(self._normalize_text(item))
        return previously

    def _check_coverage(
        self, report: str, checklist: list[str], previously_covered: set[str] | None = None
    ) -> tuple[list[str], list[str]]:
        normalized_report = self._normalize_text(report)
        covered: list[str] = []
        missing: list[str] = []
        previously_covered = previously_covered or set()
        for item in checklist:
            normalized_item = self._normalize_text(item)
            keywords = self._extract_keywords(item)
            keyword_hits = sum(1 for keyword in keywords if keyword in normalized_report)
            exact_match = normalized_item and normalized_item in normalized_report
            already_covered = normalized_item in previously_covered
            enough_keywords = False
            if keywords:
                threshold = min(len(keywords), 2) if len(keywords) > 1 else 1
                enough_keywords = keyword_hits >= threshold
            if exact_match or enough_keywords or already_covered:
                covered.append(item)
            else:
                missing.append(item)
        return covered, missing

    def _extract_blockers(self, report: str) -> list[str]:
        lowered = report.lower()
        lowered = re.sub(r"\bblockers?\s*:\s*(none|no|нет)\b", " ", lowered)
        lowered = re.sub(r"\b(no blockers?|without blockers?|нет блокеров|без блокеров)\b", " ", lowered)
        found = [pattern for pattern in BLOCKER_PATTERNS if pattern in lowered]
        return list(dict.fromkeys(found))

    def _has_delegate_signal(self, report: str) -> bool:
        lowered = report.lower()
        return any(pattern in lowered for pattern in DELEGATE_PATTERNS)

    def _get_next_phase(self, phase_code: str) -> tuple[str | None, str | None]:
        for index, phase in enumerate(self.all_phases):
            if phase.code != phase_code:
                continue
            if index + 1 >= len(self.all_phases):
                return None, None
            next_phase = self.all_phases[index + 1]
            return next_phase.code, next_phase.name
        return None, None

    def _get_parallel_group(self, start_phase: Phase) -> list[Phase]:
        """Return the contiguous parallel run starting at (or containing) start_phase."""
        try:
            start_index = self.all_phases.index(start_phase)
        except ValueError:
            return [start_phase]
        group: list[Phase] = [self.all_phases[start_index]]
        for i in range(start_index + 1, len(self.all_phases)):
            if self.all_phases[i].execution_type == "parallel":
                group.append(self.all_phases[i])
            else:
                break
        return group

    def _get_next_phase_after_group(self, group: list[Phase]) -> tuple[str | None, str | None]:
        """Return the phase that follows the last phase in the group."""
        if not group:
            return None, None
        try:
            last_index = self.all_phases.index(group[-1])
        except ValueError:
            return None, None
        if last_index + 1 >= len(self.all_phases):
            return None, None
        nxt = self.all_phases[last_index + 1]
        return nxt.code, nxt.name

    def _build_parallel_contract(self, group: list[Phase]) -> dict:
        """Build a merged contract for a parallel group of phases."""
        instructions: list[str] = []
        checks: list[str] = []
        evidence: list[str] = []
        for phase in group:
            for inst in phase.instructions:
                text = self._text_from_instruction(inst)
                if text:
                    instructions.append(f"[{phase.code}] {text}")
            for chk in phase.checks:
                text = self._text_from_check(chk)
                if text:
                    checks.append(f"[{phase.code}] {text}")
            for ev in phase.evidence:
                text = self._text_from_evidence(ev)
                if text:
                    evidence.append(f"[{phase.code}] {text}")
        first = group[0]
        last = group[-1]
        # parallel_with of the first phase is the representative partner
        parallel_target = first.parallel_with
        next_phase, next_phase_name = self._get_next_phase_after_group(group)
        return {
            "phase_code": first.code,
            "phase_name": f"Parallel group: {', '.join(p.code for p in group)}",
            "description": "\n".join(f"- {p.code}: {p.description or '-'}" for p in group),
            "instructions": instructions or ["Нет отдельных инструкций — следуй описаниям фаз и обязательным проверкам."],
            "required_checks": checks or ["Нет явных checks."],
            "required_evidence": evidence or ["Нет явных evidence items."],
            "execution_type": "parallel",
            "delegate_agent": first.delegate.agent if first.delegate else None,
            "delegate_toolsets": list(first.delegate.toolsets) if first.delegate else [],
            "next_recommendation": f"После выполнения переходи к {next_phase or 'завершению workflow'} ({next_phase_name or '-'}).",
            "parallel_with": parallel_target,
            "rollback_target": first.rollback_target,
            "group_phases": [p.code for p in group],
        }

    def _build_parallel_checklist(self, group: list[Phase]) -> list[str]:
        """Build a merged checklist (checks + evidence only) for evaluating a parallel group."""
        items: list[str] = []
        for phase in group:
            for chk in phase.checks:
                items.append(self._text_from_check(chk))
            for ev in phase.evidence:
                items.append(self._text_from_evidence(ev))
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            k = item.strip().lower()
            if k and k not in seen:
                seen.add(k)
                deduped.append(item.strip())
        return deduped

    def _record_parallel_transition(self, group: list[Phase], verdict: str, next_phase: str | None) -> None:
        """Only commit transition on pass. Non-pass verdicts leave the group intact."""
        task_id = int(self.task["id"])
        if verdict == "pass":
            for phase in group:
                self.db.add_task_history(task_id, phase.code, "done")
            if next_phase:
                self.db.add_task_history(task_id, next_phase, "pending")
                self.db.update_task(task_id, {"current_phase": next_phase, "status": "active"})
            else:
                self.db.update_task(task_id, {"current_phase": group[-1].code, "status": "done"})
            return
        # Non-pass: do NOT touch task_history or current_phase.
        # The group remains active for the next attempt.
        if verdict == "blocked":
            self.db.update_task(task_id, {"status": "blocked"})

    def _build_fail_message(self, phase: Phase, missing: list[str], blockers: list[str]) -> str:
        issues = missing or blockers or [phase.name]
        return "Missing or blocked contract items: " + "; ".join(issues)

    def _determine_verdict(self, phase: Phase, covered: list[str], missing: list[str], blockers: list[str], report: str) -> str:
        if not missing and not blockers:
            return "pass"
        if self._has_delegate_signal(report) and phase.is_delegated:
            return "delegate"
        if (blockers or "rollback" in report.lower()) and phase.rollback_target:
            return "rollback"
        if blockers:
            return "blocked"
        if covered:
            return "partial"
        return "partial"

    def _record_transition(self, phase: Phase, verdict: str, next_phase: str | None, rollback_target: str | None) -> None:
        task_id = int(self.task["id"])
        if verdict == "pass":
            self.db.add_task_history(task_id, phase.code, "done")
            if next_phase:
                self.db.add_task_history(task_id, next_phase, "pending")
                self.db.update_task(task_id, {"current_phase": next_phase, "status": "active"})
            else:
                self.db.update_task(task_id, {"current_phase": phase.code, "status": "done"})
            return

        if verdict == "partial":
            self.db.add_task_history(task_id, phase.code, "partial")
            self.db.update_task(task_id, {"current_phase": phase.code, "status": "active"})
            return

        if verdict == "blocked":
            self.db.add_task_history(task_id, phase.code, "blocked")
            self.db.update_task(task_id, {"current_phase": phase.code, "status": "blocked"})
            return

        if verdict == "rollback":
            target = rollback_target or phase.code
            self.db.add_task_history(task_id, phase.code, "rollback")
            self.db.add_task_history(task_id, target, "pending")
            self.db.update_task(task_id, {"current_phase": target, "status": "active"})
            return

        self.db.add_task_history(task_id, phase.code, "delegated")
        self.db.update_task(task_id, {"current_phase": phase.code, "status": "active"})

    def _build_result(
        self,
        *,
        phase: Phase,
        verdict: str,
        covered: list[str],
        missing: list[str],
        blockers: list[str],
        next_phase: str | None,
        next_phase_name: str | None,
        rollback_target: str | None,
    ) -> dict:
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
            "required_evidence": [self._text_from_evidence(item) for item in phase.evidence],
            "required_checks": [self._text_from_check(item) for item in phase.checks],
            "next_step": next_phase or rollback_target or phase.code,
        }
        if verdict == "pass":
            result["message"] = phase.next_recommendation or f"Phase {phase.code} accepted."
        elif verdict == "rollback":
            result["message"] = f"Phase {phase.code} failed gate and must roll back to {rollback_target}."
        elif verdict == "blocked":
            result["message"] = self._build_fail_message(phase, missing, blockers)
        elif verdict == "delegate":
            result["message"] = f"Delegate work for phase {phase.code} before continuing."
        else:
            result["message"] = f"Phase {phase.code} is only partially satisfied."
        return result

    def _build_parallel_result(
        self,
        group: list[Phase],
        verdict: str,
        covered: list[str],
        missing: list[str],
        blockers: list[str],
        next_phase: str | None,
        next_phase_name: str | None,
        rollback_target: str | None,
    ) -> dict:
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
            "next_phase_name": next_phase_name if verdict == "pass" else (self.phase_map.get(rollback_target).name if rollback_target else None),
            "rollback_target": rollback_target,
            "required_evidence": list({self._text_from_evidence(ev) for p in group for ev in p.evidence}),
            "required_checks": list({self._text_from_check(chk) for p in group for chk in p.checks}),
            "next_step": next_phase or rollback_target or first.code,
        }
        if verdict == "pass":
            result["message"] = f"Parallel group ({', '.join(phase_codes)}) accepted. Proceed to {next_phase or 'completion'}."
        elif verdict == "rollback":
            result["message"] = f"Parallel group ({', '.join(phase_codes)}) failed. Roll back to {rollback_target}."
        elif verdict == "blocked":
            issues = missing or blockers or phase_codes
            result["message"] = "Parallel group blocked. Missing items: " + "; ".join(issues)
        elif verdict == "delegate":
            result["message"] = f"Delegate work for parallel group ({', '.join(phase_codes)}) before continuing."
        else:
            result["message"] = f"Parallel group ({', '.join(phase_codes)}) only partially satisfied."
        return result

    # ── Public API ───────────────────────────────────────────────────

    def get_phase_prompt(self, phase_id: Optional[str] = None) -> str:
        target_phase = self.phase_map.get(phase_id or self.current_phase)
        if not target_phase:
            return f"Фаза {phase_id or self.current_phase} не найдена в workflow."

        ctx = self.get_full_context()
        # ── Parallel group handling ────────────────────────────────────
        is_parallel_target = target_phase.execution_type == "parallel"
        if is_parallel_target:
            group = self._get_parallel_group(target_phase)
            contract = self._build_parallel_contract(group)
            parallel_banner = (
                "\n⚡ ПАРАЛЛЕЛЬНАЯ ГРУППА ФАЗ\n"
                f"Выполняются одновременно: {', '.join(contract['group_phases'])}\n"
                f"Отчёт по этой группе присылается ОДНИМ сообщением.\n"
            )
        else:
            contract = (
                ctx["current_contract"]
                if target_phase.code == self.current_phase
                else self._build_current_contract(target_phase)
            )
            parallel_banner = ""

        workflow_lines = [
            f"- {item['code']}: {item['name']} [{item['status']}]"
            for item in ctx["workflow_path"]
        ]
        instructions = contract["instructions"] or ["Нет отдельных инструкций — следуй описанию фазы и обязательным проверкам."]
        checks = contract["required_checks"] or ["Нет явных checks."]
        evidence = contract["required_evidence"] or ["Нет явных evidence items."]
        report_lines = [f"- {key}: {value}" for key, value in ctx["report_template"].items()]
        cli_actor = ctx.get("cli_actor") or self._cli_actor()

        delegated = ""
        if contract.get("delegate_agent"):
            delegated = (
                f"\nДелегировано агенту: {contract['delegate_agent']}"
                + (f" | toolsets: {', '.join(contract['delegate_toolsets'])}" if contract.get("delegate_toolsets") else "")
            )

        return (
            f"Task: {self.task_key}\n"
            f"Repo: {self.repo or '-'}\n"
            f"Workflow: {ctx['workflow_name'] or '-'}\n"
            f"Current phase: {target_phase.code} — {target_phase.name}\n"
            f"Исполнитель CLI: {cli_actor['description']}\n"
            f"CLI entrypoint: {cli_actor['entrypoint']}\n\n"
            f"Полный путь workflow:\n" + "\n".join(workflow_lines) + "\n\n"
            f"Контракт текущей фазы:\n"
            f"- Описание: {contract['description'] or '-'}\n"
            f"- Тип выполнения: {contract['execution_type']}\n"
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

        # ── Parallel group handling ──────────────────────────────────────
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
                rollback_phase = self.phase_map.get(rollback_target) if rollback_target else None
            else:
                rollback_target = None
                rollback_phase = None
            # Non-pass on parallel group: do NOT advance next_phase, stay on group
            if verdict != "pass":
                next_phase = None
                next_phase_name = None
        else:
            next_phase, next_phase_name = self._get_next_phase(phase.code)
            rollback_target = phase.rollback_target if verdict == "rollback" else None
            rollback_phase = self.phase_map.get(rollback_target) if rollback_target else None

        # Build fresh snapshot (not cached) for this evaluation before transition
        context_snapshot = self.get_full_context(use_cache=False)

        if is_parallel:
            result = self._build_parallel_result(
                group=group,
                verdict=verdict,
                covered=covered,
                missing=missing,
                blockers=blockers,
                next_phase=next_phase,
                next_phase_name=next_phase_name,
                rollback_target=rollback_target,
            )
        else:
            result = self._build_result(
                phase=phase,
                verdict=verdict,
                covered=covered,
                missing=missing,
                blockers=blockers,
                next_phase=next_phase if verdict == "pass" else rollback_target if verdict == "rollback" else None,
                next_phase_name=next_phase_name if verdict == "pass" else rollback_phase.name if rollback_phase else None,
                rollback_target=rollback_target,
            )

        if is_parallel:
            self._record_parallel_transition(group, verdict, next_phase)
        else:
            self._record_transition(phase, verdict, next_phase, rollback_target)

        self.task = self.db.get_task(self.task["id"]) or self.task
        self.current_phase = self._resolve_current_phase()
        self.db.create_supervisor_run(
            {
                "task_id": self.task["id"],
                "phase_id": group[0].code if is_parallel else phase.code,
                "verdict": verdict,
                "report": report,
                "covered": covered,
                "missing": missing,
                "blockers": blockers,
                "next_phase_id": next_phase if verdict == "pass" and next_phase else None,
                "rollback_phase_id": rollback_target,
                "context_snapshot": context_snapshot,
                "response": result,
            }
        )
        return result


def format_result(result: dict) -> str:
    """Преобразует evaluate-result в человекочитаемый CLI-вывод."""
    verdict = result.get("verdict", "UNKNOWN")
    phase_name = result.get("phase_name", result.get("phase", "-"))
    covered = result.get("covered", [])
    missing = result.get("missing", [])
    blockers = result.get("blockers", [])
    next_phase = result.get("next_phase")
    next_phase_name = result.get("next_phase_name")
    rollback_target = result.get("rollback_target")
    message = result.get("message", "")
    is_parallel = "Parallel group" in phase_name

    lines: list[str] = []

    # ── Заголовок вердикта ───────────────────────────────────────────
    if verdict == "PASS":
        header = f"✅ Фаза \"{phase_name}\" принята."
        if next_phase_name:
            header += f" Переход к: {next_phase_name}"
        elif is_parallel:
            header += " Переход к следующей фазе."
        lines.append(header)
    elif verdict == "PARTIAL":
        lines.append(f"⚠️ Фаза \"{phase_name}\" частично выполнена.")
    elif verdict == "BLOCKED":
        lines.append(f"🔴 Фаза \"{phase_name}\" заблокирована.")
    elif verdict == "ROLLBACK":
        lines.append(f"⬅️ Фаза \"{phase_name}\" отклонена — требуется rollback.")
    elif verdict == "DELEGATE":
        lines.append(f"📤 Фаза \"{phase_name}\" делегирована.")
    else:
        lines.append(f"❓ Фаза \"{phase_name}\" — статус: {verdict}")

    lines.append("")

    # ── Закрытые пункты ──────────────────────────────────────────────
    if covered:
        lines.append("Закрытые пункты:")
        for item in covered:
            lines.append(f"  ✓ {item}")
        lines.append("")

    # ── Пробелы ──────────────────────────────────────────────────────
    if missing:
        lines.append("Не закрытые пункты:")
        for item in missing:
            lines.append(f"  ✗ {item}")
        lines.append("")

    # ── Блокеры ──────────────────────────────────────────────────────
    if blockers:
        lines.append("Блокеры:")
        for item in blockers:
            lines.append(f"  🔴 {item}")
        lines.append("")

    # ── Следующий шаг ────────────────────────────────────────────────
    if verdict == "PASS":
        if next_phase:
            lines.append(f"Следующая фаза: {next_phase} — {next_phase_name or '—'}")
        else:
            lines.append("🎉 Все фазы пройдены. Workflow завершён.")
    elif verdict == "PARTIAL":
        lines.append("Оставайся на текущей фазе. Доделай недостающие пункты и пришли отчёт.")
    elif verdict == "BLOCKED":
        lines.append("Фаза заблокирована. Устрани блокеры и пришли новый отчёт.")
    elif verdict == "ROLLBACK":
        if rollback_target:
            lines.append(f"Roll back к фазе: {rollback_target}")
        else:
            lines.append("Roll back — возврат к предыдущей фазе.")
    elif verdict == "DELEGATE":
        lines.append("Ожидаю завершения делегированной работы. Пришли отчёт когда готово.")

    # ── Сообщение от evaluate ──────────────────────────────────────
    if message and message not in lines[-1] if lines else True:
        lines.append("")
        lines.append(f"💡 {message}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Public wrappers / CLI compatibility
# ═══════════════════════════════════════════════════════════════════════


def evaluate_report(task_key: str, report: str, repo: Optional[str] = None) -> dict:
    engine = WizardEngine(task_key, repo)
    return engine.evaluate(report)


def evaluate_report_formatted(task_key: str, report: str, repo: Optional[str] = None) -> str:
    """CLI shortcut — возвращает человекочитаемый результат."""
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
