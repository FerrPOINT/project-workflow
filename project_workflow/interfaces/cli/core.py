"""CLI core shared by the canonical controller commands."""

from __future__ import annotations

import click
from rich.console import Console

from ... import __version__

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="project-workflow")
@click.option(
    "--json", "json_mode", is_flag=True, help="Машиночитаемый JSON вывод (для CLI-автоматизации и внешних исполнителей)"
)
@click.pass_context
def cli(ctx: click.Context, json_mode: bool) -> None:
    """project-workflow — жёсткий пофазовый клиент."""
    ctx.ensure_object(dict)
    ctx.obj["json_mode"] = json_mode


__all__ = ["cli", "console"]
