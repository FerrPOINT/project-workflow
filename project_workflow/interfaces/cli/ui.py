"""Agent CLI: two commands over the configured Workflow API."""

from __future__ import annotations

from typing import Any

import click

from . import configured
from .core import cli, console, out_json


def _output(ctx: click.Context, response: dict[str, Any]) -> None:
    result, code = response["result"], response["exit_code"]
    if ctx.obj.get("json_mode", False):
        out_json(result, exit_code=code)
        return
    console.print(str(result.get("instructions", result)))
    raise click.exceptions.Exit(code)


@cli.command()
@click.option("--task", required=True, help="Ключ назначенной задачи Workflow")
@click.option("--report", default=None, help="Отчёт текстом; - читает stdin")
@click.option("--operation-key", default=None, help="Стабильный ключ операции отправки отчёта")
@click.option("--expected-version", type=click.IntRange(min=1), default=None,
              help="Версия из последнего ответа Workflow")
@click.option("--requirements-revision", type=click.IntRange(min=1), default=None,
              help="Подтверждённая редакция требований для финального PM отчёта")
@click.option("--requirements-sha256", default=None, help="Hash подтверждённой редакции требований")
@click.pass_context
def step_cmd(ctx: click.Context, task: str, report: str | None, operation_key: str | None,
             expected_version: int | None, requirements_revision: int | None,
             requirements_sha256: str | None) -> None:
    """Получить текущую фазу или отправить отчёт для оценки."""
    try:
        response = configured.step(task, report, operation_key, expected_version,
            requirements_revision=requirements_revision, requirements_sha256=requirements_sha256)
    except ValueError:
        response = configured.failure("configuration-or-input-invalid")
    _output(ctx, response)


@cli.command()
@click.option("--task", required=True, help="Ключ назначенной задачи Workflow")
@click.option("--n", type=click.IntRange(min=1, max=200), default=None,
              help="Количество последних записей, не больше 200")
@click.option("--operation-key", default=None, help="Прочитать результат исходной операции")
@click.option("--execution-ref", default=None, help="Идентификатор исполнения из ответа Workflow")
@click.option("--before-history-id", type=click.IntRange(min=1, max=2**63 - 1), default=None,
              help="Следующая страница: значение next_before из предыдущего ответа")
@click.pass_context
def history_cmd(ctx: click.Context, task: str, n: int | None, operation_key: str | None,
                execution_ref: str | None, before_history_id: int | None) -> None:
    """Прочитать сохранённую историю и результат операции."""
    try:
        response = configured.history(task, n, operation_key, execution_ref, before_history_id)
    except ValueError:
        response = configured.failure("configuration-or-input-invalid")
    _output(ctx, response)
