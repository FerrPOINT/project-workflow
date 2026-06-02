"""CLI commands: rollback."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.table import Table
from rich import box

from .. import state, phases, schema, rollback
from ..cli.core import cli, out_json, _require_valid_key
from ..cli.core import console, PASS, FAIL, WARN, BLOCK


@cli.command()
@click.argument("jira_key")
@click.argument("phase_name")
@click.option("--reason", default="QA found bugs / Review rejected", show_default=True, help="Причина rollback")
@click.pass_context
def rollback_cmd(ctx: click.Context, jira_key: str, phase_name: str, reason: str) -> None:
    jira_key = _require_valid_key(jira_key)
    """Откатить задачу с phase_name к rollback_target с очисткой checkpoints.

    Пример:
        hrflow rollback AAT-123 7.6 --reason "QA FAIL: auth broken"
        hrflow rollback AAT-123 7.5 --reason "Review: fix SQL injection"
        hrflow rollback AAT-123 4.5 --reason "CriticGate: redesign needed"
    """
    jmode = ctx.obj.get("json_mode", False)
    repo = state.find_repo(jira_key)
    if not repo:
        if jmode:
            out_json({"ok": False, "error": "Репозиторий не найден"})
        console.print(f"{FAIL} Репозиторий не найден")
        raise click.Abort()

    if not rollback.can_rollback(phase_name):
        if jmode:
            out_json({
                "ok": False,
                "error": f"Фаза {phase_name} не поддерживает rollback",
                "hint": "У этой фазы нет rollback_target в phases.yaml",
            })
        console.print(f"{FAIL} Фаза {phase_name} не имеет rollback_target")
        console.print("[dim]Добавь rollback_target в phases.yaml для этой фазы[/dim]")
        raise click.Abort()

    # Check cycle limit
    cycle_info = rollback.get_cycle_info(jira_key)
    if cycle_info["remaining"] <= 0:
        if jmode:
            out_json({
                "ok": False,
                "error": "Превышен лимит retry cycles",
                "cycles": cycle_info["cycles"],
                "max_cycles": cycle_info["max_cycles"],
            })
        console.print(f"{BLOCK} [bold red]MAX CYCLES REACHED ({cycle_info['max_cycles']})[/bold red]")
        console.print("[red]Задача исчерпала лимит rollback. Требуется human intervention.[/red]")
        raise click.Abort()

    target, phases_to_clear = rollback.get_rollback_plan(phase_name)

    if jmode:
        # Preview mode
        out_json({
            "ok": True,
            "preview": True,
            "from_phase": phase_name,
            "to_phase": target,
            "phases_to_clear": phases_to_clear,
            "cycle_info": cycle_info,
            "reason": reason,
        })

    console.print(f"[bold]🔄 ROLLBACK: {phase_name} → {target}[/bold]")
    console.print(f"Причина: {reason}")
    console.print(f"Цикл: {cycle_info['cycles'] + 1}/{cycle_info['max_cycles']}")
    console.print("\n[yellow]Следующие фазы будут сброшены:[/yellow]")
    for ph in phases_to_clear:
        p = schema.get_phase(ph)
        name = p.name if p else ph
        console.print(f"  ❌ {ph} — {name}")

    # Execute rollback
    try:
        result = rollback.perform_rollback(repo, jira_key, phase_name, reason)
    except rollback.RollbackError as e:
        if jmode:
            out_json({"ok": False, "error": str(e)})
        console.print(f"{FAIL} Rollback failed: {e}")
        raise click.Abort()

    if jmode:
        out_json({
            "ok": True,
            "from_phase": result["from_phase"],
            "to_phase": result["to_phase"],
            "cleared_phases": result["cleared_phases"],
            "rollback_count": result["rollback_count"],
            "next_command": f"hrflow phase {jira_key} {result['to_phase']}",
        })

    console.print("\n[green]✅ Rollback complete[/green]")
    console.print(f"Сброшено фаз: {len(result['cleared_phases'])}")
    console.print(f"Осталось циклов: {cycle_info['remaining'] - 1}")
    console.print("\n[bold cyan]▶️ Продолжай:[/bold cyan]")
    console.print(f"  hrflow phase {jira_key} {result['to_phase']}")


# ── wartz-workflow note ─────────────────────────────────────────────────

