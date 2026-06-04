"""Workflow Wizard — conversational gate evaluator.

Все данные из БД (phases, instructions, checks, evidence). Нет хардкода.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple, Dict, Any

from .db import WorkflowDB
from . import models, conversation as convo
from .schema import load_phases_from_db, get_phase_from_db


PASS_ICON = "✅"
FAIL_ICON = "❌"
WARN_ICON = "⚠️"
INFO_ICON = "ℹ️"


class WizardEngine:
    """Conversational gate: агент присылает отчёт → wizard возвращает verdict."""

    def __init__(self, task_key: str, repo: Optional[str] = None):
        self.task_key = task_key
        self.repo = repo
        self.task_id = task_key

        history_phase = convo.get_last_phase(self.task_id)
        self.current_phase = history_phase or "-1"

        self._wdb = WorkflowDB()
        self._wdb.init()
        self.all_phases = load_phases_from_db(self._wdb)
        self.phase_map = {p.code: p for p in self.all_phases}

    # ═══════════════════════════════════════════════════════════════════
    #  PUBLIC API
    # ═══════════════════════════════════════════════════════════════════

    def evaluate(self, report: str) -> dict:
        """Основной метод: принять отчёт агента, вернуть verdict."""
        phase = self.phase_map.get(self.current_phase)
        if phase is None:
            phase = self._resolve_phase(self.current_phase)
        if phase is None:
            return {
                "verdict": "PASS",
                "phase": self.current_phase,
                "phase_name": "Complete",
                "message": "Все фазы выполнены.",
                "covered": [], "missing": [],
                "next_phase": None, "next_phase_name": None,
            }

        checklist = self._build_checklist(phase)
        covered, missing = self._check_coverage(report, checklist)

        if not missing:
            next_phase, next_name = self._get_next_phase(phase)
            self._record_transition(phase.code, next_phase or "COMPLETE")

            msg = self._build_pass_message(phase, covered, next_phase, next_name)
            return {
                "verdict": "PASS",
                "phase": phase.code,
                "phase_name": phase.name,
                "covered": covered,
                "missing": [],
                "next_phase": next_phase,
                "next_phase_name": next_name,
                "message": msg,
            }
        else:
            msg = self._build_fail_message(phase, missing)
            convo.add_wizard_answer(self.task_id, self.task_key, phase.code, f"fail: {missing}", ok=False)
            return {
                "verdict": "FAIL",
                "phase": phase.code,
                "phase_name": phase.name,
                "covered": covered,
                "missing": missing,
                "next_phase": None,
                "next_phase_name": None,
                "message": msg,
            }

    def get_phase_prompt(self, phase_id: Optional[str] = None) -> str:
        """Сформировать промпт для агента: инструкции фазы."""
        pid = phase_id or self.current_phase
        phase = self.phase_map.get(pid)
        if phase is None:
            phase = self._resolve_phase(pid)
        if phase is None:
            return "Все фазы выполнены. Задача завершена."

        lines = [
            f"🎯 Фаза {phase.code} — {phase.name}",
            f"📋 {phase.description}",
            "",
            "❗ Обязательно выполнить:",
        ]
        checklist = self._build_checklist(phase)
        for idx, item in enumerate(checklist, 1):
            lines.append(f"   {idx}. {item}")

        if phase.is_blocker:
            lines.extend(["", "🔴 Это BLOCKER фаза — пропустить нельзя."])
        if phase.is_delegated:
            lines.extend(["", f"🤖 Делегировано агенту: {phase.delegate.agent if phase.delegate else '—'}"])

        lines.extend([
            "",
            f"Когда выполнишь — пришли отчёт: 'wartz-workflow step --task {self.task_key} --report \"...\"'",
        ])

        return "\n".join(lines)

    def get_full_context(self) -> dict:
        """Собрать полный контекст для агента."""
        all_messages = convo.get_messages(self.task_id, limit=500)
        transitions = [m for m in all_messages if m.tags == "transition"]
        completed_phase_ids = list(dict.fromkeys(
            m.phase_id for m in transitions if m.phase_id and m.phase_id != "COMPLETE"
        ))

        current = self.current_phase
        if current == "COMPLETE" or current not in self.phase_map:
            current = completed_phase_ids[-1] if completed_phase_ids else "-1"

        all_phases = []
        for p in self.all_phases:
            all_phases.append({
                "id": p.id,
                "code": p.code,
                "name": p.name,
                "description": p.description,
                "min_time_min": p.min_time_min,
                "is_blocker": p.is_blocker,
                "is_delegated": p.is_delegated,
                "is_critic": p.is_critic,
                "execution_type": getattr(p, "execution_type", "sync"),
                "parallel_with": getattr(p, "parallel_with", None),
                "instructions": [{"step": i.step, "tool": getattr(i, "tool", None), "execution_type": getattr(i, "execution_type", "sync")} for i in p.instructions],
                "checks": [{"description": c.description, "optional": getattr(c, "optional", False)} for c in p.checks],
                "evidence": [{"item": e.item} for e in p.evidence],
            })

        phase_history = []
        for m in all_messages[-50:]:
            phase_history.append({
                "role": m.role,
                "phase_id": m.phase_id,
                "tags": m.tags,
                "content_preview": m.content[:200],
                "created_at": m.created_at,
            })

        current_phase_name = ""
        if current in self.phase_map:
            current_phase_name = self.phase_map[current].name
        else:
            resolved = self._resolve_phase(current)
            current_phase_name = resolved.name if resolved else current

        return {
            "task_key": self.task_key,
            "repo": self.repo,
            "current_phase": self.current_phase,
            "current_phase_name": current_phase_name,
            "completed_phases": completed_phase_ids,
            "all_phases": all_phases,
            "phase_history": phase_history,
            "total_phases": len(all_phases),
            "completed_count": len(completed_phase_ids),
        }
    # ═══════════════════════════════════════════════════════════════════
    #  INTERNAL
    # ═══════════════════════════════════════════════════════════════════

    def _build_checklist(self, phase: models.Phase) -> List[str]:
        """Собрать уникальные проверки фазы из БД (checks + instructions + evidence)."""
        items: List[str] = []
        for check in phase.checks:
            items.append(check.description)
        for inst in phase.instructions:
            items.append(inst.step)
        for ev in phase.evidence:
            items.append(ev.item)
        seen = set()
        result = []
        for i in items:
            k = i.strip().lower()
            if k and k not in seen:
                seen.add(k)
                result.append(i.strip())
        return result

    def _check_coverage(self, report: str, checklist: List[str]) -> Tuple[List[str], List[str]]:
        """Проверить покрытие чеклиста отчётом."""
        ans_lower = report.lower()
        covered: List[str] = []
        missing: List[str] = []
        for item in checklist:
            words = self._extract_keywords(item)
            if any(w in ans_lower for w in words):
                covered.append(item)
            else:
                missing.append(item)
        return covered, missing

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        """Извлечь значимые слова для matching."""
        words = re.findall(r'[a-zа-яё0-9]+', text.lower())
        return [w for w in words if len(w) > 3][:4]

    def _get_next_phase(self, current_phase: models.Phase) -> Tuple[Optional[str], Optional[str]]:
        """Получить след фазу."""
        from . import phases as phases_mod
        next_p = phases_mod.get_next_phase(current_phase.code)
        if next_p:
            next_obj = self.phase_map.get(next_p)
            return next_p, next_obj.name if next_obj else next_p
        return None, None

    def _record_transition(self, from_phase: str, to_phase: str) -> None:
        """Сохранить переход в историю."""
        convo.add_phase_transition(self.task_id, self.task_key, from_phase, to_phase)
        self.current_phase = to_phase

    def _build_pass_message(
        self,
        phase: models.Phase,
        covered: List[str],
        next_phase: Optional[str],
        next_name: Optional[str],
    ) -> str:
        lines = [
            f"{PASS_ICON} Отлично! Фаза {phase.code} ({phase.name}) пройдена.",
            f"   Покрыто пунктов: {len(covered)}",
        ]
        if next_phase and next_name:
            lines.extend(["", f"▶️ Переходим к фазе {next_phase} — {next_name}"])
        else:
            lines.extend(["", f"{PASS_ICON} Все фазы выполнены!"])
        return "\n".join(lines)

    def _build_fail_message(self, phase: models.Phase, missing: List[str]) -> str:
        lines = [
            f"{FAIL_ICON} Фаза {phase.code} ({phase.name}) — требуются доработки.",
            "",
            f"Не выполнено пунктов: {len(missing)}",
        ]
        for item in missing[:5]:
            lines.append(f"   • {item}")
        if len(missing) > 5:
            lines.append(f"   ... и ещё {len(missing) - 5}")
        lines.extend([
            "",
            f"Доработай и пришли новый отчёт: 'wartz-workflow step --task {self.task_key} --report \"...\"'",
        ])
        return "\n".join(lines)

    def _resolve_phase(self, phase_code: str) -> Optional[models.Phase]:
        """Find phase by code (exact or prefix)."""
        for p in self.all_phases:
            if p.code == phase_code or p.code.startswith(phase_code + "."):
                return p
        return None


# ═══════════════════════════════════════════════════════════════════════
#  CLI ENTRY POINTS
# ═══════════════════════════════════════════════════════════════════════

def evaluate_report(task_key: str, report: str, repo: Optional[str] = None) -> dict:
    """CLI/API entry: агент прислал отчёт → получить verdict."""
    engine = WizardEngine(task_key, repo)
    return engine.evaluate(report)


def get_phase_instructions(task_key: str, phase_id: Optional[str] = None, repo: Optional[str] = None) -> str:
    """CLI/API entry: получить инструкции для текущей (или указанной) фазы."""
    engine = WizardEngine(task_key, repo)
    return engine.get_phase_prompt(phase_id)


def main(task_key: str, report: Optional[str] = None, repo: Optional[str] = None) -> None:
    """CLI entry: wartz-workflow step --task TASK-123 [--report "..."].

    Без --report: показать инструкции текущей фазы.
    С --report: оценить отчёт.
    """
    import json, sys
    if report:
        result = evaluate_report(task_key, report, repo)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["verdict"] == "PASS" else 1)
    else:
        print(get_phase_instructions(task_key, repo=repo))
