"""GitLab CLI — standalone tool for GitLab operations."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.table import Table
from rich import box

from .adapters.http.gitlab import GitLabAdapter
from .config import GITLAB_API_URL, GITLAB_PROJECT_ID

console = Console()

PASS = "[green]✅[/green]"
FAIL = "[red]❌[/red]"
WARN = "[yellow]⚠️[/yellow]"


def out_json(data: dict[str, Any]) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False))
    sys.exit(0 if data.get("ok", True) else 1)


@click.group()
@click.version_option(version="1.0.0", prog_name="gitlab")
@click.option("--json", "json_mode", is_flag=True, help="Машиночитаемый JSON вывод")
@click.option("--url", default=GITLAB_API_URL, help="GitLab API URL")
@click.option("--project", default=GITLAB_PROJECT_ID, help="Project ID")
@click.pass_context
def cli(ctx: click.Context, json_mode: bool, url: str, project: str) -> None:
    """GitLab CLI — проверка MR, проектов, merge status."""
    ctx.ensure_object(dict)
    ctx.obj["json_mode"] = json_mode
    ctx.obj["gitlab"] = GitLabAdapter(api_url=url, project_id=project)


@cli.command()
@click.argument("task_id")
@click.pass_context
def mr(ctx: click.Context, task_id: str) -> None:
    """Найти MR по task_id."""
    jmode = ctx.obj.get("json_mode", False)
    adapter = ctx.obj["gitlab"]
    result = adapter.search_merge_requests(task_id)
    if jmode:
        out_json({"ok": True, "task_id": task_id, "mr": result})
    if not result:
        console.print(f"{WARN} MR для {task_id} не найден")
        return
    table = Table(title=f"🔀 MR: {task_id}", box=box.ROUNDED)
    table.add_column("Поле", style="cyan")
    table.add_column("Значение", style="green")
    table.add_row("Title", result.get("title", "N/A"))
    table.add_row("State", result.get("state", "N/A"))
    table.add_row("IID", str(result.get("iid", "?")))
    table.add_row("Source", result.get("source_branch", "N/A"))
    table.add_row("Target", result.get("target_branch", "N/A"))
    table.add_row("Merged by", result.get("merged_by") or "❌ NOT MERGED")
    table.add_row("URL", result.get("web_url", "N/A"))
    console.print(table)


@cli.command()
@click.argument("project_id")
@click.pass_context
def project(ctx: click.Context, project_id: str) -> None:
    """Информация о проекте."""
    jmode = ctx.obj.get("json_mode", False)
    adapter = ctx.obj["gitlab"]
    result = adapter.get_project(project_id)
    if jmode:
        out_json({"ok": True, "project_id": project_id, "project": result})
    if not result:
        console.print(f"{FAIL} Проект {project_id} не найден")
        return
    console.print(f"{PASS} Проект: {result.get('name', 'N/A')}")
    console.print(f"  Path: {result.get('path_with_namespace', 'N/A')}")
    console.print(f"  Stars: {result.get('star_count', 0)}")
    console.print(f"  URL: {result.get('web_url', 'N/A')}")


@cli.command()
@click.pass_context
def ping(ctx: click.Context) -> None:
    """Проверить подключение к GitLab."""
    jmode = ctx.obj.get("json_mode", False)
    adapter = ctx.obj["gitlab"]
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
