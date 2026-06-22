"""Phase Finite State Machine using transitions library.

Formalizes the lifecycle of a single workflow phase:
    pending → in_progress → done
                ↘ blocked
                ↘ rollback
                ↘ delegated
"""
from transitions import Machine

from project_workflow import config


class _FSMModel:
    """Dummy model for transitions Machine."""
    pass


class PhaseFSM:
    """Formalized phase lifecycle state machine."""

    STATES = ["pending", "in_progress", "done", "blocked", "rollback", "delegated"]

    TRANSITIONS = [
        {"trigger": "start", "source": "pending", "dest": "in_progress"},
        {"trigger": "succeed", "source": "in_progress", "dest": "done"},
        {"trigger": "partial_pass", "source": "in_progress", "dest": "in_progress"},
        {"trigger": "block", "source": "in_progress", "dest": "blocked"},
        {"trigger": "rollback", "source": "in_progress", "dest": "rollback"},
        {"trigger": "delegate", "source": "in_progress", "dest": "delegated"},
        {"trigger": "restart", "source": ["blocked", "rollback", "delegated"], "dest": "pending"},
        {"trigger": "resume", "source": ["blocked", "rollback", "delegated"], "dest": "in_progress"},
    ]

    VERDICT_TO_TRIGGER = {
        "pass": "succeed",
        "partial": "partial_pass",
        "blocked": "block",
        "rollback": "rollback",
        "delegate": "delegate",
    }

    def __init__(self, initial: str = "in_progress"):
        self._model = _FSMModel()
        self._model.state = initial
        self._machine = Machine(
            model=self._model,
            states=self.STATES,
            initial=initial,
            transitions=self.TRANSITIONS,
            send_event=False,
        )

    @property
    def state(self) -> str:
        return self._model.state

    def is_terminal(self) -> bool:
        return self.state in {"done", "blocked"}

    def apply_verdict(self, verdict: str) -> str:
        """Apply a wizard verdict and return the new state."""
        trigger = self.VERDICT_TO_TRIGGER.get(verdict)
        if trigger is None:
            return self.state
        try:
            getattr(self._model, trigger)()
        except Exception:
            pass
        return self.state


# ── Phase order & checklist helpers (moved from root phases.py) ─────────────

from typing import List, Optional


def get_next_phase(current_phase: str) -> Optional[str]:
    """Определить следующую фазу по порядку."""
    try:
        idx = config.PHASE_ORDER.index(current_phase)
    except ValueError:
        return None

    if idx + 1 < len(config.PHASE_ORDER):
        return config.PHASE_ORDER[idx + 1]
    return None


def get_phase_checklist_raw(phase_name: str) -> List[str]:
    """Вернуть raw список чеклиста для фазы (для JSON output)."""
    checklists = {
        "-1": ["Прочитать Jira тикет", "Извлечь acceptance criteria", "Зафиксировать в requirements.md", "Проверить assignee"],
        "0.00": ["Проверить git config user.name", "Проверить git config user.email", "Убедиться что identity выставлен корректно"],
        "0.5": ["Перевести Jira в статус 'В работе'", "Зафиксировать transition в changelog.md"],
        "0.6": ["Запустить workflow_researcher (delegate_task)", "Получить отчёт по dataflow", "Зафиксировать findings", "Дождаться COMPLETE"],
        "1": ["Определить репозиторий(и)", "Проверить target branch", "Синхронизировать ветку", "Проверить окружение"],
        "1.5": ["Запустить Deep Research (delegate_task)", "Собрать архитектуру + API + types", "Проверить existing реализации"],
        "3": ["Написать план в PLAN.md", "Чеклист подзадач (min 5)", "Оценить время", "CriticGate review"],
        "4": ["Реализовать по плану", "Обновлять current-stage.md", "TDD: тесты перед кодом", "Каждый checkpoint — ревизия"],
        "5": ["Запустить линтер/форматтер", "Проверить типы (tsc/mypy)", "Unit tests PASS", "Integration tests (если есть)"],
        "5.5": ["Скриншоты UI (если фронт)", "E2E тесты (если есть)", "Ручное тестирование edge cases", "Проверить на тестовых данных"],
        "6": ["git add только нужные файлы", "Сообщение с task_id", "Conventional commit format", "push --set-upstream origin"],
        "7": ["Создать MR через GitLab UI", "Заполнить description с чеклистом", "Прикрепить скриншоты к MR", "Назначить reviewer"],
        "7.5": ["Запустить workflow_reviewer (delegate_task)", "Ревью стиля, безопасности, логики", "Зафиксировать замечания", "Внести правки"],
        "7.6": ["Запустить QA (delegate_task)", "Функциональное тестирование", "Проверить на тестовом стенде", "Зафиксировать результаты"],
        "7.6.R": ["Запустить workflow_researcher (DVR)", "Проверить dataflow соответствие", "Зафиксировать DVR report", "Дождаться COMPLETE"],
        "8": ["Перевести Jira в 'Выполнено'", "Прикрепить MR ссылку к тикету", "Зафиксировать в changelog.md", "Голосовой отчёт (если нужно)"],
        "9": ["Ретроспектива: что сработало", "Метрики: время, tool calls, токены", "Сравнение solo vs delegate", "Обновить project-knowledge.md"],
    }
    return checklists.get(phase_name, [])


def show_phase_checklist(phase_name: str) -> None:
    """Показать чеклист для фазы (Rich console)."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    console = Console()
    items = get_phase_checklist_raw(phase_name)
    if not items:
        console.print(Panel("См. workflow skill для чеклиста", title=f"📋 Фаза {phase_name}", border_style="blue"))
        return

    text = Text()
    for item in items:
        text.append(f"  [ ] {item}\n")

    console.print(Panel(text, title=f"📋 Чеклист фазы {phase_name}", border_style="blue"))


def show_all_phases() -> None:
    """Показать все фазы с пометками."""
    from rich.console import Console
    from rich.table import Table
    from rich import box

    console = Console()
    table = Table(title="🗺️ project-workflow — все фазы", box=box.ROUNDED)
    table.add_column("#", style="cyan", width=6)
    table.add_column("Название", style="white")
    table.add_column("Тип", style="yellow")
    table.add_column("Мин. время", style="dim")

    # Stub names mapping for display
    names = {
        "-1": "Task Intake", "0.00": "Git Identity", "0.5": "Jira Transition",
        "0.6": "Researcher #1", "1": "Preflight", "1.5": "Deep Research",
        "3": "Plan", "4": "Implement", "5": "Validate", "5.5": "Self-Test",
        "6": "Commit", "7": "MR Draft", "7.5": "Code Review", "7.6": "QA Testing",
        "7.6.R": "DVR", "8": "Jira Done", "9": "Retro", "10": "Auto-Improve",
    }
    for code in config.PHASE_ORDER:
        table.add_row(code, names.get(code, ""), "", "")
    console.print(table)
    console.print("\n[dim]🔴 BLOCKER — если FAIL, workflow останавливается[/dim]")
    console.print("[dim]🤖 delegate — запускается через delegate_task[/dim]")
    console.print("[dim]🛡️ Critic — CriticGate checkpoint[/dim]")
