"""CLI core — shared group, helpers, constants. No commands here.

ПРАВИЛО ПРОЕКТА: этот файл содержит только общий click-group и хелперы.
Никакие CLI-команды здесь не регистрируются. Все команды живут в
`project_workflow/interfaces/cli/ui.py` и их ровно две: step, history.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Sequence
from typing import Any

import click
from rich.console import Console

from ... import __version__
from ...domain import validation as task_validator
from ...domain.validation import TaskKeyValidationError

console = Console()

WARN = "[yellow]WARN[/yellow]"
NAMESPACE_ENV_VAR = "PROJECT_WORKFLOW_NAMESPACE_ID"


def _format_options(command: click.Command, ctx: click.Context, formatter: click.HelpFormatter) -> None:
    records = [record for param in command.get_params(ctx) if (record := param.get_help_record(ctx))]
    if records:
        with formatter.section("Параметры"):
            formatter.write_dl(records)


def _parameter_hint(exc: click.BadParameter) -> str:
    hint = exc.param_hint
    if hint is None and exc.param is not None:
        hint = exc.param.get_error_hint(exc.ctx)
    if isinstance(hint, Sequence) and not isinstance(hint, str):
        return " / ".join(hint)
    return str(hint or "")


def _usage_error_message(exc: click.UsageError) -> str:
    if isinstance(exc, click.NoSuchOption):
        return f"Нет такого параметра: {exc.option_name}."
    if isinstance(exc, click.MissingParameter):
        hint = _parameter_hint(exc)
        return f"Не указан обязательный параметр {hint}." if hint else "Не указан обязательный параметр."
    if isinstance(exc, click.BadParameter):
        hint = _parameter_hint(exc)
        return f"Некорректное значение параметра {hint}." if hint else "Некорректное значение параметра."
    missing_command = re.fullmatch(r"No such command '([^']+)'\.", exc.message)
    if missing_command:
        return f"Нет такой команды: {missing_command.group(1)!r}."
    return "Некорректный вызов команды."


class RussianUsageError(click.UsageError):
    """Usage error that never exposes Click's English diagnostics."""

    def show(self, file: Any | None = None) -> None:
        if file is None:
            file = sys.stderr
        if self.ctx is not None:
            click.echo(self.ctx.get_usage(), file=file)
            click.echo(f"Для справки: '{self.ctx.command_path} --help'.", file=file)
        click.echo(f"Ошибка: {self.message}", file=file)


def _russian_usage_error(exc: click.UsageError, ctx: click.Context) -> RussianUsageError:
    if isinstance(exc, RussianUsageError):
        return exc
    return RussianUsageError(_usage_error_message(exc), exc.ctx or ctx)


class RussianCommand(click.Command):
    """Click command with Russian help headings and built-in option text."""

    def format_usage(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write_usage(ctx.command_path, " ".join(self.collect_usage_pieces(ctx)), prefix="Использование: ")

    def format_options(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        _format_options(self, ctx, formatter)

    def get_help_option(self, ctx: click.Context) -> click.Option | None:
        option = super().get_help_option(ctx)
        if option is not None:
            option.help = "Показать справку и выйти."
        return option

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        try:
            return super().parse_args(ctx, args)
        except click.UsageError as exc:
            raise _russian_usage_error(exc, ctx) from exc


class RussianGroup(click.Group):
    """Click group whose complete help surface is Russian."""

    command_class = RussianCommand

    def format_usage(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write_usage(ctx.command_path, " ".join(self.collect_usage_pieces(ctx)), prefix="Использование: ")

    def format_options(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        _format_options(self, ctx, formatter)
        self.format_commands(ctx, formatter)

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        commands: list[tuple[str, str]] = []
        for name in self.list_commands(ctx):
            command = self.get_command(ctx, name)
            if command is None or command.hidden:
                continue
            commands.append((name, command.get_short_help_str()))
        if commands:
            with formatter.section("Команды"):
                formatter.write_dl(commands)

    def get_help_option(self, ctx: click.Context) -> click.Option | None:
        option = super().get_help_option(ctx)
        if option is not None:
            option.help = "Показать справку и выйти."
        return option

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        try:
            return super().parse_args(ctx, args)
        except click.UsageError as exc:
            raise _russian_usage_error(exc, ctx) from exc

    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        except click.UsageError as exc:
            raise _russian_usage_error(exc, exc.ctx or ctx) from exc


def _echo_json_text(text: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            buffer.write(text.encode("utf-8") + b"\n")
            buffer.flush()
            return
    click.echo(text)


def out_json(data: dict[str, Any], exit_code: int | None = None) -> None:
    _echo_json_text(json.dumps(data, indent=2, ensure_ascii=False))
    sys.exit(exit_code if exit_code is not None else (0 if data.get("ok", True) else 1))


def _get_task_key_validator(uow=None, project_id: int | None = None) -> task_validator.TaskKeyValidator:
    from project_workflow.infrastructure.db.uow import SAUnitOfWork

    if uow is None:
        with SAUnitOfWork() as owned_uow:
            projects_raw = owned_uow.projects.list()
            projects = [p.to_dict() for p in projects_raw]
    else:
        projects_raw = uow.projects.list()
        projects = [p.to_dict() for p in projects_raw]
    if project_id is not None:
        projects = [p for p in projects if p.get("id") == project_id]
    return task_validator.TaskKeyValidator.from_projects(projects)


def _require_valid_key(task_key: str, uow=None, project_id: int | None = None) -> str:
    """Проверить валидность ключа задачи по префиксам из БД."""
    if uow is None:
        validator = (
            _get_task_key_validator()
            if project_id is None
            else _get_task_key_validator(project_id=project_id)
        )
    else:
        validator = (
            _get_task_key_validator(uow=uow)
            if project_id is None
            else _get_task_key_validator(uow=uow, project_id=project_id)
        )
    validated = validator.validate(task_key)
    if not validated.is_valid:
        raise TaskKeyValidationError(task_key, validated.error_message or "неизвестный префикс")
    return validated.normalized or task_key


def _project_dicts(uow: Any) -> list[dict[str, Any]]:
    return [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in uow.projects.list()]


def _resolve_namespace_id(uow: Any, namespace: str | None) -> int | None:
    """Resolve optional namespace selector from an id, exact legacy code, name, or CLI command."""
    if namespace is None or not namespace.strip():
        return None
    selector = namespace.strip()
    projects = _project_dicts(uow)
    if selector.isdecimal():
        project_id = int(selector)
        if any(item.get("id") == project_id for item in projects):
            return project_id
        raise ValueError(f"Запись {project_id} не найдена")
    matches = [
        item
        for item in projects
        if str(item.get("code") or "").casefold() == selector.casefold()
        or str(item.get("name") or "").casefold() == selector.casefold()
        or str(item.get("cli_command") or "").casefold() == selector.casefold()
    ]
    if not matches:
        raise ValueError(f"Запись {selector!r} не найдена")
    if len(matches) > 1:
        raise ValueError(f"Выбор {selector!r} неоднозначен; укажите ID")
    resolved_project_id = matches[0].get("id")
    if (
        not isinstance(resolved_project_id, int)
        or isinstance(resolved_project_id, bool)
        or resolved_project_id <= 0
    ):
        raise ValueError(f"Выбор {selector!r} имеет некорректный id")
    return resolved_project_id


def _resolve_namespace_id_from_env(uow: Any) -> int | None:
    """Resolve the wrapper-selected namespace id from ``PROJECT_WORKFLOW_NAMESPACE_ID``."""
    raw = os.environ.get(NAMESPACE_ENV_VAR)
    if raw is None or not raw.strip():
        return None
    selector = raw.strip()
    if not selector.isdecimal():
        raise ValueError(f"{NAMESPACE_ENV_VAR} должен содержать положительный ID")
    namespace_id = int(selector)
    if namespace_id <= 0:
        raise ValueError(f"{NAMESPACE_ENV_VAR} должен содержать положительный ID")
    if not any(item.get("id") == namespace_id for item in _project_dicts(uow)):
        raise ValueError(f"Запись {namespace_id} не найдена")
    return namespace_id


def _resolve_context_id(uow: Any, context: str | None) -> int | None:
    """Backward-compatible alias for old callers; prefer ``_resolve_namespace_id``."""
    return _resolve_namespace_id(uow, context)


def _resolve_project_id(uow: Any, project: str | None) -> int | None:
    """Backward-compatible alias for old callers; prefer ``_resolve_namespace_id``."""
    return _resolve_namespace_id(uow, project)


def blocked_result(task_key: str, message: str, phase_code: str = "") -> dict[str, Any]:
    """Return the single fail-closed CLI error shape."""
    return {
        "verdict": "BLOCKED",
        "task_key": task_key,
        "phase_code": phase_code,
        "message": message,
        "covered": [],
        "missing": [],
        "blockers": ["configuration-error"],
        "current_phase_code": phase_code,
        "next_phase_code": None,
        "replayed": False,
        "retryable": True,
    }


@click.group(cls=RussianGroup)
@click.version_option(
    version=__version__,
    prog_name="project-workflow",
    message="project-workflow, версия %(version)s",
    help="Показать версию и выйти.",
)
@click.option(
    "--json", "json_mode", is_flag=True, help="Машиночитаемый JSON вывод (для CLI-автоматизации и внешних исполнителей)"
)
@click.pass_context
def cli(ctx: click.Context, json_mode: bool) -> None:
    """project-workflow — жёсткий пофазовый клиент."""
    ctx.ensure_object(dict)
    ctx.obj["json_mode"] = json_mode


__all__ = [
    "cli",
    "out_json",
    "_require_valid_key",
    "_resolve_namespace_id",
    "_resolve_namespace_id_from_env",
    "_resolve_context_id",
    "_resolve_project_id",
    "NAMESPACE_ENV_VAR",
    "blocked_result",
    "console",
    "WARN",
]
