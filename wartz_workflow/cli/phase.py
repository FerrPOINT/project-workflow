"""CLI commands: phase."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.table import Table
from rich import box

from .. import state, phases, engine, schema, wizard
from ..cli.core import cli, out_json, _require_valid_key
from ..cli.core import console, PASS, FAIL, WARN, BLOCK


@cli.command()
@click.argument("jira_key")
@click.argument("phase_name")
@click.pass_context
def phase(ctx: click.Context, jira_key: str, phase_name: str) -> None:
    jira_key = _require_valid_key(jira_key)
    """Выполнить конкретную фазу."""
    jmode = ctx.obj.get("json_mode", False)
    repo = state.find_repo(jira_key)

    if not repo:
        if jmode:
            out_json({"ok": False, "error": f"Репозиторий не найден для {jira_key}"})
        console.print(f"{FAIL} Не найден репозиторий для {jira_key}")
        raise click.Abort()

    current = state.load_state(repo, jira_key)
    if not current:
        if jmode:
            out_json({"ok": False, "error": "Задача не инициализирована", "fix": "wartz-workflow init"})
        console.print(f"{FAIL} Задача {jira_key} не инициализирована")
        raise click.Abort()

    # Проверка порядка
    ok, msg = phases.check_previous_phase(repo, jira_key, phase_name)
    if not ok:
        if jmode:
            out_json({"ok": False, "error": msg, "current_phase": current.get("current_phase")})
        console.print(f"{BLOCK} [bold red]BLOCKER:[/bold red] {msg}")
        raise click.Abort()

    # Используем engine для execution
    checks_ok, result = engine.execute_phase(repo, jira_key, phase_name)

    if jmode:
        out_json({
            "ok": checks_ok,
            "phase": phase_name,
            "result": result,
        })

    # Human output
    console.print(f"\n[bold]📍 Phase {phase_name}: {result['phase_name']}[/bold]")
    for cr in result["check_results"]:
        icon = PASS if cr["ok"] else (WARN if cr["optional"] else FAIL)
        console.print(f"{icon} {cr['description']}: {cr['detail']}")

    if not checks_ok:
        console.print(f"\n{BLOCK} [bold red]BLOCKER: checks FAILED[/bold red]")
        raise click.Abort()

    # Show playbook instructions
    if result.get("playbook"):
        pb = result["playbook"]
        console.print("\n[bold]📋 Playbook:[/bold]")
        for i, step in enumerate(pb["instructions"], 1):
            console.print(f"  {i}. {step}")

        if pb.get("delegate"):
            d = pb["delegate"]
            console.print(f"\n[bold]🤖 Delegate to {d['agent']}:[/bold]")
            console.print(f"  Toolsets: {', '.join(d['toolsets'])}")
            console.print(f"  Timeout: {d['timeout_min']} min")

    # Delegate command for agent
    if result.get("delegate_payload"):
        dp = result["delegate_payload"]
        console.print("\n[bold cyan]🤖 DELEGATE COMMAND (copy-paste для агента):[/bold cyan]")
        console.print(f"[dim]delegate_task(goal='{dp['goal']}', context='...', toolsets={dp['toolsets']})[/dim]")
        if result.get("job_id"):
            console.print(f"[dim]Job ID: {result['job_id']}[/dim]")

    # Parallel phases
    parallels = engine.get_parallel_phases(phase_name)
    if parallels:
        console.print("\n[bold yellow]🔄 Можно запустить ПАРАЛЛЕЛЬНО:[/bold yellow]")
        for p_id in parallels:
            p = schema.get_phase(p_id)
            if p:
                console.print(f"  hrflow phase {jira_key} {p_id}  # {p.name}")

    next_p = phases.get_next_phase(phase_name)
    if next_p:
        console.print(f"\n[dim]Следующий шаг: wartz-workflow next {jira_key}[/dim]")
    else:
        console.print("\n[green]✅ Все фазы выполнены![/green]")


# ── wartz-workflow next ─────────────────────────────────────────────────


@cli.command()
@click.argument("jira_key")
@click.option("--repo", help="Path к репозиторию (опционально)")
@click.pass_context
def next(ctx: click.Context, jira_key: str, repo: Optional[str]) -> None:
    jira_key = _require_valid_key(jira_key)
    """Запустить wizard для текущей фазы (= 'hrflow wizard TASK-KEY')."""
    jmode = ctx.obj.get("json_mode", False)
    if jmode:
        out_json({"ok": True, "message": "Wizard запущен", "next_command": f"hrflow wizard {jira_key}"})
    wizard.main(jira_key, repo)


# ── wartz-workflow status ───────────────────────────────────────────────

