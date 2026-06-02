"""CLI commands: delegate."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.table import Table
from rich import box

from .. import state, profiles, jobs
from ..cli.core import cli, out_json, _require_valid_key
from ..cli.core import console, PASS, FAIL, WARN, BLOCK


@cli.command()
@click.argument("jira_key")
@click.argument("phase_name")
@click.pass_context
def delegate(ctx: click.Context, jira_key: str, phase_name: str) -> None:
    """Сгенерировать готовый delegate_task payload для асинхронного запуска."""
    jmode = ctx.obj.get("json_mode", False)
    repo = state.find_repo(jira_key)
    if not repo:
        if jmode:
            out_json({"ok": False, "error": "Репозиторий не найден"})
        console.print(f"{FAIL} Репозиторий не найден")
        raise click.Abort()

    current = state.load_state(repo, jira_key)
    if not current:
        if jmode:
            out_json({"ok": False, "error": "Задача не инициализирована"})
        console.print(f"{FAIL} Задача не инициализирована")
        raise click.Abort()

    payload = profiles.build_delegate_payload(
        phase_name, jira_key,
        current.get("task_id", ""), current.get("title", "")
    )
    if not payload:
        if jmode:
            out_json({"ok": False, "error": f"Фаза {phase_name} не делегируется"})
        console.print(f"{FAIL} Фаза {phase_name} не требует делегирования")
        raise click.Abort()

    job = jobs.create_job(jira_key, phase_name, payload["agent"])

    # Build ready-to-paste delegate_task call
    delegate_call = {
        "tool": "delegate_task",
        "role": "leaf",
        "goal": payload["goal"],
        "context": payload["context"],
        "toolsets": payload["toolsets"],
    }

    # Update job with metadata
    jobs.update_job_status(job.job_id, "pending")

    if jmode:
        out_json({
            "ok": True,
            "job_id": job.job_id,
            "phase": phase_name,
            "agent": payload["agent"],
            "delegate_call": delegate_call,
            "usage": "Copy delegate_call into your next tool call",
        })

    console.print("[bold]🤖 Delegate Payload Ready[/bold]")
    console.print(f"Job ID: {job.job_id}")
    console.print(f"Phase: {phase_name} → Agent: {payload['agent']}")
    console.print("\n[bold cyan]📋 Скопируй delegate_task вызов ниже:[/bold cyan]")
    console.print("[dim]Роль: leaf (делегированный агент не спавнит дальше)[/dim]")
    console.print(f"[dim]Toolsets: {', '.join(delegate_call['toolsets'])}[/dim]\n")

    # Pretty-print the delegate call
    console.print("[yellow]delegate_task([/yellow]")
    console.print("  [green]role[/green]=[white]\"leaf\"[/white],")
    console.print(f"  [green]goal[/green]=[white]\"{delegate_call['goal']}\"[/white],")
    console.print("  [green]context[/green]=[white]\"...\"[/white],  [dim]# полный контекст в job файле[/dim]")
    console.print(f"  [green]toolsets[/green]={delegate_call['toolsets']},")
    console.print("[yellow])[/yellow]")

    console.print("\n[dim]После завершения проверь статус:[/dim]")
    console.print(f"  hrflow jobs {jira_key}")


# ── wartz-workflow delegate-batch ───────────────────────────────────────


@cli.command()
@click.argument("jira_key")
@click.argument("phase_names", nargs=-1)
@click.pass_context
def delegate_batch(ctx: click.Context, jira_key: str, phase_names: tuple) -> None:
    """Сгенерировать batch delegate_task для параллельных фаз.
    
    Пример: hrflow delegate-batch AAT-123 7.5 7.6 7.6.R
    """
    jmode = ctx.obj.get("json_mode", False)
    repo = state.find_repo(jira_key)
    if not repo:
        if jmode:
            out_json({"ok": False, "error": "Репозиторий не найден"})
        console.print(f"{FAIL} Репозиторий не найден")
        raise click.Abort()

    current = state.load_state(repo, jira_key)
    if not current:
        if jmode:
            out_json({"ok": False, "error": "Задача не инициализирована"})
        console.print(f"{FAIL} Задача не инициализирована")
        raise click.Abort()

    if not phase_names:
        if jmode:
            out_json({"ok": False, "error": "Укажи хотя бы одну фазу"})
        console.print(f"{FAIL} Укажи фазы для делегирования")
        raise click.Abort()

    tasks = []
    for phase_name in phase_names:
        payload = profiles.build_delegate_payload(
            phase_name, jira_key,
            current.get("task_id", ""), current.get("title", "")
        )
        if not payload:
            if jmode:
                out_json({"ok": False, "error": f"Фаза {phase_name} не делегируется"})
            console.print(f"{FAIL} Фаза {phase_name} не требует делегирования")
            raise click.Abort()

        job = jobs.create_job(jira_key, phase_name, payload["agent"])

        tasks.append({
            "goal": payload["goal"],
            "context": payload["context"],
            "toolsets": payload["toolsets"],
            "role": "leaf",
            "phase": phase_name,
            "agent": payload["agent"],
            "job_id": job.job_id,
        })

    # Build batch delegate_task
    batch_call = {
        "tool": "delegate_task",
        "tasks": [
            {
                "role": t["role"],
                "goal": t["goal"],
                "context": t["context"],
                "toolsets": t["toolsets"],
            }
            for t in tasks
        ],
    }

    if jmode:
        out_json({
            "ok": True,
            "jira_key": jira_key,
            "phase_count": len(tasks),
            "tasks": [
                {"phase": t["phase"], "agent": t["agent"], "job_id": t["job_id"]} for t in tasks
            ],
            "batch_delegate_call": batch_call,
            "usage": "Run delegate_task with tasks=[...] array",
        })

    console.print(f"[bold]🤖 Batch Delegate Ready — {len(tasks)} phases[/bold]")
    for t in tasks:
        console.print(f"  {t['phase']}: {t['agent']} (job {t['job_id']})")

    console.print("\n[bold cyan]📋 Batch delegate_task:[/bold cyan]")
    console.print("[yellow]delegate_task([/yellow]")
    console.print("  [green]tasks[/green]=[")
    for t in tasks:
        console.print("    {")
        console.print("      [green]role[/green]: [white]\"leaf\"[/white],")
        console.print(f"      [green]goal[/green]: [white]\"{t['goal'][:60]}...\"[/white],")
        console.print(f"      [green]toolsets[/green]: {t['toolsets']},")
        console.print("    },")
    console.print("  ]")
    console.print("[yellow])[/yellow]")

    console.print("\n[dim]После завершения:[/dim]")
    console.print(f"  hrflow jobs {jira_key}")


# ── wartz-workflow jobs ─────────────────────────────────────────────────


@cli.command()
@click.argument("jira_key")
@click.pass_context
def jobs_cmd(ctx: click.Context, jira_key: str) -> None:
    """Показать status всех background jobs для задачи."""
    jmode = ctx.obj.get("json_mode", False)
    job_list = jobs.list_jobs(jira_key=jira_key)

    if jmode:
        out_json({
            "ok": True,
            "jira_key": jira_key,
            "jobs": [
                {
                    "job_id": j.job_id,
                    "phase_id": j.phase_id,
                    "agent": j.agent,
                    "status": j.status,
                    "created_at": j.created_at,
                    "completed_at": j.completed_at,
                }
                for j in job_list
            ],
            "count": len(job_list),
        })

    console.print(f"[bold]📋 Background Jobs для {jira_key}[/bold]")
    if not job_list:
        console.print("  Нет jobs.")
        return

    table = Table(box=box.ROUNDED)
    table.add_column("Job", style="cyan")
    table.add_column("Phase", style="white")
    table.add_column("Agent", style="yellow")
    table.add_column("Status", style="green")
    table.add_column("Created")
    for j in job_list:
        status_color = {
            "pending": "[yellow]⏳ pending[/yellow]",
            "running": "[blue]🔄 running[/blue]",
            "complete": "[green]✅ complete[/green]",
            "failed": "[red]❌ failed[/red]",
        }.get(j.status, j.status)
        table.add_row(j.job_id, j.phase_id, j.agent, status_color, j.created_at[:10])
    console.print(table)

    # Check if any delegated phases are still pending
    pending = [j for j in job_list if j.status in ("pending", "running")]
    if pending:
        console.print(f"\n[yellow]⏳ {len(pending)} job(s) в ожидании. Запусти delegate скрипты.[/yellow]")
    else:
        console.print("\n[green]✅ Все jobs завершены. Продолжай workflow.[/green]")


# ── wartz-workflow rollback ───────────────────────────────────────────────

