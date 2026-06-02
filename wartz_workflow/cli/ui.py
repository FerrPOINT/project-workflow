"""CLI commands: ui."""

from __future__ import annotations

import json
import subprocess
import sys
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

    Usage: hrflow ui [--port 7788] [--daemon]
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


# ── wartz-workflow wizard (conversational) ──────────────────────────────


@cli.command()
@click.argument("jira_key")
@click.option("--repo", default=None, help="Repo path (auto-detected if omitted)")
@click.pass_context
def wizard_cmd(ctx: click.Context, jira_key: str, repo: Optional[str]) -> None:
    jira_key = _require_valid_key(jira_key)
    """🧙 Interactive wizard -- phase-by-phase workflow assistant.

    Usage: hrflow wizard TASKNEIROKLYUCH-456
    """
    wizard.main(jira_key, repo)


# ── main ────────────────────────────────────────────────────────────────

