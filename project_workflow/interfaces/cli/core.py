"""CLI core — shared group, helpers, constants. No commands here.

ПРАВИЛО ПРОЕКТА: этот файл содержит только общий click-group и хелперы.
Никакие CLI-команды здесь не регистрируются. Все команды живут в
`project_workflow/interfaces/cli/ui.py` и их ровно две: step, history.
"""

from __future__ import annotations

import json
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
            file = click.get_text_stream("stderr")
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
        raise TaskKeyValidationError(task_key, validated.error_message or "неизвестный префикс проекта")
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


__all__ = ["cli", "out_json", "_require_valid_key", "blocked_result", "console", "WARN"]
