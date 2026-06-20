"""Управление фазами workflow — порядок, чеклисты, консольный вывод.

Устаревшие функции (run_phase, check_previous_phase, conditional_delegate_jump)
удалены — вся логика FSM теперь в wizard.py.
"""

from typing import List, Optional

from . import config

PHASE_ORDER = config.PHASE_ORDER


def get_next_phase(current_phase: str) -> Optional[str]:
    """Определить следующую фазу по порядку."""
    try:
        idx = PHASE_ORDER.index(current_phase)
    except ValueError:
        return None

    if idx + 1 < len(PHASE_ORDER):
        return PHASE_ORDER[idx + 1]
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
    table = Table(title="🗺️ Workflow CLI — все фазы", box=box.ROUNDED)
    table.add_column("#", style="cyan", width=6)
    table.add_column("Название", style="white")
    table.add_column("Тип", style="yellow")
    table.add_column("Мин. время", style="dim")

    phase_meta = {
        "-1": ("Task Intake", "", 1),
        "0.0a": ("Suite Verification", "", 2),
        "0.01": ("Task Docs Setup", "", 2),
        "0.00": ("Git Identity", "", 1),
        "0.000": ("Workspace", "", 1),
        "0.5": ("Jira Transition", "", 1),
        "0.6": ("Researcher #1", "🤖 delegate", 5),
        "0.7": ("Repo Sync", "", 2),
        "0.9": ("CriticGate-PreFlight", "🛡️ Critic", 2),
        "1": ("Preflight", "", 10),
        "1.5": ("Deep Research", "🤖 delegate", 5),
        "2": ("Research Synthesis", "", 10),
        "3": ("Plan", "", 15),
        "3.5": ("CriticGate-PrePlan", "🛡️ Critic", 5),
        "4": ("Implement", "", 30),
        "4.5": ("CriticGate-PreCommit", "🛡️ Critic", 5),
        "5": ("Validate", "", 10),
        "5.5": ("Self-Test", "", 15),
        "6": ("Commit", "", 3),
        "7": ("MR Draft", "", 5),
        "7.5": ("Code Review", "🤖 delegate", 10),
        "7.6": ("QA Testing", "🤖 delegate", 10),
        "7.6.R": ("DVR", "🤖 delegate", 5),
        "7.7": ("CriticGate-PostQA", "🛡️ Critic", 5),
        "8": ("Jira Done", "", 2),
        "9": ("Retro", "", 10),
    }

    for p in PHASE_ORDER:
        name, ptype, mins = phase_meta.get(p, ("?", "", 0))
        table.add_row(p, name, ptype, f"{mins} min")

    console.print(table)
    console.print("\n[dim]🔴 BLOCKER — если FAIL, workflow останавливается[/dim]")
    console.print("[dim]🤖 delegate — запускается через delegate_task[/dim]")
    console.print("[dim]🛡️ Critic — CriticGate checkpoint[/dim]")
