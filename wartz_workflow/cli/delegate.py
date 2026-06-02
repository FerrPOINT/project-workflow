"""CLI commands: delegate — payload generator without job tracking."""

from __future__ import annotations

import json
from typing import Any, Dict

import click

from .. import state, profiles
from ..cli.core import cli, out_json
from ..cli.core import console, PASS, FAIL


@cli.command()
@click.argument("jira_key")
@click.argument("phase_name")
@click.pass_context
def delegate(ctx: click.Context, jira_key: str, phase_name: str) -> None:
    """Сгенерировать delegate_task payload для делегированной фазы."""
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

    delegate_call: Dict[str, Any] = {
        "tool": "delegate_task",
        "role": "leaf",
        "goal": payload["goal"],
        "context": payload["context"],
        "toolsets": payload["toolsets"],
    }

    if jmode:
        out_json({
            "ok": True,
            "phase": phase_name,
            "agent": payload["agent"],
            "delegate_call": delegate_call,
        })

    console.print("[bold]🤖 Delegate Payload Ready[/bold]")
    console.print(f"Phase: {phase_name} → Agent: {payload['agent']}")
    console.print("\n[bold cyan]📋 delegate_task вызов:[/bold cyan]")
    console.print(json.dumps(delegate_call, indent=2, ensure_ascii=False))
    console.print("\n[dim]После завершения верни отчёт через hrflow wizard[/dim]")
