"""Workflow Wizard — conversational interface for phase-by-phase execution.

Usage:
    hrflow wizard TASK-123
    hrflow wizard TASK-123 --repo /path/to/repo

The wizard loads the current phase from state, asks questions derived from
phases.yaml checks/instructions, accumulates evidence, and advances on PASS.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Iterator, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich import box

from . import state, schema, phases, engine

console = Console()

PASS_ICON = "[green]✅[/green]"
FAIL_ICON = "[red]❌[/red]"
WARN_ICON = "[yellow]⚠️[/yellow]"
BLOCK_ICON = "[red]🔴[/red]"


# ── Data Models ─────────────────────────────────────────────────────────

@dataclass
class PhaseQuestion:
    """Один вопрос для пользователя в рамках фазы."""
    text: str
    question_type: str = "confirm"  # confirm | choice | text
    options: List[str] = field(default_factory=lambda: ["y", "n", "auto", "skip", "?"])
    default: str = "n"
    hint: Optional[str] = None
    auto_command: Optional[str] = None  # команда для авто-выполнения
    is_blocker: bool = False


# ── Wizard Engine ───────────────────────────────────────────────────────

class WizardEngine:
    """State machine — фаза → вопросы → evidence → gate → следующая фаза."""

    def __init__(self, jira_key: str, repo: Optional[str] = None):
        self.jira_key = jira_key
        self.repo = repo or state.find_repo(jira_key) or "/opt/dev/hr-recruiter/recruiter-front"
        self.task_state = state.load_state(self.repo, jira_key) or {}
        self.current_phase = self.task_state.get("current_phase", "-1")
        self.conversation_log: List[dict] = []
        self.evidence_accumulator: dict[str, List[dict]] = {}

        # Загрузить все фазы
        self.all_phases = schema.load_phases()
        self.phase_map = {p.id: p for p in self.all_phases}

    # ── Public API ──────────────────────────────────────────────────────

    def run(self) -> None:
        """Главный цикл wizard."""
        self._show_banner()

        while True:
            phase = self.phase_map.get(self.current_phase)
            if phase is None:
                # Попробовать найти как numeric
                phase = self._resolve_phase(self.current_phase)

            if phase is None:
                console.print("[green]✅ Все фазы завершены или phase ID не найден.[/green]")
                break

            result = self._run_phase(phase)

            if result == "QUIT":
                console.print("\n[dim]👋 Wizard сохранил состояние. Продолжи позже с:[/dim]")
                console.print(f"  [bold]hrflow wizard {self.jira_key}[/bold]\n")
                break
            elif result == "ROLLBACK":
                self._handle_rollback(phase)
            elif result == "PASS":
                if not self._advance_phase(phase):
                    break
            elif result == "FAIL":
                if not self._handle_fail(phase):
                    break

    # ── Display ─────────────────────────────────────────────────────────

    def _show_banner(self) -> None:
        task_id = self.task_state.get("task_id", "??")
        sprint = self.task_state.get("sprint", "??")
        repo_name = self.repo.split("/")[-1] if "/" in self.repo else self.repo

        console.print(Panel(
            f"[bold]🧙 Workflow Wizard[/bold]  v3.0\n"
            f"Task: [cyan]{self.jira_key}[/cyan] | Branch: [yellow]{task_id}[/yellow]\n"
            f"Repo: [dim]{repo_name}[/dim] | Sprint: [dim]{sprint}[/dim]\n"
            f"[dim]Commands: y/n/auto/skip/? | 'q' to quit[/dim]",
            title="WARTZ",
            border_style="cyan",
        ))

    def _show_phase_header(self, phase: schema.Phase) -> None:
        """Показать заголовок фазы."""
        icon = self._phase_icon(phase.id)

        console.print(f"\n{'━' * 54}")
        console.print(f"{icon} [bold]Phase {phase.id} — {phase.name}[/bold]")
        console.print(f"[dim]{phase.description}[/dim]")

        if phase.is_blocker:
            console.print(f"{BLOCK_ICON} [red]BLOCKER — FAIL останавливает workflow[/red]")
        if phase.is_delegated:
            console.print("[cyan]🤖 Эта фаза делегируется (async)[/cyan]")
        if phase.min_time_min:
            console.print(f"[dim]⏱️ Минимальное время: {phase.min_time_min} min[/dim]")

        # Показать параллельные фазы если есть
        parallels = engine.get_parallel_phases(phase.id)
        if parallels:
            console.print(f"[yellow]🔄 Параллельно:[/yellow] {', '.join(parallels)}")

        console.print("━" * 54)

    def _phase_icon(self, phase_id: str) -> str:
        """Emoji по номеру фазы."""
        if phase_id.startswith(("-", "0")):
            return "🚀"
        if phase_id.startswith("1"):
            return "🔍"
        if phase_id.startswith(("2", "3")):
            return "📋"
        if phase_id.startswith("4"):
            return "💻"
        if phase_id.startswith("5"):
            return "✅"
        if phase_id.startswith("6"):
            return "💾"
        if phase_id.startswith("7"):
            return "👁️"
        if phase_id.startswith("8"):
            return "🏁"
        return "📈"

    # ── Phase Execution ─────────────────────────────────────────────────

    def _run_phase(self, phase: schema.Phase) -> str:
        """Выполнить одну фазу: вопросы → evidence → gate.

        Возвращает: PASS | FAIL | ROLLBACK | QUIT
        """
        self._show_phase_header(phase)

        # Сгенерировать вопросы на основе checks + instructions
        questions = self._generate_questions(phase)

        for q in questions:
            answer = self._ask_question(q)

            self.conversation_log.append({
                "phase": phase.id,
                "question": q.text,
                "answer": answer,
            })

            if answer in ("q", "quit"):
                self._save_wizard_state(phase.id)
                return "QUIT"

            if answer == "rollback":
                return "ROLLBACK"

            if answer == "skip":
                console.print(f"{WARN_ICON} [yellow]Пропущено без evidence[/yellow]")
                self._accumulate_evidence(phase.id, q.text, "skipped", None)
                continue

            if answer in ("y", "yes"):
                self._accumulate_evidence(phase.id, q.text, "confirmed", q.auto_command)
                continue

            if answer == "n":
                # Если blocker — спросить что делать
                if q.is_blocker or phase.is_blocker:
                    action = self._prompt_on_fail(phase)
                    if action == "retry":
                        continue
                    elif action == "rollback":
                        return "ROLLBACK"
                    elif action == "escalate":
                        console.print("[purple]🆘 Эскалировано к человеку[/purple]")
                        return "FAIL"
                    else:
                        return "QUIT"
                else:
                    console.print(f"{WARN_ICON} [yellow]Продолжаем без этого[/yellow]")
                    self._accumulate_evidence(phase.id, q.text, "failed_optional", None)

        # Gate evaluation
        if not self._evaluate_gate(phase):
            return "FAIL"

        return "PASS"

    def _generate_questions(self, phase: schema.Phase) -> List[PhaseQuestion]:
        """Сгенерировать вопросы из checks и instructions фазы."""
        questions: List[PhaseQuestion] = []

        # Из checks (первичные проверки)
        for check in phase.checks:
            q = PhaseQuestion(
                text=check.description,
                question_type="confirm",
                options=["y", "n", "auto", "skip", "?"],
                default="n",
                auto_command=check.command,
                is_blocker=not check.optional,
            )
            if check.optional:
                q.options.append("skip")
            questions.append(q)

        # Из instructions (до 3 ключевых)
        for inst in phase.instructions[:3]:
            q = PhaseQuestion(
                text=inst.step,
                question_type="confirm",
                options=["y", "n", "?"],
                default="n",
                hint=inst.example,
            )
            questions.append(q)

        # Gate question (если blocker или есть gate_after)
        if phase.is_blocker or phase.gate_after:
            q = PhaseQuestion(
                text=f"Gate {phase.gate_after or 'BLOCKER'}: всё проверено?",
                question_type="choice",
                options=["y", "r", "e"],
                default="n",
                is_blocker=True,
            )
            questions.append(q)

        return questions

    # ── User Interaction ────────────────────────────────────────────────

    def _ask_question(self, q: PhaseQuestion) -> str:
        """Задать один вопрос с поддержкой help/auto."""
        options_str = "/".join(q.options)

        console.print(f"\n❓ {q.text}")
        if q.hint:
            console.print(f"   [dim]💡 {q.hint}[/dim]")

        while True:
            try:
                answer = Prompt.ask(
                    f"[dim][{options_str}][/dim]",
                    default=q.default,
                )
            except (EOFError, KeyboardInterrupt):
                return "q"

            answer = answer.strip().lower()

            if answer in ("?", "help", "h"):
                self._print_question_help(q)
                continue

            if answer in ("auto", "a"):
                return self._run_auto(q)

            # Разрешить короткие формы
            if answer in ("y", "yes"):
                return "y"
            if answer in ("n", "no"):
                return "n"
            if answer == "skip":
                return "skip"
            if answer == "rollback":
                return "rollback"
            if answer == "escalate":
                return "escalate"
            if answer in ("q", "quit"):
                return "q"

            # Проверить на полный match
            if answer in [o.lower() for o in q.options]:
                return answer

            console.print(f"[red]Неизвестно. Варианты: {options_str} | ? для помощи[/red]")

    def _print_question_help(self, q: PhaseQuestion) -> None:
        """Показать help для текущего вопроса."""
        helptext = """[bold]Команды:[/bold]
  [bold]y[/bold]      — Да, выполнено / согласен
  [bold]n[/bold]      — Нет, не выполнено
  [bold]auto[/bold]  — Автоматически проверить (запустить команду)
  [bold]skip[/bold]  — Пропустить (warning, но продолжить)
  [bold]?[/bold]      — Показать эту справку"""
        console.print(helptext)
        if q.hint:
            console.print(f"\n[dim]💡 Подсказка: {q.hint}[/dim]")
        if q.auto_command:
            console.print(f"\n[dim]▶️ Auto-команда: {q.auto_command}[/dim]")

    def _run_auto(self, q: PhaseQuestion) -> str:
        """Автоматически выполнить команду из check."""
        if not q.auto_command:
            console.print(f"{WARN_ICON} [yellow]Нет auto-команды для этого шага[/yellow]")
            return "n"

        # Заменить плейсхолдеры
        cmd = q.auto_command
        cmd = cmd.replace("{jira_key}", self.jira_key)
        if self.repo:
            cmd = cmd.replace("{repo}", self.repo)

        console.print(f"[dim]▶️ {cmd}[/dim]")
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30
            )
            stdout_preview = result.stdout.strip()[:300]
            if result.returncode == 0:
                console.print(f"{PASS_ICON} [green]Auto-check PASSED[/green]")
                if stdout_preview:
                    console.print(f"[dim]{stdout_preview}[/dim]")
                return "y"
            else:
                stderr_preview = result.stderr.strip()[:300]
                console.print(f"{FAIL_ICON} [red]Auto-check FAILED[/red]")
                console.print(f"[dim]{stderr_preview}[/dim]")
                return "n"
        except subprocess.TimeoutExpired:
            console.print(f"{FAIL_ICON} [red]Timeout (30s)[/red]")
            return "n"
        except Exception as e:
            console.print(f"{FAIL_ICON} [red]Error: {e}[/red]")
            return "n"

    def _prompt_on_fail(self, phase: schema.Phase) -> str:
        """Спросить что делать при gate FAIL."""
        console.print(f"\n{BLOCK_ICON} [bold red]Gate BLOCKED[/bold red]")
        console.print("[dim]Что делаем?[/dim]")
        console.print("  [bold]r[/bold] — Retry (попробовать ещё раз)")
        console.print("  [bold]b[/bold] — Rollback (откат к предыдущей фазе)")
        console.print("  [bold]e[/bold] — Escalate (эскалация к человеку)")
        console.print("  [bold]q[/bold] — Quit (сохранить и выйти)")

        choice = Prompt.ask("[r/b/e/q]", default="r")
        return choice.lower().strip()

    # ── Evidence & State ──────────────────────────────────────────────

    def _accumulate_evidence(
        self, phase_id: str, question: str, answer: str, command: Optional[str]
    ) -> None:
        """Накопить evidence для фазы."""
        entry = {
            "question": question,
            "answer": answer,
            "command": command,
            "timestamp": _now(),
        }
        self.evidence_accumulator.setdefault(phase_id, []).append(entry)

        # Auto-save в state (append mode)
        evidence_text = f"{question}: {answer}"
        if command:
            evidence_text += f" (cmd: {command})"
        state.mark_phase_complete(self.repo, self.jira_key, phase_id, evidence_text)

    def _evaluate_gate(self, phase: schema.Phase) -> bool:
        """Оценить gate — все ли evidence собраны."""
        collected = self.evidence_accumulator.get(phase.id, [])
        if not collected:
            console.print(f"{WARN_ICON} [yellow]Нет evidence для Phase {phase.id}[/yellow]")
            return not phase.is_blocker  # Не-blocker можно пройти без evidence

        # Показать summary
        console.print(f"\n[dim]📎 Evidence собрано: {len(collected)} шт.[/dim]")
        for i, ev in enumerate(collected[:5], 1):
            icon = PASS_ICON if ev["answer"] in ("y", "confirmed") else WARN_ICON
            console.print(f"   {icon} {ev['question'][:50]}")

        return True

    def _save_wizard_state(self, stopped_phase: str) -> None:
        """Сохранить состояние wizard (для continue later)."""
        wizard_state = {
            "jira_key": self.jira_key,
            "repo": self.repo,
            "current_phase": stopped_phase,
            "conversation_log": self.conversation_log[-20:],  # last 20 entries
            "evidence_accumulator": self.evidence_accumulator,
            "updated_at": _now(),
        }
        # Save alongside task state
        import json
        from pathlib import Path
        state_dir = Path(f"~/.wartz-workflow/state").expanduser()
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(state_dir / f"{self.jira_key}.wizard.json", "w") as f:
            json.dump(wizard_state, f, indent=2, ensure_ascii=False)

    # ── Phase Transitions ───────────────────────────────────────────────

    def _advance_phase(self, phase: schema.Phase) -> bool:
        """Перейти к следующей фазе."""
        next_p = phases.get_next_phase(phase.id)

        if not next_p:
            console.print(f"\n{PASS_ICON} [bold green]Phase {phase.id} — последняя. Workflow завершён![/bold green]")
            return False

        # Переключить state
        self.current_phase = next_p
        state.save_state(self.repo, self.jira_key, "", "", next_p)

        # Загрузить следующую фазу для показа
        next_phase_obj = self.phase_map.get(next_p)
        if next_phase_obj:
            delegate_hint = ""
            if next_phase_obj.is_delegated and next_phase_obj.delegate:
                d = next_phase_obj.delegate
                delegate_hint = f"\n[cyan]🤖 Эта фаза делегируется: {d.agent}[/cyan]"

            console.print(f"\n[green]▶️ Переход к Phase {next_p}: {next_phase_obj.name}[/green]")
            if delegate_hint:
                console.print(delegate_hint)

        console.print(f"[dim]Нажми Enter чтобы продолжить, или 'q' чтобы выйти[/dim]")
        try:
            cont = input()
            if cont.strip().lower() == "q":
                self._save_wizard_state(next_p)
                console.print("[dim]Сохранено. Продолжи позже: hrflow wizard {self.jira_key}[/dim]")
                return False
        except (EOFError, KeyboardInterrupt):
            return False

        return True

    def _handle_rollback(self, phase: schema.Phase) -> None:
        """Откат к rollback_target."""
        target = phase.rollback_target
        if not target:
            console.print(f"{FAIL_ICON} [red]У Phase {phase.id} нет rollback_target[/red]")
            return

        console.print(f"\n[yellow]🔄 Rollback: {phase.id} → {target}[/yellow]")
        self.current_phase = target
        state.save_state(self.repo, self.jira_key, "", "", target)

    def _handle_fail(self, phase: schema.Phase) -> bool:
        """Обработка FAIL — спросить retry/escalate/abort."""
        console.print(f"\n{BLOCK_ICON} [bold red]Phase {phase.id} FAILED[/bold red]")
        action = self._prompt_on_fail(phase)

        if action == "retry":
            return True  # Перезапустить текущую фазу
        elif action == "rollback" and phase.rollback_target:
            self._handle_rollback(phase)
            return True
        elif action == "escalate":
            console.print("[purple]🆘 Задача эскалирована к wartzcto[/purple]")
            return False
        else:
            self._save_wizard_state(phase.id)
            return False

    def _resolve_phase(self, phase_id: str) -> Optional[schema.Phase]:
        """ fuzzy resolve phase ID (например, "3" → "3.0")."""
        for p in self.all_phases:
            if p.id == phase_id or p.id.startswith(phase_id + "."):
                return p
        return None


# ── Helpers ───────────────────────────────────────────────────────────

def _now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"


# ── Entry Point ───────────────────────────────────────────────────────

def main(jira_key: str, repo: Optional[str] = None) -> None:
    wizard = WizardEngine(jira_key, repo)
    wizard.run()
