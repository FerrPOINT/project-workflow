"""CLI commands: ui + step (consolidated)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.table import Table
from rich import box

from .. import wizard, conversation as convo
from ..cli.core import cli, out_json, _require_valid_key
from ..cli.core import console, PASS, FAIL, WARN, BLOCK


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND: step
# ═══════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("jira_key")
@click.option("--repo", default=None, help="Repo path (auto-detected if omitted)")
@click.option("--report", default=None, help="Отчёт агента (оценить и перейти)")
@click.option("--skip", is_flag=True, help="Форсировать переход к следующей фазе без отчёта")
@click.pass_context
def step_cmd(
    ctx: click.Context,
    jira_key: str,
    repo: Optional[str],
    report: Optional[str],
    skip: bool,
) -> None:
    """🚶 Step — движение по workflow: показать текущую фазу или отчитаться и перейти.

    Usage:
      wartz-workflow step TASK-KEY                → текущие инструкции
      wartz-workflow step TASK-KEY --report "..."  → оценить отчёт и перейти
      wartz-workflow step TASK-KEY --skip         → форсировать переход без отчёта
    """
    import time
    jira_key = _require_valid_key(jira_key)
    jmode = ctx.obj.get("json_mode", False)

    from .. import state, config
    from ..db import WorkflowDB
    from ..schema import load_phases_from_db

    found_repo = state.find_repo(jira_key)
    repo_path = repo or found_repo or "/opt/dev/hr-recruiter/recruiter-front"

    # Auto-init if task not initialized
    current = state.load_state(found_repo, jira_key) if found_repo else None
    if not current:
        console.print(f"{WARN} Задача {jira_key} не инициализирована.")
        console.print("[bold]Создаём задачу?[/bold] Автоматически создаём info/, progress.json, changelog.md")
        # Create minimal task structure
        sprint = "sprint-auto"
        task_id = jira_key.split("-")[-1] if "-" in jira_key else jira_key
        title = f"Auto-init {jira_key}"
        success, task_dir = state.create_task_dir(repo_path, sprint, task_id, jira_key, title)
        if success:
            console.print(f"{PASS} Задача создана: {task_dir}")
            current = state.load_state(repo_path, jira_key)
        else:
            console.print(f"{FAIL} Не удалось создать задачу")
            raise click.Abort()

    engine = wizard.WizardEngine(jira_key, repo_path)

    # --report : evaluate report
    if report:
        result = wizard.evaluate_report(jira_key, report, repo_path)
        if jmode:
            out_json(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["verdict"] == "PASS" else 1)

    # --skip : force advance
    if skip:
        _force_advance(engine, jira_key, repo_path, jmode)
        sys.exit(0)

    # default: show phase instructions
    wizard.main(jira_key, repo_path)


def _force_advance(engine: wizard.WizardEngine, jira_key: str, repo: str, jmode: bool) -> None:
    """Force transition to next phase without report."""
    from .core import out_json
    from .. import config

    current = engine.current_phase
    phase = engine.phase_map.get(current)
    if phase is None:
        phase = engine._resolve_phase(current)

    if phase is None or current == "COMPLETE":
        msg = "Все фазы выполнены. Некуда переходить."
        if jmode:
            out_json({"ok": True, "message": msg})
        console.print(f"{PASS} {msg}")
        return

    next_phase, next_name = engine._get_next_phase(phase)
    engine._record_transition(phase.id, next_phase or "COMPLETE")

    msg = f"Форсированный переход: {phase.id} ({phase.name}) → {next_phase or 'COMPLETE'}"
    if jmode:
        out_json({
            "ok": True,
            "verdict": "SKIP",
            "phase": phase.id,
            "phase_name": phase.name,
            "next_phase": next_phase,
            "next_phase_name": next_name,
            "message": msg,
        })
    console.print(f"{WARN} {msg}")
    if next_phase and next_name:
        console.print(f"[bold]▶️ Следующая фаза: {next_phase} — {next_name}[/bold]")
        # Show instructions for next phase
        prompt = engine.get_phase_prompt(next_phase)
        console.print(f"\n{prompt}")


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND: history
# ═══════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("jira_key")
@click.option("--repo", default=None, help="Repo path")
@click.option("--n", default=20, help="Количество записей (default 20)")
@click.pass_context
def history_cmd(ctx: click.Context, jira_key: str, repo: Optional[str], n: int) -> None:
    """📜 History — история отчётов, переходов и статусов по задаче.

    Usage:
      wartz-workflow history TASK-KEY           → последние 20 записей
      wartz-workflow history TASK-KEY --n 50     → последние 50 записей
    """
    jira_key = _require_valid_key(jira_key)
    jmode = ctx.obj.get("json_mode", False)

    task_id = jira_key.split("-")[-1] if "-" in jira_key else jira_key
    records = convo.get_messages(task_id, limit=n)

    if jmode:
        out_json({
            "ok": True,
            "jira_key": jira_key,
            "count": len(records),
            "records": [
                {
                    "role": r.role,
                    "phase_id": r.phase_id,
                    "tags": r.tags,
                    "content": r.content,
                    "created_at": r.created_at,
                }
                for r in records
            ],
        })

    if not records:
        console.print(f"{WARN} История для {jira_key} пуста.")
        return

    console.print(f"[bold]📜 History: {jira_key}[/bold] (последние {len(records)} записей)\n")
    for r in records:
        tag_icon = "🔄" if r.tags == "transition" else "📝" if r.role == "user" else "🤖"
        phase_str = f" [phase {r.phase_id}]" if r.phase_id else ""
        console.print(f"{tag_icon} [{r.created_at}]{phase_str}")
        lines = r.content.split("\n")
        for line in lines[:5]:
            console.print(f"   {line}")
        if len(lines) > 5:
            console.print(f"   ... и ещё {len(lines) - 5} строк")
        console.print("")


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND: ui
# ═══════════════════════════════════════════════════════════════════════

@cli.command("ui")
@click.option("--port", default=7788, help="Порт (default 7788)")
@click.option("--host", default="0.0.0.0", help="Хост (default 0.0.0.0)")
@click.option("--daemon", is_flag=True, help="Запустить в background")
def ui_cmd(port: int, host: str, daemon: bool) -> None:
    """🌐 Web UI — просмотр фаз, задач, истории.

    Usage: wartz-workflow ui [--port 7788] [--daemon]
    """
    from .ui import ensure_templates, app
    ensure_templates()
    console.print(f"{PASS} Запуск wartz-workflow UI на http://{host}:{port}")
    if daemon:
        console.print(f"[dim]Background mode: http://{host}:{port}[/dim]")
    else:
        console.print("[dim]Press Ctrl+C to stop[/dim]")
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")
