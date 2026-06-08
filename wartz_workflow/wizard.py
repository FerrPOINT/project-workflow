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
    "заблок",
    "не могу",
    "ошиб",
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

    def _check_coverage(self, report: str, checklist: list[str]) -> tuple[list[str], list[str]]:
        normalized_report = self._normalize_text(report)
        covered: list[str] = []
        missing: list[str] = []
        for item in checklist:
            normalized_item = self._normalize_text(item)
            keywords = self._extract_keywords(item)
            keyword_hits = sum(1 for keyword in keywords if keyword in normalized_report)
            exact_match = normalized_item and normalized_item in normalized_report
            enough_keywords = False
            if keywords:
                threshold = min(len(keywords), 2) if len(keywords) > 1 else 1
                enough_keywords = keyword_hits >= threshold
            if exact_match or enough_keywords:
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

    # ── Public API ───────────────────────────────────────────────────

    def get_phase_prompt(self, phase_id: Optional[str] = None) -> str:
        target_phase = self.phase_map.get(phase_id or self.current_phase)
        if not target_phase:
            return f"Фаза {phase_id or self.current_phase} не найдена в workflow."

        ctx = self.get_full_context()
        contract = ctx["current_contract"] if target_phase.code == self.current_phase else self._build_current_contract(target_phase)
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
        if contract["delegate_agent"]:
            delegated = (
                f"\nДелегировано агенту: {contract['delegate_agent']}"
                + (f" | toolsets: {', '.join(contract['delegate_toolsets'])}" if contract["delegate_toolsets"] else "")
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
            f"- Параллельно с: {contract['parallel_with'] or '-'}\n"
            f"- Rollback target: {contract['rollback_target'] or '-'}\n"
            f"- Next recommendation: {contract['next_recommendation'] or '-'}"
            f"{delegated}\n\n"
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

        checklist = self._build_checklist(phase)
        covered, missing = self._check_coverage(report, checklist)
        blockers = self._extract_blockers(report)
        verdict = self._determine_verdict(phase, covered, missing, blockers, report)
        next_phase, next_phase_name = self._get_next_phase(phase.code)
        rollback_target = phase.rollback_target if verdict == "rollback" else None
        rollback_phase = self.phase_map.get(rollback_target) if rollback_target else None
        # Build fresh snapshot (not cached) for this evaluation before transition
        context_snapshot = self.get_full_context(use_cache=False)

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
        self._record_transition(phase, verdict, next_phase, rollback_target)
        self.task = self.db.get_task(self.task["id"]) or self.task
        self.current_phase = self._resolve_current_phase()
        self.db.create_supervisor_run(
            {
                "task_id": self.task["id"],
                "phase_id": phase.code,
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


# ═══════════════════════════════════════════════════════════════════════
# Public wrappers / CLI compatibility
# ═══════════════════════════════════════════════════════════════════════


def evaluate_report(task_key: str, report: str, repo: Optional[str] = None) -> dict:
    engine = WizardEngine(task_key, repo)
    return engine.evaluate(report)


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
