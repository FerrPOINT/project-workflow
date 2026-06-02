"""Jira CLI — standalone tool for Jira operations."""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.table import Table
from rich import box

from .adapters.http.jira import JiraAdapter
from .config import JIRA_API_URL

console = Console()

PASS = "[green]✅[/green]"
FAIL = "[red]❌[/red]"
WARN = "[yellow]⚠️[/yellow]"


def out_json(data: dict[str, Any]) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False))
    sys.exit(0 if data.get("ok", True) else 1)


@click.group()
@click.version_option(version="1.0.0", prog_name="jira")
@click.option("--json", "json_mode", is_flag=True, help="Машиночитаемый JSON вывод")
@click.option("--url", default=JIRA_API_URL, help="Jira API URL")
@click.pass_context
def cli(ctx: click.Context, json_mode: bool, url: str) -> None:
    """Jira CLI — управление тикетами и transitions."""
    ctx.ensure_object(dict)
    ctx.obj["json_mode"] = json_mode
    ctx.obj["jira"] = JiraAdapter(api_url=url)


@cli.command()
@click.argument("issue_key")
@click.pass_context
def status(ctx: click.Context, issue_key: str) -> None:
    """Получить статус тикета."""
    jmode = ctx.obj.get("json_mode", False)
    adapter = ctx.obj["jira"]
    result = adapter.get_status(issue_key)
    if jmode:
        out_json({"ok": True, "issue_key": issue_key, "status": result})
    if result:
        console.print(f"{PASS} {issue_key}: [bold]{result}[/bold]")
    else:
        console.print(f"{FAIL} {issue_key}: не удалось получить статус")


@cli.command()
@click.argument("issue_key")
@click.pass_context
def info(ctx: click.Context, issue_key: str) -> None:
    """Полная информация о тикете."""
    jmode = ctx.obj.get("json_mode", False)
    adapter = ctx.obj["jira"]
    data = adapter.get_task_info(issue_key)
    if jmode:
        out_json(data)
    if not data.get("ok"):
        console.print(f"{FAIL} Ошибка: {data.get('error', 'unknown')}")
        return
    table = Table(title=f"📋 {issue_key}", box=box.ROUNDED)
    table.add_column("Поле", style="cyan")
    table.add_column("Значение", style="green")
    table.add_row("Summary", data.get("summary", "N/A"))
    table.add_row("Status", data.get("status", "N/A"))
    table.add_row("Assignee", data.get("assignee") or "Unassigned")
    table.add_row("Source", data.get("source", "unknown"))
    console.print(table)


@cli.command()
@click.argument("issue_key")
@click.pass_context
def transitions(ctx: click.Context, issue_key: str) -> None:
    """Список доступных transitions."""
    jmode = ctx.obj.get("json_mode", False)
    adapter = ctx.obj["jira"]
    trans = adapter.get_transitions(issue_key)
    if jmode:
        out_json({"ok": True, "issue_key": issue_key, "transitions": trans})
    if not trans:
        console.print(f"{WARN} Нет доступных transitions")
        return
    table = Table(box=box.ROUNDED)
    table.add_column("ID", style="dim")
    table.add_column("Name", style="cyan")
    table.add_column("To", style="green")
    for t in trans:
        to_name = t.get("to", {}).get("name", "unknown") if isinstance(t.get("to"), dict) else "unknown"
        table.add_row(t.get("id", "?"), t.get("name", "?"), to_name)
    console.print(table)


@cli.command()
@click.argument("issue_key")
@click.argument("transition_name")
@click.pass_context
def transition(ctx: click.Context, issue_key: str, transition_name: str) -> None:
    """Перевести тикет в новый статус."""
    jmode = ctx.obj.get("json_mode", False)
    adapter = ctx.obj["jira"]
    ok, msg = adapter.transition(issue_key, transition_name)
    if jmode:
        out_json({"ok": ok, "issue_key": issue_key, "transition": transition_name, "message": msg})
    if ok:
        console.print(f"{PASS} {msg}")
    else:
        console.print(f"{FAIL} {msg}")
        raise click.Abort()


@cli.command()
@click.pass_context
def ping(ctx: click.Context) -> None:
    """Проверить подключение к Jira."""
    jmode = ctx.obj.get("json_mode", False)
    adapter = ctx.obj["jira"]
    ok, msg = adapter.ping()
    if jmode:
        out_json({"ok": ok, "message": msg})
    console.print(f"{PASS if ok else FAIL} {msg}")
    if not ok:
        raise click.Abort()


def main() -> None:
    cli()

if __name__ == "__main__":
    main()
