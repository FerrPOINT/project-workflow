"""CLI core — shared group, helpers, constants. No commands here.

ПРАВИЛО ПРОЕКТА: этот файл содержит только общий click-group и хелперы.
Никакие CLI-команды здесь не регистрируются. Все команды живут в
`project_workflow/interfaces/cli/ui.py` и их ровно две: step, history.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import click
from rich.console import Console

from ... import __version__
from ...domain import validation as task_validator
from ...domain.validation import TaskKeyValidationError

console = Console()

WARN = "[yellow]WARN[/yellow]"


def out_json(data: dict[str, Any], exit_code: int | None = None) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False))
    sys.exit(exit_code if exit_code is not None else (0 if data.get("ok", True) else 1))


def _get_task_key_validator(uow=None) -> task_validator.TaskKeyValidator:
    from project_workflow.infrastructure.db.uow import SAUnitOfWork

    if uow is None:
        uow = SAUnitOfWork()
    projects_raw = uow.projects.list()
    projects = [p.to_dict() for p in projects_raw]
    return task_validator.TaskKeyValidator.from_projects(projects)


def _require_valid_key(task_key: str, uow=None) -> str:
    """Проверить валидность ключа задачи по проектам из БД."""
    if uow is None:
        validated = _get_task_key_validator().validate(task_key)
    else:
        validated = _get_task_key_validator(uow=uow).validate(task_key)
    if not validated.is_valid:
        raise TaskKeyValidationError(task_key, validated.error_message or "unknown project prefix")
    return validated.normalized or task_key


def blocked_result(task_key: str, message: str, phase: str = "") -> dict[str, Any]:
    """Return the single fail-closed CLI error shape."""
    return {
        "verdict": "BLOCKED",
        "task_key": task_key,
        "phase": phase,
        "message": message,
        "covered": [],
        "missing": [],
        "blockers": ["configuration-error"],
        "current_phase": phase,
        "next_phase": None,
        "replayed": False,
        "retryable": True,
    }


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


__all__ = ["cli", "out_json", "_require_valid_key", "blocked_result", "console", "WARN"]
