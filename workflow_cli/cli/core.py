"""CLI core — shared group, helpers, constants. No commands here."""

from __future__ import annotations

import json
import sys
from typing import Any

import click
from rich.console import Console

from .. import task_validator

console = Console()

PASS = "[green]✅[/green]"
FAIL = "[red]❌[/red]"
WARN = "[yellow]⚠️[/yellow]"
BLOCK = "[red]🔴[/red]"


def out_json(data: dict[str, Any]) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False))
    sys.exit(0 if data.get("ok", True) else 1)


def _get_task_key_validator() -> task_validator.TaskKeyValidator:
    from ..db import WorkflowDB

    wdb = WorkflowDB()
    wdb.init()
    projects = wdb.get_projects()
    if projects:
        return task_validator.TaskKeyValidator.from_projects(projects)
    return task_validator.TaskKeyValidator.with_migration()


def _require_valid_key(task_key: str) -> str:
    """Проверить валидность ключа задачи. Вернуть normalized или выбросить Abort."""
    validated = _get_task_key_validator().validate(task_key)
    if not validated.is_valid:
        console.print(f"{FAIL} [bold red]Invalid task key:[/bold red] {validated.error_message}")
        raise click.Abort()
    return validated.normalized or task_key

"""Workflow CLI — жёсткий пофазовый клиент."""

@click.group()
@click.version_option(version="1.0.0", prog_name="workflow-cli")
@click.option("--json", "json_mode", is_flag=True, help="Машиночитаемый JSON вывод (для CLI-автоматизации и внешних исполнителей)")
@click.pass_context
def cli(ctx: click.Context, json_mode: bool) -> None:
    """Workflow CLI — жёсткий пофазовый клиент."""
    ctx.ensure_object(dict)
    ctx.obj["json_mode"] = json_mode


__all__ = ["cli", "out_json", "_require_valid_key", "console", "PASS", "FAIL", "WARN", "BLOCK"]
