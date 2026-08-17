"""Contract-driven Agentic SDLC CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click
from pydantic import ValidationError

from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.v2 import PolicyEngineV2
from project_workflow.v2.engine import V2PolicyError
from project_workflow.v2.schemas import PhaseReportV2
from project_workflow.v2.task_adapter import CommandTaskAdapter

from .core import cli, console


def _emit(ctx: click.Context, payload: dict[str, Any]) -> None:
    if ctx.find_root().obj.get("json_mode"):
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        console.print_json(data=payload)


def _engine() -> tuple[SAUnitOfWork, PolicyEngineV2]:
    uow = SAUnitOfWork()
    uow.init()
    return uow, PolicyEngineV2(uow.session)


@cli.command("current")
@click.option("--task", "task_key", required=True)
@click.pass_context
def current_command(ctx: click.Context, task_key: str) -> None:
    """Return current state plus the only contract Hermes may execute."""
    uow, engine = _engine()
    try:
        task = CommandTaskAdapter.from_env().read(task_key.upper())
        _emit(ctx, {"ok": True, **engine.open_task(task.as_dict(), task.profile)})
    except V2PolicyError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        uow.close()

@cli.command("submit")
@click.option("--task", "task_key", required=True)
@click.option("--report", "report_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.pass_context
def submit_command(ctx: click.Context, task_key: str, report_path: Path) -> None:
    """Verify a structured phase report and atomically apply its controller decision."""
    try:
        report = PhaseReportV2.model_validate_json(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise click.ClickException(f"invalid phase-report/v2: {exc}") from exc
    if report.taskKey != task_key.upper():
        raise click.ClickException("--task does not match report.taskKey")
    uow, engine = _engine()
    try:
        result = engine.submit(report)
        _emit(ctx, {"ok": True, **result.model_dump(mode="json")})
    except (V2PolicyError, ValidationError) as exc:
        uow.rollback()
        raise click.ClickException(str(exc)) from exc
    finally:
        uow.close()
