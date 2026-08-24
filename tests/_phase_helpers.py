"""Test-only helpers moved from project_workflow/domain/fsm.py."""

from __future__ import annotations

from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._db_helpers import prepare_sqlite_uow

SEED_PHASES = schema.load_phases_from_seed()
PHASE_CODES = [phase.code for phase in SEED_PHASES]
PHASE_NAMES = {phase.code: phase.name for phase in SEED_PHASES}


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
        phase = uow.phases.get_by_code(workflow.id, phase_name) if workflow and workflow.id else None
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

    for code in PHASE_CODES:
        table.add_row(code, PHASE_NAMES[code])
    console.print(table)
    console.print("\n[dim]BLOCKER — если FAIL, workflow останавливается[/dim]")
    console.print("[dim]delegate — запускается через delegate_task[/dim]")
    console.print("[dim]Critic — CriticGate checkpoint[/dim]")
