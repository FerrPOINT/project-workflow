"""Workflow Wizard v4.1 -- чёткий checklist engine без костылей.

Принцип:
  1. Wizard показывает фазу + список ДЕЙСТВИЙ (чеклист) из phase.checks/instructions/evidence.
  2. Пользователь отвечает свободно: "сделал X и Y".
  3. Wizard сравнивает каждый пункт с ответом: есть ли ключевое слово пункта в ответе?
  4. Все пункты covered -> PASS, показывает что осталось -> повтор.
  5. Обязаловки (changelog, progress, info/) -- через реальные file checks, не keywords.

Никаких regex magic keywords. Чеклист берётся прямо из phase.yaml.
"""

from __future__ import annotations

import subprocess
from typing import List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from . import state, schema, phases, conversation as convo
import json as _json

console = Console()

PASS_ICON = "[green]✅[/green]"
FAIL_ICON = "[red]❌[/red]"
WARN_ICON = "[yellow]⚠️[/yellow]"
INFO_ICON = "[blue]ℹ️[/blue]"
ASK_ICON = "[cyan]❓[/cyan]"
MEMO_ICON = "[magenta]📝[/magenta]"


class WizardEngine:
    """Чёткий checklist wizard: показал пункты -- получил ответ -- проверил покрытие."""

    def __init__(self, jira_key: str, repo: Optional[str] = None):
        self.jira_key = jira_key
        self.repo = repo or state.find_repo(jira_key) or "/opt/dev/hr-recruiter/recruiter-front"
        self.task_state: dict = state.load_state(self.repo, jira_key) or {}
        self.task_id: str = self.task_state.get("task_id", jira_key)

        history_phase = convo.get_last_phase(self.task_id)
        self.current_phase = history_phase or self.task_state.get("current_phase", "-1")

        self.all_phases = schema.load_phases()
        self.phase_map = {p.id: p for p in self.all_phases}

    def run(self) -> None:
        from . import task_validator
        validated = task_validator.validate(self.jira_key)
        if not validated.is_valid:
            console.print(f"[red]❌ Invalid task key '{self.jira_key}': {validated.error_message}[/red]")
            return

        self._show_banner()

        while True:
            phase = self.phase_map.get(self.current_phase)
            if phase is None:
                phase = self._resolve_phase(self.current_phase)
            if phase is None:
                console.print(f"\n{PASS_ICON} [bold green]Все фазы завершены![/bold green]")
                break

            result = self._run_phase(phase)
            if result == "QUIT":
                self._show_resume_hint()
                break
            elif result == "PASS":
                if not self._advance_phase(phase):
                    break
            elif result == "FAIL":
                if not self._handle_fail(phase):
                    break

    # ── Banner ────────────────────────────────────────────────────────

    def _show_banner(self) -> None:
        digest = convo.build_status_digest(self.task_id, self.jira_key, self.current_phase)
        total = digest.get("total_messages", 0)
        transitions = digest.get("transitions_count", 0)

        console.print(Panel(
            f"[bold]🧙 Workflow Wizard[/bold] -- task history v4.1 (checklist engine)\n"
            f"Task: [cyan]{self.jira_key}[/cyan] | ID: {self.task_id}\n"
            f"[dim]История: {total} сообщений | Переходов: {transitions}[/dim]\n"
            f"[dim]Команды: done / skip / help / auto / rollback / quit[/dim]",
            title="WARTZ", border_style="cyan",
        ))

    # ── Phase Runner (core) ──────────────────────────────────────────

    def _run_phase(self, phase: schema.Phase) -> str:
        self._show_phase_header(phase)

        # 1. Собрать чеклист действий
        checklist = self._build_checklist(phase)
        if not checklist:
            console.print(f"{WARN_ICON} Нет действий для этой фазы -- auto PASS")
            return "PASS"

        # 2. Показать чеклист пользователю
        self._show_checklist(checklist)

        # 3. Обязаловки (real file checks)
        self._show_obligatory_checklist()

        # 4. Спросить что сделал
        return self._ask_and_check(checklist, phase)

    def _build_checklist(self, phase: schema.Phase) -> List[str]:
        """Собрать список конкретных действий из фазы."""
        items: List[str] = []
        for check in phase.checks:
            items.append(check.description)
        for inst in phase.instructions[:5]:
            items.append(inst.step)
        for ev in phase.evidence:
            items.append(ev.item)
        # Убрать дубликаты, сохранить порядок
        seen = set()
        result = []
        for i in items:
            k = i.strip().lower()
            if k and k not in seen:
                seen.add(k)
                result.append(i.strip())
        return result

    def _show_checklist(self, items: List[str]) -> None:
        console.print(f"\n[bold]📋 По этой фазе нужно сделать ({len(items)} пунктов):[/bold]")
        for idx, item in enumerate(items, 1):
            console.print(f"   {idx}. {item}")

    def _show_obligatory_checklist(self) -> None:
        """Проверить обязаловки реальными file checks (не keywords)."""
        missing: List[str] = []
        # changelog.md
        changelog_path = f"{self.repo}/info/changelog.md"
        try:
            with open(changelog_path, "r") as f:
                text = f.read()
            if self.jira_key not in text:
                missing.append("📝 changelog.md не содержит записи по этой задаче")
        except FileNotFoundError:
            missing.append("📝 changelog.md не найден")
        # progress.json
        progress_path = f"{self.repo}/progress.json"
        try:
            with open(progress_path, "r") as f:
                data = _json.load(f)
            if self.jira_key not in str(data):
                missing.append("📊 progress.json не обновлялся для этой задачи")
        except (FileNotFoundError, _json.JSONDecodeError):
            missing.append("📊 progress.json не найден или битый")
        # info/
        info_pattern = f"{self.repo}/info/*/*{self.jira_key}*"
        import glob
        if not glob.glob(info_pattern):
            missing.append("📁 info/ -- нет папки задачи")

        if missing:
            console.print(f"\n[bold yellow]Обязаловки (не найдены):[/bold yellow]")
            for m in missing:
                console.print(f"   {m}")

    # ── Ask + Evaluation ────────────────────────────────────────────────

    def _ask_and_check(self, checklist: List[str], phase: schema.Phase) -> str:
        console.print(f"\n{ASK_ICON} [bold]Что сделал по этой фазе? Опиши по пунктам.[/bold]")
        console.print("[dim]Команды: done / skip / auto / rollback / quit / ?[/dim]")

        while True:
            try:
                raw = Prompt.ask("Ответ", default="")
            except (EOFError, KeyboardInterrupt):
                return "QUIT"

            answer = raw.strip()
            lower = answer.lower()

            # Meta commands
            if lower in ("q", "quit"): return "QUIT"
            if lower in ("r", "rollback"): return "ROLLBACK"
            if lower in ("h", "help", "?"):
                self._print_help(checklist)
                continue
            if lower in ("skip", "s"):
                if not phase.is_blocker:
                    console.print(f"{WARN_ICON} Фаза пропущена")
                    convo.add_wizard_answer(self.task_id, self.jira_key, phase.id, "skipped", ok=False)
                    return "PASS"  # skip = pass but without evidence
                console.print(f"{FAIL_ICON} Blocker фазу пропустить нельзя")
                continue
            if lower in ("auto", "a"):
                outcome = self._run_auto_commands(phase)
                if outcome:
                    return "PASS"
                console.print(f"{FAIL_ICON} Auto-check не прошёл. Ответь вручную.")
                continue
            if not answer:
                console.print(f"{INFO_ICON} Опиши что сделал -- например: 'создал файл X, запустил Y'")
                continue

            # Основная логика: проверить покрытие checklist ответом
            done, remaining = self._check_coverage(answer, checklist)

            if not remaining:
                console.print(f"\n{PASS_ICON} [bold green]Все пункты покрыты ({len(done)}/{len(checklist)})[/bold green]")
                convo.add_wizard_answer(self.task_id, self.jira_key, phase.id, f"done: {done}", ok=True)
                return "PASS"
            else:
                console.print(f"\n{WARN_ICON} [yellow]Не хватает пунктов:[/yellow] ({len(done)}/{len(checklist)})")
                for r in remaining[:5]:
                    console.print(f"   • {r}")
                console.print("[dim]Дополни ответ -- что ещё сделал по этим пунктам.[/dim]\n")
                convo.add_wizard_answer(self.task_id, self.jira_key, phase.id, f"partial: {remaining}", ok=False)

    def _check_coverage(self, answer: str, checklist: List[str]) -> Tuple[List[str], List[str]]:
        """Вернуть (done_items, remaining_items).

        Правило: для каждого пункта берём ключевые слова (первые 3 значимых слова > 3 букв),
        если хоть одно есть в ответе -- считаем пункт covered.
        """
        ans_lower = answer.lower()
        done: List[str] = []
        remaining: List[str] = []
        for item in checklist:
            words = self._extract_keywords(item)
            if any(w in ans_lower for w in words):
                done.append(item)
            else:
                remaining.append(item)
        return done, remaining

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        """Извлечь первые 3 значимых слова (>3 букв) из текста пункта."""
        import re
        words = re.findall(r'[a-zа-яё]+', text.lower())
        return [w for w in words if len(w) > 3][:4]

    # ── Auto commands ──────────────────────────────────────────────────

    def _run_auto_commands(self, phase: schema.Phase) -> bool:
        """Выполнить shell commands из checks, вернуть True если хоть один PASS."""
        passed = 0
        for check in phase.checks:
            if check.command:
                cmd = check.command.replace("{jira_key}", self.jira_key).replace("{repo}", self.repo)
                console.print(f"[dim]▶️ {cmd}[/dim]")
                try:
                    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                    if res.returncode == 0:
                        console.print(f"{PASS_ICON} PASS")
                        passed += 1
                    else:
                        console.print(f"{FAIL_ICON} FAIL")
                except (subprocess.TimeoutExpired, Exception) as e:
                    console.print(f"{FAIL_ICON} Error: {e}")
        return passed > 0

    # ── Helpers ─────────────────────────────────────────────────────────

    def _print_help(self, checklist: List[str]) -> None:
        console.print(f"[bold]Команды:[/bold]")
        console.print("  [cyan]done[/cyan] -- подтвердить, описав что сделал")
        console.print("  [cyan]skip[/cyan] -- пропустить (только для non-blocker)")
        console.print("  [cyan]auto[/cyan] -- запустить автопроверки из фазы")
        console.print("  [cyan]rollback[/cyan] -- откат к предыдущей фазе")
        console.print("  [cyan]quit[/cyan] -- сохранить и выйти")
        console.print(f"[bold]Пункты ({len(checklist)}):[/bold]")
        for i, c in enumerate(checklist, 1):
            console.print(f"  {i}. {c}")

    # ── Phase header ────────────────────────────────────────────────────

    def _show_phase_header(self, phase: schema.Phase) -> None:
        icon = self._phase_icon(phase.id)
        console.print(f"\n{'━' * 56}")
        console.print(f"{icon} [bold]Фаза {phase.id} -- {phase.name}[/bold]")
        console.print(f"[dim]{phase.description}[/dim]")
        console.print("━" * 56)

    def _phase_icon(self, phase_id: str) -> str:
        mapping = {"-": "🚀", "0": "🚀", "1": "🔍", "2": "📋", "3": "📋",
                   "4": "💻", "5": "✅", "6": "💾", "7": "👁️", "8": "🏁", "9": "📈", "10": "📈"}
        return mapping.get(phase_id[0] if phase_id else "?", "📌")

    # ── Gate (simplified) ───────────────────────────────────────────────

    def _evaluate_gate(self, phase: schema.Phase) -> bool:
        # Gate теперь проверяется прямо в _check_coverage
        return True

    # ── Phase Transition ──────────────────────────────────────────────

    def _advance_phase(self, phase: schema.Phase) -> bool:
        next_p = phases.get_next_phase(phase.id)
        if not next_p:
            console.print(f"\n{PASS_ICON} [bold green]Все фазы выполнены![/bold green]")
            return False
        convo.add_phase_transition(self.task_id, self.jira_key, phase.id, next_p)
        self.current_phase = next_p
        state.save_state(self.repo, self.jira_key, "", "", next_p)

        next_obj = self.phase_map.get(next_p)
        if next_obj:
            console.print(f"\n[green]▶️ Следующая фаза: {next_p} -- {next_obj.name}[/green]")
        try:
            cont = input("[Enter -- продолжить, q -- выйти] ")
            if cont.strip().lower() == "q":
                self._show_resume_hint()
                return False
        except (EOFError, KeyboardInterrupt):
            return False
        return True

    def _handle_fail(self, phase: schema.Phase) -> bool:
        console.print(f"\n{FAIL_ICON} [bold red]Фаза {phase.id} FAILED[/bold red]")
        console.print("  [bold]r[/bold] -- Retry  [bold]b[/bold] -- Rollback  [bold]q[/bold] -- Quit")
        try:
            choice = Prompt.ask("[r/b/q]", default="r")
        except (EOFError, KeyboardInterrupt):
            return False
        c = choice.lower().strip()
        if c in ("r", "retry"): return True
        if c in ("b", "rollback") and phase.rollback_target:
            convo.add_phase_transition(self.task_id, self.jira_key, phase.id, phase.rollback_target)
            self.current_phase = phase.rollback_target
            state.save_state(self.repo, self.jira_key, "", "", phase.rollback_target)
            return True
        return False

    def _resolve_phase(self, phase_id: str) -> Optional[schema.Phase]:
        for p in self.all_phases:
            if p.id == phase_id or p.id.startswith(phase_id + "."):
                return p
        return None

    def _show_resume_hint(self) -> None:
        console.print(f"\n[dim]💾 История сохранена. Продолжи: hrflow wizard {self.jira_key}[/dim]")


# ── Entry Point ───────────────────────────────────────────────────────

def main(jira_key: str, repo: Optional[str] = None) -> None:
    WizardEngine(jira_key, repo).run()
