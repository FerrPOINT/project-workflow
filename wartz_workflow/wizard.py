"""Workflow Wizard v4.0 — история по номеру задачи, auto-progress от conversation.

Принцип: пользователь пишет `hrflow note TASK-123 "сделал X"`.
Wizard хранит историю в SQLite (conversation.db).
При `hrflow wizard TASK-123` wizard:
  1. Читает историю из conversation.db по task_id
  2. Определяет текущую фазу (из последнего transition или progress.json)
  3. Говорит: "Согласно истории, ты на фазе X. Вот что осталось: ..."
  4. В каждой фазе напоминает про info/, changelog, progress.json
  5. Принимает ответ → анализирует → сохраняет → advance/keep_asking
  6. При advance записывает transition в историю
"""

from __future__ import annotations

import re
import subprocess
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from . import state, schema, phases, conversation as convo

console = Console()

PASS_ICON = "[green]✅[/green]"
FAIL_ICON = "[red]❌[/red]"
WARN_ICON = "[yellow]⚠️[/yellow]"
INFO_ICON = "[blue]ℹ️[/blue]"
ASK_ICON = "[cyan]❓[/cyan]"
MEMO_ICON = "[magenta]📝[/magenta]"


class WizardEngine:
    """История по номеру задачи + smart phase advisor."""

    def __init__(self, jira_key: str, repo: Optional[str] = None):
        self.jira_key = jira_key
        self.repo = repo or state.find_repo(jira_key) or "/opt/dev/hr-recruiter/recruiter-front"
        self.task_state: dict = state.load_state(self.repo, jira_key) or {}
        self.task_id: str = self.task_state.get("task_id", jira_key)

        # Загрузить фазу из истории (приоритет над progress.json)
        history_phase = convo.get_last_phase(self.task_id)
        self.current_phase = history_phase or self.task_state.get("current_phase", "-1")

        self.all_phases = schema.load_phases()
        self.phase_map = {p.id: p for p in self.all_phases}

    # ── Public API ──────────────────────────────────────────────────────

    def run(self) -> None:
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

    # ── Banner ───────────────────────────────────────────────────────────

    def _show_banner(self) -> None:
        digest = convo.build_status_digest(self.task_id, self.jira_key, self.current_phase)
        last = digest.get("last_phase", "??")
        transitions = digest.get("transitions_count", 0)
        total_notes = digest.get("total_messages", 0)

        console.print(Panel(
            f"[bold]🧙 Workflow Wizard[/bold] — task history v4.0\n"
            f"Task: [cyan]{self.jira_key}[/cyan] | ID: [yellow]{self.task_id}[/yellow]\n"
            f"[dim]История: {total_notes} сообщений | Переходов: {transitions}[/dim]\n"
            f"[dim]Команды: done / skip / auto / help / rollback / escalate / quit[/dim]",
            title="WARTZ", border_style="cyan",
        ))
        console.print(f"\n[bold]Текущая фаза: {last}[/bold]")
        if digest.get("latest_notes"):
            console.print("[dim]Последние отчёты:[/dim]")
            for n in digest["latest_notes"][-3:]:
                console.print(f"   {MEMO_ICON} {n}")

    # ── Phase Header + Todo Reminders ────────────────────────────────────

    def _show_phase_header(self, phase: schema.Phase) -> None:
        icon = self._phase_icon(phase.id)
        console.print(f"\n{'━' * 56}")
        console.print(f"{icon} [bold]Фаза {phase.id} — {phase.name}[/bold]")
        console.print(f"[dim]{phase.description}[/dim]")
        console.print("━" * 56)

        # Автоматические напоминания на основе истории
        self._show_missing_repeating_items()

        # Показать что ещё нужно по этой фазе
        missing = self._detect_missing_items(phase)
        if missing:
            console.print(f"\n[yellow]⚠️ По этой фазе ещё не найдено в истории:[/yellow]")
            for m in missing:
                console.print(f"   • {m}")

    def _show_missing_repeating_items(self) -> None:
        """Повторяющиеся вещи: info/, changelog, progress. Проверяем по истории."""
        missing: List[str] = []
        if not convo.check_keyword_in_history(self.task_id, "changelog"):
            missing.append("📝 changelog.md — не было записи")
        if not convo.check_keyword_in_history(self.task_id, "progress"):
            missing.append("📊 progress.json — не обновлялся")
        if not convo.check_keyword_in_history(self.task_id, "info"):
            missing.append("📁 info/ — не упоминалось")
        if not convo.check_keyword_in_history(self.task_id, "requirements"):
            missing.append("📋 requirements.md — не упоминалось")

        if missing:
            console.print("\n[bold yellow]Обязаловки (не найдены в истории):[/bold yellow]")
            for m in missing:
                console.print(f"   {m}")
            console.print("[dim]   Когда выполнишь — отпиши об этом в ответе[/dim]")

    def _phase_icon(self, phase_id: str) -> str:
        mapping = {"-": "🚀", "0": "🚀", "1": "🔍", "2": "📋", "3": "📋",
                   "4": "💻", "5": "✅", "6": "💾", "7": "👁️", "8": "🏁", "9": "📈", "10": "📈"}
        return mapping.get(phase_id[0] if phase_id else "?", "📌")

    # ── Core: Run Phase ──────────────────────────────────────────────────

    def _run_phase(self, phase: schema.Phase) -> str:
        self._show_phase_header(phase)
        questions = self._build_questions(phase)

        if not questions:
            console.print(f"{WARN_ICON} Нет вопросов — auto-PASS")
            return "PASS"

        for q in questions:
            outcome = self._ask_and_analyze(q, phase)
            if outcome in ("QUIT", "ROLLBACK", "SKIP"):
                return outcome
            # outcome OK — продолжаем

        # Gate
        if self._evaluate_gate(phase):
            return "PASS"
        return "FAIL"

    # ── Question Builder ────────────────────────────────────────────────

    def _build_questions(self, phase: schema.Phase) -> List[schema.PhaseQuestion]:
        if phase.questions:
            return phase.questions

        questions: List[schema.PhaseQuestion] = []
        for check in phase.checks:
            questions.append(schema.PhaseQuestion(
                text=check.description,
                required=not check.optional,
                expected_keywords=self._extract_expected(check.description),
                hint=f"Запусти: {check.command}" if check.command else None,
                auto_command=check.command,
            ))
        for inst in phase.instructions[:3]:
            questions.append(schema.PhaseQuestion(
                text=f"Выполнено: {inst.step}",
                required=True,
                expected_keywords=self._extract_expected(inst.step),
                hint=inst.example,
            ))
        for ev in phase.evidence:
            questions.append(schema.PhaseQuestion(
                text=f"Evidence: {ev.item}",
                required=True,
                expected_keywords=self._extract_expected(ev.item),
                min_evidence_lines=2,
            ))
        return questions

    @staticmethod
    def _extract_expected(text: str) -> List[str]:
        clean = re.sub(r'[^\w\s]', ' ', text.lower())
        words = [w for w in clean.split() if len(w) > 3]
        return words[:5]

    # ── Interactive Question ────────────────────────────────────────────

    def _ask_and_analyze(self, q: schema.PhaseQuestion, phase: schema.Phase) -> str:
        console.print(f"\n{ASK_ICON} [bold]{q.text}[/bold]")
        if q.hint:
            console.print(f"   [dim]💡 {q.hint}[/dim]")

        while True:
            try:
                raw = Prompt.ask(
                    "[dim]Ответ (свободный текст, или: done/skip/help/auto/rollback/escalate/quit)[/dim]",
                    default="",
                )
            except (EOFError, KeyboardInterrupt):
                return "QUIT"

            answer = raw.strip()
            lower = answer.lower()

            if lower in ("q", "quit"): return "QUIT"
            if lower in ("r", "rollback"): return "ROLLBACK"
            if lower in ("e", "escalate"): return "QUIT"
            if lower in ("s", "skip"):
                if not q.required:
                    console.print(f"{WARN_ICON} Пропущено")
                    convo.add_wizard_answer(self.task_id, self.jira_key, phase.id, answer, ok=False)
                    return "SKIP"
                console.print(f"{FAIL_ICON} Обязательный вопрос — skip нельзя")
                continue
            if lower in ("h", "help", "?"):
                self._print_help(q)
                continue
            if lower in ("auto", "a"):
                if self._run_auto(q) == "PASS":
                    convo.add_wizard_answer(self.task_id, self.jira_key, phase.id, "auto-pass", ok=True)
                    return "OK"
                console.print(f"{FAIL_ICON} Auto-check не прошёл. Ответь вручную.")
                continue
            if not answer:
                console.print(f"{INFO_ICON} Нужен ответ. Опиши что сделал.")
                continue

            # Анализ
            analysis = self._analyze_answer(answer, q)
            if analysis.sufficient:
                console.print(f"{PASS_ICON} [green]Принято[/green]")
                convo.add_wizard_answer(self.task_id, self.jira_key, phase.id, answer, ok=True)
                return "OK"
            else:
                console.print(f"\n{WARN_ICON} [yellow]Недостаточно:[/yellow]")
                for m in analysis.missing:
                    console.print(f"   • {m}")
                console.print("[dim]Повтори — опиши подробнее что сделал и перечисли факты.[/dim]\n")
                convo.add_wizard_answer(self.task_id, self.jira_key, phase.id, f"incomplete: {answer[:80]}", ok=False)

    def _analyze_answer(self, answer: str, q: schema.PhaseQuestion) -> "AnswerAnalysis":
        """Возвращает namedtuple-like объект (inline для простоты)."""
        lower = answer.lower()

        # 1. Negative patterns
        neg_pats = [r"не (делал|знаю|смог|получилось)", r"не удалось", r"ничего не", r"не применимо"]
        for pat in neg_pats:
            if re.search(pat, lower):
                return _AA(False, ["Ты ответил что не сделал/не знаешь. Нужно выполнить этот пункт."], 0.0)

        # 2. Min length
        min_len = max(q.min_evidence_lines * 15, 10)
        if len(answer) < min_len and q.expected_keywords:
            return _AA(False, [f"Слишком коротко ({len(answer)} симв). Опиши подробнее."], 0.1)

        # 3. Keywords
        found = [kw for kw in q.expected_keywords if kw.lower() in lower]
        ratio = len(found) / max(len(q.expected_keywords), 1)
        missing_kw = [kw for kw in q.expected_keywords if kw.lower() not in lower]

        miss = []
        if missing_kw and ratio < 0.5:
            miss.append(f"Не упомянуто: {', '.join(missing_kw[:3])}")

        sufficient = ratio >= 0.5 and len(answer) >= min_len
        return _AA(sufficient, miss, ratio)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _run_auto(self, q: schema.PhaseQuestion) -> str:
        if not q.auto_command:
            console.print(f"{WARN_ICON} Нет auto-команды")
            return "FAIL"
        cmd = q.auto_command.replace("{jira_key}", self.jira_key).replace("{repo}", self.repo)
        console.print(f"[dim]▶️ {cmd}[/dim]")
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            if res.returncode == 0:
                out = res.stdout.strip()[:300]
                console.print(f"{PASS_ICON} [green]PASSED[/green]")
                if out: console.print(f"[dim]{out}[/dim]")
                return "PASS"
            console.print(f"{FAIL_ICON} [red]FAILED[/red]")
            return "FAIL"
        except Exception:
            console.print(f"{FAIL_ICON} [red]Error[/red]")
            return "FAIL"

    def _print_help(self, q: schema.PhaseQuestion) -> None:
        console.print("""[bold]Команды:[/bold]
  done — подтвердить, описав что сделал
  skip — пропустить (только необязательное)
  auto — автопроверка (командой из фазы)
  rollback — откат к предыдущей фазе
  escalate — эскалация к человеку
  quit — сохранить и выйти""")
        if q.auto_command:
            console.print(f"\n[dim]▶️ Auto: {q.auto_command}[/dim]")

    # ── Detect Missing Items from History ───────────────────────────────

    def _detect_missing_items(self, phase: schema.Phase) -> List[str]:
        """На основе истории — какие evidence/checks ещё не упоминались."""
        missing: List[str] = []
        for ev in phase.evidence:
            kw = ev.item.split()[0].lower() if ev.item else ""
            if not convo.check_keyword_in_history(self.task_id, kw):
                missing.append(ev.item)
        return missing[:3]

    # ── Gate ────────────────────────────────────────────────────────────

    def _evaluate_gate(self, phase: schema.Phase) -> bool:
        msgs = convo.get_messages(self.task_id, phase_id=phase.id, tags="pass")
        incomplete = convo.get_messages(self.task_id, phase_id=phase.id, tags="fail")
        console.print(f"\n[bold]📋 Gate Check — Фаза {phase.id}[/bold]")
        console.print(f"[dim]Прошло / Не прошло: {len(msgs)} / {len(incomplete)}[/dim]")
        if not msgs:
            console.print(f"{FAIL_ICON} [red]Нет прошедших вопросов[/red]")
            return False
        # Упрощённый gate: достаточно чтобы все required questions имели pass
        all_pass = len(incomplete) == 0 or phase.is_blocker is False
        if all_pass:
            console.print(f"\n{PASS_ICON} [bold green]Gate PASSED[/bold green]")
        else:
            console.print(f"\n{FAIL_ICON} [bold red]Gate FAILED[/bold red]")
        return all_pass

    # ── Phase Transition ──────────────────────────────────────────────

    def _advance_phase(self, phase: schema.Phase) -> bool:
        next_p = phases.get_next_phase(phase.id)
        if not next_p:
            console.print(f"\n{PASS_ICON} [bold green]Все фазы выполнены![/bold green]")
            return False

        # Записать transition в историю
        convo.add_phase_transition(self.task_id, self.jira_key, phase.id, next_p)
        self.current_phase = next_p
        state.save_state(self.repo, self.jira_key, "", "", next_p)

        next_obj = self.phase_map.get(next_p)
        if next_obj:
            console.print(f"\n[green]▶️ Следующая фаза: {next_p} — {next_obj.name}[/green]")

        console.print("[dim]Нажми Enter чтобы продолжить, или 'q' чтобы выйти[/dim]")
        try:
            cont = input()
            if cont.strip().lower() == "q":
                self._show_resume_hint()
                return False
        except (EOFError, KeyboardInterrupt):
            return False
        return True

    def _handle_fail(self, phase: schema.Phase) -> bool:
        console.print(f"\n{FAIL_ICON} [bold red]Фаза {phase.id} FAILED[/bold red]")
        console.print("  [bold]r[/bold] — Retry  [bold]b[/bold] — Rollback  [bold]e[/bold] — Escalate  [bold]q[/bold] — Quit")
        try:
            choice = Prompt.ask("[r/b/e/q]", default="r")
        except (EOFError, KeyboardInterrupt):
            return False
        c = choice.lower().strip()
        if c in ("r", "retry"): return True
        if c in ("b", "rollback") and phase.rollback_target:
            convo.add_phase_transition(self.task_id, self.jira_key, phase.id, phase.rollback_target)
            self.current_phase = phase.rollback_target
            state.save_state(self.repo, self.jira_key, "", "", phase.rollback_target)
            return True
        if c in ("e", "escalate"):
            console.print("[purple]🆘 Эскалировано[/purple]")
            return False
        return False

    def _resolve_phase(self, phase_id: str) -> Optional[schema.Phase]:
        for p in self.all_phases:
            if p.id == phase_id or p.id.startswith(phase_id + "."):
                return p
        return None

    def _show_resume_hint(self) -> None:
        console.print(f"\n[dim]💾 История сохранена. Продолжи позже: hrflow wizard {self.jira_key}[/dim]")


# ── Lightweight namedtuple для AnswerAnalysis (inline) ───────────────────

from collections import namedtuple
_AA = namedtuple("_AA", ["sufficient", "missing", "confidence"])


# ── Entry Point ───────────────────────────────────────────────────────

def main(jira_key: str, repo: Optional[str] = None) -> None:
    WizardEngine(jira_key, repo).run()
