"""CLI commands: ui + wizard (consolidated)."""

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

from .. import wizard
from ..cli.core import cli, out_json, _require_valid_key
from ..cli.core import console, PASS, FAIL, WARN, BLOCK


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


# ── wartz-workflow wizard TASK-KEY [--report] [--context] [--list] ──────


@cli.command()
@click.argument("jira_key")
@click.option("--repo", default=None, help="Repo path (auto-detected if omitted)")
@click.option("--report", default=None, help="Отчёт агента (оценить и перейти)")
@click.option("--context", is_flag=True, help="Показать полный контекст (вместо инструкций)")
@click.option("--list", "list_flag", is_flag=True, help="Показать список пройденных этапов")
@click.pass_context
def wizard_cmd(
    ctx: click.Context,
    jira_key: str,
    repo: Optional[str],
    report: Optional[str],
    context: bool,
    list_flag: bool,
) -> None:
    """🧙 Wizard — инструкции, отчёт, контекст, список этапов.

    Usage:
      wartz-workflow wizard TASK-KEY              → текущие инструкции
      wartz-workflow wizard TASK-KEY --report "..." → оценить отчёт
      wartz-workflow wizard TASK-KEY --context    → полный контекст
      wartz-workflow wizard TASK-KEY --list       → список пройденных фаз
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

    # --list : show done-list
    if list_flag:
        data = engine.get_full_context()
        completed = data.get("completed_phases", [])
        current_phase = data.get("current_phase", "-1")

        wdb = WorkflowDB()
        wdb.init()
        all_phases = load_phases_from_db(wdb)
        phase_map = {p.id: p for p in all_phases}
        current_ph = phase_map.get(current_phase)

        if jmode:
            out_json({
                "ok": True,
                "jira_key": jira_key,
                "current_phase": current_phase,
                "current_phase_name": current_ph.name if current_ph else current_phase,
                "completed_count": len(completed),
                "total_phases": len(all_phases),
                "done_list": completed,
            })

        console.print(f"[bold]📋 Done-list: {jira_key}[/bold]")
        console.print(f"Текущая фаза: {current_phase} — {current_ph.name if current_ph else '?'}")
        console.print(f"Пройдено: {len(completed)} / {len(all_phases)}\n")
        if not completed:
            console.print("  Нет завершённых фаз")
        else:
            for pid in completed:
                ph = phase_map.get(pid)
                badges = []
                if ph and ph.is_blocker:
                    badges.append("[red]БЛОКЕР[/red]")
                if ph and ph.is_delegated:
                    badges.append("[yellow]АГЕНТ[/yellow]")
                badge_str = f" ({', '.join(badges)})" if badges else ""
                console.print(f"  {PASS} {pid} — {ph.name if ph else pid}{badge_str}")
        return

    # --context : full wizard context
    if context:
        data = engine.get_full_context()
        if jmode:
            out_json({
                "ok": True,
                "jira_key": jira_key,
                "current_phase": data["current_phase"],
                "current_phase_name": data["current_phase_name"],
                "completed_count": data["completed_count"],
                "total_phases": data["total_phases"],
                "completed_phases": data["completed_phases"],
                "all_phases": data["all_phases"],
                "repeatable_checks": data["repeatable_checks"],
                "phase_history_count": len(data["phase_history"]),
            })

        console.print(f"[bold]🧙 Wizard Context: {jira_key}[/bold]")
        console.print(f"Текущая фаза: {data['current_phase']} — {data['current_phase_name']}")
        console.print(f"Пройдено: {data['completed_count']} / {data['total_phases']}\n")

        if data["completed_phases"]:
            console.print("[bold]✅ Выполненные фазы:[/bold]")
            for pid in data["completed_phases"]:
                console.print(f"  {PASS} {pid}")
            console.print("")

        console.print("[bold]📋 Все фазы с инструкциями:[/bold]")
        for ph in data["all_phases"]:
            status_icon = PASS if ph["id"] in data["completed_phases"] else "[dim]⏳[/dim]"
            badges = []
            if ph["is_blocker"]:
                badges.append("[red]BLOCKER[/red]")
            if ph["is_delegated"]:
                badges.append("[yellow]DELEGATED[/yellow]")
            if ph["is_critic"]:
                badges.append("[magenta]CRITIC[/magenta]")
            badge_str = f" ({', '.join(badges)})" if badges else ""
            console.print(f"\n{status_icon} {ph['id']} — {ph['name']}{badge_str}")
            if ph["instructions"]:
                for inst in ph["instructions"]:
                    et = inst.get("execution_type", "sync")
                    et_icon = "[green]→[/green]" if et == "sync" else "[orange]⇄[/orange]"
                    console.print(f"   {et_icon} {inst['step']}")
            if ph["checks"]:
                for ck in ph["checks"]:
                    console.print(f"   [dim]✓ {ck['description']}[/dim]")

        console.print("\n[bold]🔄 Repeatable задания (последний отчёт):[/bold]")
        for rc in data["repeatable_checks"]:
            icon = PASS if rc["ok"] else FAIL
            console.print(f"   {icon} {rc['item']}")
        return

    # --report : evaluate report
    if report:
        result = wizard.evaluate_report(jira_key, report, repo_path)
        if jmode:
            out_json(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["verdict"] == "PASS" else 1)

    # default: show phase instructions
    wizard.main(jira_key, repo_path)


# ── main ────────────────────────────────────────────────────────────────

