"""Test-only helpers moved from project_workflow/domain/fsm.py."""

from __future__ import annotations

from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._db_helpers import prepare_sqlite_uow

PHASE_CODES = [phase.code for phase in schema.load_phases_from_seed()]


def get_next_phase(current_phase: str) -> str | None:
    """Return the next phase code in configured order."""
    try:
        idx = PHASE_CODES.index(current_phase)
    except ValueError:
        return None

    if idx + 1 < len(PHASE_CODES):
        return PHASE_CODES[idx + 1]
    return None


def get_phase_checklist_raw(phase_name: str) -> list[str]:
    """Return raw checklist items for a phase from the DB catalog."""
    try:
        uow = SAUnitOfWork()
        prepare_sqlite_uow(uow)
        workflow = uow.workflows.get_default()
        phase = schema.get_phase_from_db(uow, phase_name, workflow.id) if workflow and workflow.id else None
        if phase:
            items: list[str] = []
            for check in phase.checks:
                txt = getattr(check, "description", "")
                if txt:
                    items.append(str(txt).strip())
            for ev in phase.evidence:
                txt = getattr(ev, "item", "")
                if txt:
                    items.append(str(txt).strip())
            return items
    except Exception:
        pass
    return []


def show_phase_checklist(phase_name: str) -> None:
    """Print a Rich panel with the phase checklist (test helper)."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    console = Console()
    items = get_phase_checklist_raw(phase_name)
    if not items:
        console.print(Panel("См. workflow skill для чеклиста", title=f"Фаза {phase_name}", border_style="blue"))
        return

    text = Text()
    for item in items:
        text.append(f"  [ ] {item}\n")

    console.print(Panel(text, title=f"Чеклист фазы {phase_name}", border_style="blue"))


def show_all_phases() -> None:
    """Print a Rich table with all configured phase codes (test helper)."""
    from rich import box
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="project-workflow — все фазы", box=box.ROUNDED)
    table.add_column("#", style="cyan", width=6)
    table.add_column("Название", style="white")

    names = {
        "-1": "Task Intake",
        "0.0a": "Runtime Readiness",
        "0.01": "Acceptance Setup",
        "0.000": "Workspace",
        "0.00": "Git Identity",
        "0.7": "Repo Sync",
        "0.9": "CriticGate-PreFlight",
        "0.5": "Work Start",
        "0.6": "Researcher #1",
        "1": "Preflight",
        "1.5": "Deep Research",
        "2": "Research Synthesis",
        "3": "Plan",
        "3.5": "CriticGate-PrePlan",
        "4": "Implement",
        "4.5": "CriticGate-PreCommit",
        "5": "Validate",
        "5.5": "Self-Test",
        "6": "Commit",
        "7": "Merge Request",
        "7.5": "Code Review",
        "7.6": "QA Testing",
        "7.6.R": "DVR",
        "7.7": "CriticGate-PostQA",
        "8": "Delivery Handoff",
        "9": "Retro",
        "10": "Auto-Improve",
    }
    for code in PHASE_CODES:
        table.add_row(code, names.get(code, ""))
    console.print(table)
    console.print("\n[dim]BLOCKER — если FAIL, workflow останавливается[/dim]")
    console.print("[dim]delegate — запускается через delegate_task[/dim]")
    console.print("[dim]Critic — CriticGate checkpoint[/dim]")
