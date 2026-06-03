"""Workflow Wizard v5.0 — conversational gate evaluator.

Принцип работы:
  1. Агент присылает отчёт: "я сделал X, Y, Z"
  2. Wizard проверяет покрытие по чеклисту текущей фазы
  3. Возвращает verdict:
     - PASS → переход на след фазу + новые инструкции + repeatable задания
     - FAIL → список что не сделано + требование доработать
  4. Повторяющиеся задания (repeatable_checks) — выполняются каждый ход

No интерактивных Prompt. Только evaluate(report) → verdict.
"""

from __future__ import annotations

import re
import subprocess
from typing import List, Optional, Tuple, Dict, Any

from . import schema, conversation as convo


# ── Icons ─────────────────────────────────────────────────────────────
PASS_ICON = "✅"
FAIL_ICON = "❌"
WARN_ICON = "⚠️"
INFO_ICON = "ℹ️"


# ── Repeatable checks (каждый ход) ───────────────────────────────────
REPEATABLE_CHECKS = [
    "Залогировать работу по фазе в файл info/",
    "Обновить progress.json текущей фазой",
    "Добавить запись в changelog.md",
]


class WizardEngine:
    """Conversational gate: агент присылает отчёт → wizard возвращает verdict."""

    def __init__(self, jira_key: str, repo: Optional[str] = None):
        self.jira_key = jira_key
        self.repo = repo
        self.task_id = jira_key  # Simplified; could be resolved from state

        # Load current phase from history or default to -1
        history_phase = convo.get_last_phase(self.task_id)
        self.current_phase = history_phase or "-1"

        self.all_phases = schema.load_phases()
        self.phase_map = {p.id: p for p in self.all_phases}

    # ═══════════════════════════════════════════════════════════════════
    #  PUBLIC API
    # ═══════════════════════════════════════════════════════════════════

    def evaluate(self, report: str) -> dict:
        """Основной метод: принять отчёт агента, вернуть verdict.

        Returns:
            {
                "verdict": "PASS" | "FAIL",
                "phase": "0.6",
                "phase_name": "Researcher #1",
                "covered": ["проверил пуллреквесты", "воспроизвёл баги"],
                "missing": ["запустить параллельного агента"],
                "repeatable": ["залогировать фазу"],
                "next_phase": "1" | None,   # только при PASS
                "next_phase_name": "Preflight",
                "message": "Отлично, переходим... / Не хватает...",
            }
        """
        phase = self.phase_map.get(self.current_phase)
        if phase is None:
            phase = self._resolve_phase(self.current_phase)
        if phase is None:
            return {
                "verdict": "PASS",
                "phase": self.current_phase,
                "phase_name": "Complete",
                "message": "Все фазы выполнены.",
                "covered": [], "missing": [], "repeatable": [],
                "next_phase": None, "next_phase_name": None,
            }

        # Build checklist from phase requirements
        checklist = self._build_checklist(phase)
        covered, missing = self._check_coverage(report, checklist)

        # Evaluate repeatable checks (always present)
        repeatable_status = self._check_repeatable(report)

        if not missing and all(r["ok"] for r in repeatable_status):
            # PASS — advance to next phase
            next_phase, next_name = self._get_next_phase(phase)
            self._record_transition(phase.id, next_phase or "COMPLETE")

            msg = self._build_pass_message(phase, covered, repeatable_status, next_phase, next_name)
            return {
                "verdict": "PASS",
                "phase": phase.id,
                "phase_name": phase.name,
                "covered": covered,
                "missing": [],
                "repeatable": [r["item"] for r in repeatable_status],
                "next_phase": next_phase,
                "next_phase_name": next_name,
                "message": msg,
            }
        else:
            # FAIL — return missing items + repeatable failures
            msg = self._build_fail_message(phase, missing, repeatable_status)
            convo.add_wizard_answer(self.task_id, self.jira_key, phase.id, f"fail: {missing}", ok=False)
            return {
                "verdict": "FAIL",
                "phase": phase.id,
                "phase_name": phase.name,
                "covered": covered,
                "missing": missing,
                "repeatable": [r["item"] for r in repeatable_status if not r["ok"]],
                "next_phase": None,
                "next_phase_name": None,
                "message": msg,
            }

    def get_phase_prompt(self, phase_id: Optional[str] = None) -> str:
        """Сформировать промпт для агента: инструкции фазы + repeatable задания.

        Используется когда агент впервые обращается к фазе.
        """
        pid = phase_id or self.current_phase
        phase = self.phase_map.get(pid)
        if phase is None:
            phase = self._resolve_phase(pid)
        if phase is None:
            return "Все фазы выполнены. Задача завершена."

        lines = [
            f"🎯 Фаза {phase.id} — {phase.name}",
            f"📋 {phase.description}",
            "",
            "❗ Обязательно выполнить:",
        ]
        checklist = self._build_checklist(phase)
        for idx, item in enumerate(checklist, 1):
            lines.append(f"   {idx}. {item}")

        lines.extend([
            "",
            "🔄 Повторяющиеся задания (каждый ход):",
        ])
        for idx, item in enumerate(REPEATABLE_CHECKS, 1):
            lines.append(f"   {idx}. {item}")

        if phase.is_blocker:
            lines.extend(["", "🔴 Это BLOCKER фаза — пропустить нельзя."])
        if phase.is_delegated:
            lines.extend(["", f"🤖 Делегировано агенту: {phase.delegate.agent if phase.delegate else '—'}"])

        lines.extend([
            "",
            f"Когда выполнишь — пришли отчёт: 'hrflow wizard {self.jira_key}' с описанием что сделал.",
        ])

        return "\n".join(lines)

    def get_full_context(self) -> dict:
        """Собрать полный контекст для агента-визарда.

        Возвращает структуру с:
        - выполненными фазами
        - текущей фазой
        - ВСЕМИ фазами + их инструкции / чеки / evidence
        - историей переходов и отчётов
        - статусом повторяющихся заданий
        """
        # Completed phases — из conversation history transitions
        all_messages = convo.get_messages(self.task_id, limit=500)
        transitions = [m for m in all_messages if m.tags == "transition"]
        completed_phase_ids = list(dict.fromkeys(
            m.phase_id for m in transitions if m.phase_id and m.phase_id != "COMPLETE"
        ))

        # Current phase
        current = self.current_phase
        # If current says COMPLETE → pick last real phase or "-1"
        if current == "COMPLETE" or current not in self.phase_map:
            if completed_phase_ids:
                current = completed_phase_ids[-1]
            else:
                current = "-1"

        # Build all phases summary
        all_phases = []
        for p in self.all_phases:
            all_phases.append({
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "min_time_min": p.min_time_min,
                "is_blocker": p.is_blocker,
                "is_delegated": p.is_delegated,
                "is_critic": p.is_critic,
                "execution_mode": getattr(p, "execution_mode", "sync"),
                "parallel_with": getattr(p, "parallel_with", None),
                "skills": p.skills,
                "instructions": [{"step": i.step, "tool": getattr(i, "tool", None), "execution_type": getattr(i, "execution_type", "sync")} for i in p.instructions],
                "checks": [{"type": c.type, "description": c.description, "optional": getattr(c, "optional", False)} for c in p.checks],
                "evidence": [{"item": e.item, "validator": getattr(e, "validator", None)} for e in p.evidence],
            })

        # Phase history digest (lightweight)
        phase_history = []
        for m in all_messages[-50:]:
            phase_history.append({
                "role": m.role,
                "phase_id": m.phase_id,
                "tags": m.tags,
                "content_preview": m.content[:200],
                "created_at": m.created_at,
            })

        # Repeatable checks status against last user note
        last_user_note = ""
        for m in reversed(all_messages):
            if m.role == "user":
                last_user_note = m.content
                break
        repeatable_status = self._check_repeatable(last_user_note)

        current_phase_name = ""
        if current in self.phase_map:
            current_phase_name = self.phase_map[current].name
        else:
            resolved = self._resolve_phase(current)
            current_phase_name = resolved.name if resolved else current

        return {
            "jira_key": self.jira_key,
            "repo": self.repo,
            "current_phase": current,
            "current_phase_name": current_phase_name,
            "completed_phases": completed_phase_ids,
            "all_phases": all_phases,
            "phase_history": phase_history,
            "repeatable_checks": [
                {"item": r["item"], "ok": r["ok"]} for r in repeatable_status
            ],
            "total_phases": len(all_phases),
            "completed_count": len(completed_phase_ids),
        }

    # ═══════════════════════════════════════════════════════════════════
    #  INTERNAL
    # ═══════════════════════════════════════════════════════════════════

    def _build_checklist(self, phase: schema.Phase) -> List[str]:
        """Собрать уникальные проверки фазы (без повторяющихся)."""
        items: List[str] = []
        for check in phase.checks:
            items.append(check.description)
        for inst in phase.instructions:
            items.append(inst.step)
        for ev in phase.evidence:
            items.append(ev.item)
        # Deduplicate
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

    def _check_repeatable(self, report: str) -> List[Dict[str, Any]]:
        """Проверить повторяющиеся задания с гибким matching (стемминг)."""
        ans_lower = report.lower()
        results = []
        for item in REPEATABLE_CHECKS:
            ok = self._match_repeatable(item, ans_lower)
            results.append({"item": item, "ok": ok})
        return results

    def _match_repeatable(self, item: str, text_lower: str) -> bool:
        """Гибкое сопоставление с учётом русских окончаний."""
        # Core concepts for each repeatable item
        concepts = {
            "логир": ["логир", "log"],           # залогировать, залогировал
            "progress": ["progress", "прогресс"],
            "changelog": ["changelog", "чейнджлог"],
        }
        for key, variants in concepts.items():
            if key in item.lower():
                return any(v in text_lower for v in variants)
        # Fallback to keyword matching
        words = self._extract_keywords(item)
        return any(w in text_lower for w in words)

    def _get_next_phase(self, current_phase: schema.Phase) -> Tuple[Optional[str], Optional[str]]:
        """Получить след фазу."""
        from . import phases as phases_mod
        next_p = phases_mod.get_next_phase(current_phase.id)
        if next_p:
            next_obj = self.phase_map.get(next_p)
            return next_p, next_obj.name if next_obj else next_p
        return None, None

    def _record_transition(self, from_phase: str, to_phase: str) -> None:
        """Сохранить переход в историю."""
        convo.add_phase_transition(self.task_id, self.jira_key, from_phase, to_phase)
        self.current_phase = to_phase

    def _build_pass_message(
        self,
        phase: schema.Phase,
        covered: List[str],
        repeatable: List[Dict[str, Any]],
        next_phase: Optional[str],
        next_name: Optional[str],
    ) -> str:
        lines = [
            f"{PASS_ICON} Отлично! Фаза {phase.id} ({phase.name}) пройдена.",
            f"   Покрыто пунктов: {len(covered)}",
        ]
        if next_phase and next_name:
            lines.extend([
                "",
                f"▶️ Переходим к фазе {next_phase} — {next_name}",
            ])
        else:
            lines.extend(["", f"{PASS_ICON} Все фазы выполнены!"])
        return "\n".join(lines)

    def _build_fail_message(
        self,
        phase: schema.Phase,
        missing: List[str],
        repeatable: List[Dict[str, Any]],
    ) -> str:
        lines = [
            f"{FAIL_ICON} Фаза {phase.id} ({phase.name}) — требуются доработки.",
            "",
            f"Не выполнено пунктов: {len(missing)}",
        ]
        for item in missing[:5]:
            lines.append(f"   • {item}")
        if len(missing) > 5:
            lines.append(f"   ... и ещё {len(missing) - 5}")

        failed_repeatable = [r["item"] for r in repeatable if not r["ok"]]
        if failed_repeatable:
            lines.extend(["", "Пропущены повторяющиеся задания:"])
            for item in failed_repeatable:
                lines.append(f"   • {item}")

        lines.extend([
            "",
            f"Доработай и пришли новый отчёт: 'hrflow wizard {self.jira_key}'",
        ])
        return "\n".join(lines)

    def _resolve_phase(self, phase_id: str) -> Optional[schema.Phase]:
        for p in self.all_phases:
            if p.id == phase_id or p.id.startswith(phase_id + "."):
                return p
        return None


# ═══════════════════════════════════════════════════════════════════════
#  CLI ENTRY POINTS
# ═══════════════════════════════════════════════════════════════════════

def evaluate_report(jira_key: str, report: str, repo: Optional[str] = None) -> dict:
    """CLI/API entry: агент прислал отчёт → получить verdict."""
    engine = WizardEngine(jira_key, repo)
    return engine.evaluate(report)


def get_phase_instructions(jira_key: str, phase_id: Optional[str] = None, repo: Optional[str] = None) -> str:
    """CLI/API entry: получить инструкции для текущей (или указанной) фазы."""
    engine = WizardEngine(jira_key, repo)
    return engine.get_phase_prompt(phase_id)


def main(jira_key: str, report: Optional[str] = None, repo: Optional[str] = None) -> None:
    """CLI entry: hrflow wizard TASK-123 [--report "я сделал ..."].

    Без --report: показать инструкции текущей фазы.
    С --report: оценить отчёт.
    """
    import json, sys
    if report:
        result = evaluate_report(jira_key, report, repo)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["verdict"] == "PASS" else 1)
    else:
        print(get_phase_instructions(jira_key, repo=repo))
