"""CLI commands: status."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.table import Table
from rich import box

from .. import state, phases, jira_gitlab, conversation
from ..cli.core import cli, out_json, _require_valid_key
from ..cli.core import console, PASS, FAIL, WARN, BLOCK


@cli.command()
@click.argument("jira_key")
@click.pass_context
def status(ctx: click.Context, jira_key: str) -> None:
    jira_key = _require_valid_key(jira_key)
    """Текущий статус задачи."""
    jmode = ctx.obj.get("json_mode", False)
    repo = state.find_repo(jira_key)
    if not repo:
        if jmode:
            out_json({"ok": False, "error": f"Репозиторий не найден для {jira_key}"})
        console.print(f"{FAIL} Репозиторий не найден")
        return

    current = state.load_state(repo, jira_key)
    if not current:
        if jmode:
            out_json({"ok": False, "error": "Задача не инициализирована"})
        console.print(f"{FAIL} Задача не инициализирована")
        return

    jira_status = jira_gitlab.get_jira_status(jira_key)
    next_p = phases.get_next_phase(current.get("current_phase", ""))

    if jmode:
        out_json({
            "ok": True,
            "jira_key": current.get("jira_key"),
            "task_id": current.get("task_id"),
            "sprint": current.get("sprint"),
            "current_phase": current.get("current_phase"),
            "phases_completed": current.get("phases_completed", []),
            "jira_status": jira_status,
            "repo": repo,
            "next_phase": next_p,
        })

    table = Table(title=f"📋 Статус задачи {jira_key}", box=box.ROUNDED)
    table.add_column("Параметр", style="cyan")
    table.add_column("Значение", style="green")
    table.add_row("Jira Key", current.get("jira_key", "N/A"))
    table.add_row("Task ID", current.get("task_id", "N/A"))
    table.add_row("Sprint", current.get("sprint", "N/A"))
    table.add_row("Текущая фаза", current.get("current_phase", "N/A"))
    table.add_row("Jira статус", jira_status or "❌ API error")
    table.add_row("Репозиторий", repo)
    table.add_row("Завершено фаз", str(len(current.get("phases_completed", []))))
    console.print(table)

    phases.show_phase_checklist(current["current_phase"])


# ── wartz-workflow playbook ─────────────────────────────────────────────


@cli.command()
@click.argument("jira_key")
@click.argument("content")
@click.option("--task-id", help="Task ID (default from state)")
@click.pass_context
def note(ctx: click.Context, jira_key: str, content: str, task_id: Optional[str]) -> None:
    jira_key = _require_valid_key(jira_key)
    """Записать отчёт в историю задачи: hrflow note TASK-123 \"сделал X\""""
    jmode = ctx.obj.get("json_mode", False)
    repo = state.find_repo(jira_key)
    st = state.load_state(repo, jira_key) if repo else {}
    tid = task_id or st.get("task_id", jira_key)

    phase = conversation.get_last_phase(tid) or st.get("current_phase", "-1")
    msg_id = conversation.add_user_note(tid, jira_key, content, phase_id=phase)

    if jmode:
        out_json({"ok": True, "msg_id": msg_id, "phase": phase, "content": content})
    console.print(f"{PASS} Записано в историю {jira_key} (фаза {phase})")
    console.print(f"[dim]{content[:80]}[/dim]")


# ── wartz-workflow ui (web dashboard) ───────────────────────────────────

