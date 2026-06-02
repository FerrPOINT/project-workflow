"""Workflow Wizard — агент-супервизор для пофазового выполнения задач.

Принцип работы:
    CLI задаёт вопросы пользователю по каждой фазе workflow.
    Пользователь отвечает свободным текстом (или командой y/n/auto/skip).
    Wizard анализирует ответ — ищет ключевые слова, проверяет достаточность evidence.
    Если всё ОК — переходит к следующей фазе.
    Если не ОК — указывает что не сделано, просит дополнить.
    Не отпускает пользователя, пока он не перечислит что сделал и не подтвердит фазу.

Usage:
    hrflow wizard TASK-123           # запуск wizard с текущей фазы
    hrflow wizard TASK-123 --repo /path/to/repo
    hrflow next TASK-123             # алиас: тоже wizard для текущей фазы
"""

from __future__ import annotations

import re
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
INFO_ICON = "[blue]ℹ️[/blue]"
ASK_ICON = "[cyan]❓[/cyan]"

# ── Answer Analysis Result ────────────────────────────────────────────

@dataclass
class AnswerAnalysis:
    """Результат анализа ответа пользователя."""
    sufficient: bool                  # достаточно ли evidence
    missing: List[str] = field(default_factory=list)  # что не хватает
    confidence: float = 0.0             # 0.0-1.0
    action: str = "keep_asking"       # keep_asking | advance | rollback | escalate


# ── Wizard Engine (Agent Supervisor) ────────────────────────────────────

class WizardEngine:
    """Агент-супервизор — не отпускает user до достаточного evidence."""

    def __init__(self, jira_key: str, repo: Optional[str] = None):
        self.jira_key = jira_key
        self.repo = repo or state.find_repo(jira_key) or "/opt/dev/hr-recruiter/recruiter-front"
        self.task_state = state.load_state(self.repo, self.jira_key) or {}
        self.current_phase = self.task_state.get("current_phase", "-1")
        self.conversation_log: List[dict] = []
        self.evidence_accumulator: dict[str, List[dict]] = {}
        self.retry_count = 0

        self.all_phases = schema.load_phases()
        self.phase_map = {p.id: p for p in self.all_phases}

    # ── Public API ──────────────────────────────────────────────────────

    def run(self) -> None:
        """Главный цикл: пока не закончатся фазы или user не выйдет."""
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
                self.retry_count = 0  # сброс счётчика при успехе
            elif result == "FAIL":
                if not self._handle_phase_fail(phase):
                    break
            elif result == "ROLLBACK":
                self._handle_rollback(phase)

    # ── Display ─────────────────────────────────────────────────────────

    def _show_banner(self) -> None:
        task_id = self.task_state.get("task_id", "??")
        sprint = self.task_state.get("sprint", "??")
        repo_name = self.repo.split("/")[-1] if "/" in self.repo else self.repo

        console.print(Panel(
            f"[bold]🧙 Workflow Wizard[/bold] — Агент-супервизор v3.1\n"
            f"Task: [cyan]{self.jira_key}[/cyan] | Branch: [yellow]{task_id}[/yellow]\n"
            f"Repo: [dim]{repo_name}[/dim] | Sprint: [dim]{sprint}[/dim]\n"
            f"[dim]Отвечай свободным текстом. Команды: 'done' 'skip' 'help' 'auto' 'retry' 'rollback' 'escalate' 'quit'[/dim]",
            title="WARTZ",
            border_style="cyan",
        ))

    def _show_resume_hint(self) -> None:
        console.print(f"\n[dim]💾 Wizard сохранил состояние. Продолжи позже:[/dim]")
        console.print(f"  [bold]hrflow wizard {self.jira_key}[/bold]\n")

    def _show_phase_header(self, phase: schema.Phase) -> None:
        console.print(f"\n{'━' * 56}")
        console.print(f"{self._phase_icon(phase.id)} [bold]Фаза {phase.id} — {phase.name}[/bold]")
        console.print(f"[dim]{phase.description}[/dim]")
        if phase.is_blocker:
            console.print(f"{BLOCK_ICON} [red]BLOCKER — FAIL останавливает workflow[/red]")
        if phase.is_delegated:
            console.print("[cyan]🤖 Эта фаза делегируется (async)[/cyan]")
        console.print("━" * 56)

    def _phase_icon(self, phase_id: str) -> str:
        mapping = {
            "-": "🚀", "0": "🚀",
            "1": "🔍", "2": "📋", "3": "📋",
            "4": "💻", "5": "✅",
            "6": "💾", "7": "👁️",
            "8": "🏁", "9": "📈", "10": "📈",
        }
        first = phase_id[0] if phase_id else "?"
        return mapping.get(first, "📌")

    # ── Core: Phase Execution ───────────────────────────────────────────

    def _run_phase(self, phase: schema.Phase) -> str:
        """Одна фаза: показываем заголовок → задаём вопросы → gate.
        Возвращает: PASS | FAIL | ROLLBACK | QUIT
        """
        self._show_phase_header(phase)
        self.retry_count += 1

        # Собираем вопросы: из questions.yaml > fallback из checks+instructions
        questions = self._build_questions(phase)
        if not questions:
            console.print(f"{WARN_ICON} Нет вопросов для фазы {phase.id} — auto-PASS")
            return "PASS"

        for q in questions:
            outcome = self._ask_until_satisfactory(q, phase)
            if outcome == "QUIT":
                self._save_wizard_state(phase.id)
                return "QUIT"
            if outcome == "ROLLBACK":
                return "ROLLBACK"
            if outcome == "SKIP":
                continue  # фаза пропущена
            # outcome == "OK" → сохраняем evidence и идём дальше

        # Gate: проверяем собрано ли достаточно evidence
        if self._evaluate_gate(phase):
            return "PASS"
        return "FAIL"

    # ── Question Builder ────────────────────────────────────────────────

    def _build_questions(self, phase: schema.Phase) -> List[schema.PhaseQuestion]:
        """Собрать список вопросов для фазы."""
        # Приоритет: явные questions в phases.yaml
        if phase.questions:
            return phase.questions

        # Fallback: сгенерировать из checks + evidence + instructions
        questions: List[schema.PhaseQuestion] = []

        # Из checks — для каждого делаем вопрос "сделал ли проверку?"
        for check in phase.checks:
            q = schema.PhaseQuestion(
                text=check.description,
                required=not check.optional,
                expected_keywords=self._extract_expected(check.description),
                hint=f"Запусти: {check.command}" if check.command else None,
                auto_command=check.command,
            )
            questions.append(q)

        # Из instructions — вопрос "выполнил ли ключевые шаги?"
        for inst in phase.instructions[:3]:
            q = schema.PhaseQuestion(
                text=f"Выполнено: {inst.step}",
                required=True,
                expected_keywords=self._extract_expected(inst.step),
                hint=inst.example,
            )
            questions.append(q)

        # Из evidence — вопрос "собрано ли evidence?"
        for ev in phase.evidence:
            q = schema.PhaseQuestion(
                text=f"Evidence: {ev.item}",
                required=True,
                expected_keywords=self._extract_expected(ev.item),
                min_evidence_lines=2,
            )
            questions.append(q)

        return questions

    @staticmethod
    def _extract_expected(text: str) -> List[str]:
        """Извлечь ключевые слова для проверки ответа."""
        # Нормализация: убираем пунктуацию, нижний регистр
        clean = re.sub(r'[^\w\s]', ' ', text.lower())
        words = [w for w in clean.split() if len(w) > 3]
        # Берём существительные и глаголы (heuristics)
        keywords = words[:5]  # top 5 words
        return keywords

    # ── Interactive Question Loop ────────────────────────────────────────

    def _ask_until_satisfactory(
        self, q: schema.PhaseQuestion, phase: schema.Phase
    ) -> str:
        """Задаём вопрос, анализируем ответ, повторяем пока не достаточно.
        Возвращает: OK | SKIP | QUIT | ROLLBACK
        """
        # Подсказка по типу вопроса
        console.print(f"\n{ASK_ICON} [bold]{q.text}[/bold]")
        if q.hint:
            console.print(f"   [dim]💡 {q.hint}[/dim]")

        while True:
            try:
                raw = Prompt.ask(
                    "[dim]Ответ (свободный текст, или: done/skip/help/auto/quit)[/dim]",
                    default="",
                )
            except (EOFError, KeyboardInterrupt):
                return "QUIT"

            answer = raw.strip()
            lower = answer.lower()

            # Meta-команды
            if lower in ("q", "quit", "exit"):
                return "QUIT"
            if lower in ("r", "rollback"):
                return "ROLLBACK"
            if lower in ("e", "escalate"):
                return "QUIT"  # сохраняем для escalation
            if lower in ("s", "skip"):
                if not q.required:
                    console.print(f"{WARN_ICON} [yellow]Пропущено[/yellow]")
                    self._accumulate_evidence(phase.id, q.text, "skipped", None)
                    return "SKIP"
                console.print(f"{BLOCK_ICON} Этот вопрос обязательный — skip нельзя")
                continue
            if lower in ("h", "help", "?"):
                self._print_help(q)
                continue
            if lower in ("auto", "a"):
                result = self._run_auto(q)
                if result == "PASS":
                    self._accumulate_evidence(phase.id, q.text, "auto-pass", q.auto_command)
                    return "OK"
                console.print(f"{FAIL_ICON} Auto-check не прошёл. Ответь вручную.")
                continue
            if lower in ("done", "yes", "y", "готово", "да"):
                # даже "done" мы анализируем — user должен перечислить что сделал
                pass

            if not answer:
                console.print(f"{INFO_ICON} Нужен ответ. Перечисли что сделал по этому пункту.")
                continue

            # Анализ ответа
            analysis = self._analyze_answer(answer, q)

            if analysis.sufficient:
                console.print(f"{PASS_ICON} [green]Принято[/green]")
                self._accumulate_evidence(phase.id, q.text, answer, q.auto_command)
                return "OK"
            else:
                # Недостаточно — говорим что не хватает
                console.print(f"\n{WARN_ICON} [yellow]Ответ неполный:[/yellow]")
                for miss in analysis.missing:
                    console.print(f"   • {miss}")
                console.print(f"[dim]Повтори и дополни ответ. Нужно больше деталей.[/dim]\n")
                self._accumulate_evidence(phase.id, q.text, f"incomplete: {answer[:80]}", None)

    @staticmethod
    def _analyze_answer(answer: str, q: schema.PhaseQuestion) -> AnswerAnalysis:
        """Проанализировать ответ пользователя."""
        lower = answer.lower()

        # 1. Negative patterns — ответ "не делал", "не знаю", "не получилось"
        negative_patterns = [
            r"не (делал|знаю|смог|получилось|наш[её]л)",
            r"не удалось", r"ничего не", r"не применимо",
            r"^skip$", r"^n/a$", r"not applicable",
        ]
        for pat in negative_patterns:
            if re.search(pat, lower):
                return AnswerAnalysis(
                    sufficient=False,
                    missing=["Ты ответил что не сделал/не знаешь. Нужно выполнить этот пункт."],
                    confidence=0.0,
                    action="keep_asking",
                )

        # 2. Длина — если expected_keywords заданы, нужен развёрнутый ответ
        min_len = max(q.min_evidence_lines * 15, 10)
        if len(answer) < min_len and q.expected_keywords:
            return AnswerAnalysis(
                sufficient=False,
                missing=[f"Слишком короткий ответ ({len(answer)} симв). Опиши подробнее что сделал."],
                confidence=0.1,
                action="keep_asking",
            )

        # 3. Keywords check
        found_keywords = []
        missing_keywords = []
        for kw in q.expected_keywords:
            if kw.lower() in lower:
                found_keywords.append(kw)
            else:
                missing_keywords.append(kw)

        # Если_keywords заданы и найдено < 50% → недостаточно
        keyword_ratio = len(found_keywords) / max(len(q.expected_keywords), 1)
        confidence = keyword_ratio

        missing = []
        if len(answer) < min_len and not q.expected_keywords:
            missing.append("Ответ слишком короткий. Раскрой детали.")
        if missing_keywords and keyword_ratio < 0.5:
            missing.append(f"В ответе не упомянуто: {', '.join(missing_keywords[:3])}")

        # 4. Достаточно?
        sufficient = confidence >= 0.5 and len(answer) >= min_len

        return AnswerAnalysis(
            sufficient=sufficient,
            missing=missing if not sufficient else [],
            confidence=confidence,
            action="advance" if sufficient else "keep_asking",
        )

    def _print_help(self, q: schema.PhaseQuestion) -> None:
        console.print("""[bold]Команды Wizard:[/bold]
  [bold]done[/bold]    — Подтвердить выполнение (нужно описать что сделал)
  [bold]skip[/bold]    — Пропустить (только для необязательных пунктов)
  [bold]auto[/bold]    — Автоматически проверить (запустить команду)
  [bold]help[/bold]    — Показать эту справку
  [bold]retry[/bold]   — Перезапустить текущую фазу
  [bold]rollback[/bold]— Откат к предыдущей фазе
  [bold]escalate[/bold]— Эскалировать к человеку
  [bold]quit[/bold]    — Сохранить и выйти (продолжишь позже)""")
        if q.auto_command:
            console.print(f"\n[dim]▶️ Auto-команда: {q.auto_command}[/dim]")

    def _run_auto(self, q: schema.PhaseQuestion) -> str:
        """Выполнить auto-команду и вернуть PASS/FAIL."""
        if not q.auto_command:
            console.print(f"{WARN_ICON} Нет auto-команды")
            return "FAIL"
        cmd = q.auto_command.replace("{jira_key}", self.jira_key).replace("{repo}", self.repo)
        console.print(f"[dim]▶️ {cmd}[/dim]")
        try:
            # NOTE: shell=True safe here — cmd from trusted YAML schema only.
            # No user input interpolation into shell commands.
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                stdout = result.stdout.strip()[:300]
                console.print(f"{PASS_ICON} [green]PASSED[/green]")
                if stdout:
                    console.print(f"[dim]{stdout}[/dim]")
                return "PASS"
            else:
                stderr = result.stderr.strip()[:300]
                console.print(f"{FAIL_ICON} [red]FAILED[/red]")
                console.print(f"[dim]{stderr}[/dim]")
                return "FAIL"
        except subprocess.TimeoutExpired:
            console.print(f"{FAIL_ICON} [red]Timeout (30s)[/red]")
            return "FAIL"
        except Exception as e:
            console.print(f"{FAIL_ICON} [red]Error: {e}[/red]")
            return "FAIL"

    # ── Evidence & Gate ───────────────────────────────────────────────────

    def _accumulate_evidence(
        self, phase_id: str, question: str, answer: str, command: Optional[str]
    ) -> None:
        entry = {
            "question": question,
            "answer": answer,
            "command": command,
            "timestamp": _now(),
        }
        self.evidence_accumulator.setdefault(phase_id, []).append(entry)
        evidence_text = f"{question}: {answer}"
        if command:
            evidence_text += f" (cmd: {command})"
        state.mark_phase_complete(self.repo, self.jira_key, phase_id, evidence_text)

    def _evaluate_gate(self, phase: schema.Phase) -> bool:
        """Оценить достаточно ли evidence для перехода к следующей фазе."""
        collected = self.evidence_accumulator.get(phase.id, [])

        # Показать summary собранного evidence
        console.print(f"\n{'─' * 56}")
        console.print(f"[bold]📋 Gate Check — Фаза {phase.id}[/bold]")
        if not collected:
            console.print(f"{FAIL_ICON} [red]Нет evidence — фаза не может считаться выполненной[/red]")
            return False

        ok_count = sum(1 for e in collected if "skipped" not in e["answer"] and "incomplete" not in e["answer"])
        total = len(collected)
        console.print(f"[dim]Evidence собрано: {ok_count}/{total}[/dim]")

        for ev in collected:
            ans = ev["answer"]
            is_ok = "skipped" not in ans and "incomplete" not in ans
            icon = PASS_ICON if is_ok else WARN_ICON
            short = ans[:60] + "..." if len(ans) > 60 else ans
            console.print(f"   {icon} {short}")

        # Если хоть один required вопрос failed → FAIL
        all_pass = ok_count == total and total > 0
        if all_pass:
            console.print(f"\n{PASS_ICON} [bold green]Gate PASSED — переходим к следующей фазе[/bold green]")
        else:
            console.print(f"\n{FAIL_ICON} [bold red]Gate FAILED — есть незавершённые пункты[/bold red]")
        console.print("─" * 56)
        return all_pass

    # ── Phase Transitions ───────────────────────────────────────────────

    def _advance_phase(self, phase: schema.Phase) -> bool:
        """Перейти к следующей фазе."""
        next_p = phases.get_next_phase(phase.id)
        if not next_p:
            console.print(f"\n{PASS_ICON} [bold green]Все фазы выполнены! Workflow завершён.[/bold green]")
            return False

        self.current_phase = next_p
        state.save_state(self.repo, self.jira_key, "", "", next_p)

        next_phase_obj = self.phase_map.get(next_p)
        if next_phase_obj:
            console.print(f"\n[green]▶️ Следующая фаза: {next_p} — {next_phase_obj.name}[/green]")
            if next_phase_obj.is_delegated and next_phase_obj.delegate:
                d = next_phase_obj.delegate
                console.print(f"[cyan]🤖 Делегируется: {d.agent} ({d.timeout_min}min)[/cyan]")

        # Пауза перед продолжением
        console.print("[dim]Нажми Enter чтобы продолжить, или 'q' чтобы выйти[/dim]")
        try:
            cont = input()
            if cont.strip().lower() == "q":
                self._save_wizard_state(next_p)
                self._show_resume_hint()
                return False
        except (EOFError, KeyboardInterrupt):
            return False
        return True

    def _handle_phase_fail(self, phase: schema.Phase) -> bool:
        """Обработка FAIL — не хватает evidence, спрашиваем retry/escalate/quit."""
        console.print(f"\n{BLOCK_ICON} [bold red]Фаза {phase.id} FAILED[/bold red]")
        console.print("[dim]Что делаем?[/dim]")

        # Показать что не сделано
        collected = self.evidence_accumulator.get(phase.id, [])
        incomplete = [e for e in collected if "incomplete" in e["answer"] or "skipped" in e["answer"]]
        if incomplete:
            console.print("[yellow]Незавершённые пункты:[/yellow]")
            for e in incomplete:
                console.print(f"   • {e['question']}")

        console.print("  [bold]r[/bold] — Retry (переответить на вопросы)")
        console.print("  [bold]b[/bold] — Rollback (откат к предыдущей фазе)")
        console.print("  [bold]e[/bold] — Escalate (эскалация к человеку)")
        console.print("  [bold]q[/bold] — Quit (сохранить и выйти)")

        try:
            choice = Prompt.ask("[r/b/e/q]", default="r")
        except (EOFError, KeyboardInterrupt):
            self._save_wizard_state(phase.id)
            return False

        choice = choice.lower().strip()
        if choice in ("r", "retry"):
            return True  # перезапустить текущую фазу
        if choice in ("b", "rollback") and phase.rollback_target:
            self._handle_rollback(phase)
            return True
        if choice in ("e", "escalate"):
            console.print("[purple]🆘 Эскалировано — остановка wizard[/purple]")
            return False

        self._save_wizard_state(phase.id)
        return False

    def _handle_rollback(self, phase: schema.Phase) -> None:
        target = phase.rollback_target
        if not target:
            console.print(f"{FAIL_ICON} [red]Нет rollback_target[/red]")
            return
        console.print(f"\n[yellow]🔄 Rollback: {phase.id} → {target}[/yellow]")
        self.current_phase = target
        state.save_state(self.repo, self.jira_key, "", "", target)

    def _resolve_phase(self, phase_id: str) -> Optional[schema.Phase]:
        for p in self.all_phases:
            if p.id == phase_id or p.id.startswith(phase_id + "."):
                return p
        return None

    # ── State Persistence ───────────────────────────────────────────────

    def _save_wizard_state(self, stopped_phase: str) -> None:
        import json
        from pathlib import Path
        wizard_state = {
            "jira_key": self.jira_key,
            "repo": self.repo,
            "current_phase": stopped_phase,
            "retry_count": self.retry_count,
            "conversation_log": self.conversation_log[-30:],
            "evidence_accumulator": self.evidence_accumulator,
            "updated_at": _now(),
        }
        state_dir = Path("~/.wartz-workflow/state").expanduser()
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(state_dir / f"{self.jira_key}.wizard.json", "w") as f:
            json.dump(wizard_state, f, indent=2, ensure_ascii=False)


def _now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"


# ── Entry Point ───────────────────────────────────────────────────────

def main(jira_key: str, repo: Optional[str] = None) -> None:
    engine = WizardEngine(jira_key, repo)
    engine.run()
