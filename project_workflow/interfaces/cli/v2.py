"""Contract-driven Agentic SDLC v2 CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click
from pydantic import ValidationError

from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.v2 import PolicyEngineV2, load_default_catalog
from project_workflow.v2.engine import V2PolicyError
from project_workflow.v2.schemas import PhaseReportV2

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


@cli.group("v2")
def v2_group() -> None:
    """Deterministic agentic-sdlc-v2 controller."""


@v2_group.command("catalog")
@click.pass_context
def catalog_command(ctx: click.Context) -> None:
    """Validate and summarize the packaged immutable catalog."""
    catalog = load_default_catalog()
    phase_map = catalog.phases
    payload = {
        "ok": True,
        "workflowVersion": catalog.workflow_version,
        "catalogRevision": catalog.revision,
        "phases": len(phase_map),
        "featurePath": len(catalog.path("feature")),
        "bugPath": len(catalog.path("bug")),
        "instructions": sum(len(item["instructions"]) for item in phase_map.values()),
        "checks": sum(len(item["checks"]) for item in phase_map.values()),
        "evidenceRequirements": sum(len(item["evidenceRequirements"]) for item in phase_map.values()),
        "featureHumanGates": sum(bool(phase_map[item]["approvalRule"]) for item in catalog.path("feature")),
        "bugHumanGates": sum(bool(phase_map[item]["approvalRule"]) for item in catalog.path("bug")),
    }
    _emit(ctx, payload)


@v2_group.command("start")
@click.option("--task", "task_key", required=True)
@click.option("--profile", type=click.Choice(["feature", "bug"]), required=True)
@click.pass_context
def start_command(ctx: click.Context, task_key: str, profile: str) -> None:
    """Pin a new task to agentic-sdlc-v2 and its current catalog revision."""
    uow, engine = _engine()
    try:
        result = engine.start(task_key.upper(), profile)
        _emit(ctx, {"ok": True, **result})
    except V2PolicyError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        uow.close()


@v2_group.command("current")
@click.option("--task", "task_key", required=True)
@click.pass_context
def current_command(ctx: click.Context, task_key: str) -> None:
    """Return current state plus the only contract Hermes may execute."""
    uow, engine = _engine()
    try:
        _emit(ctx, {"ok": True, **engine.current(task_key.upper())})
    except V2PolicyError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        uow.close()


@v2_group.command("submit")
@click.option("--task", "task_key", required=True)
@click.option("--report", "report_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.pass_context
def submit_command(ctx: click.Context, task_key: str, report_path: Path) -> None:
    """Verify a phase-report/v2 and atomically apply its controller decision."""
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


@v2_group.command("history")
@click.option("--task", "task_key", required=True)
@click.pass_context
def history_command(ctx: click.Context, task_key: str) -> None:
    """Read immutable v2 attempt receipts for restart and audit."""
    uow, engine = _engine()
    try:
        _emit(ctx, {"ok": True, "taskKey": task_key.upper(), "attempts": engine.history(task_key.upper())})
    except V2PolicyError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        uow.close()


@v2_group.command("evidence-export")
@click.option("--task", "task_key", required=True)
@click.option("--schema-version", type=click.IntRange(1, 2), default=1, show_default=True)
@click.pass_context
def evidence_export_command(ctx: click.Context, task_key: str, schema_version: int) -> None:
    """Export sanitized verified evidence for the privileged E2E collector."""
    uow, engine = _engine()
    try:
        _emit(
            ctx,
            {
                "ok": True,
                **engine.evidence_export(task_key.upper(), schema_version=schema_version),
            },
        )
    except V2PolicyError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        uow.close()
