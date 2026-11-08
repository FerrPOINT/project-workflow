"""Agent CLI: two commands over the configured Workflow API."""

from __future__ import annotations

from typing import Any

import click

from project_workflow.domain.phase_report import PhaseReportFormatError
from project_workflow.supervisor.formatting import format_result

from . import configured
from .core import cli, console, out_json


def _output(ctx: click.Context, response: dict[str, Any]) -> None:
    result, code = response["result"], response["exit_code"]
    if ctx.obj.get("json_mode", False):
        out_json(result, exit_code=code)
        return
    if (result.get("error_code") == "invalid-phase-report" and result.get("http_status") is None
            and result.get("acceptance_unknown") is False):
        output = "Отчёт не отправлен: локальная ошибка формата\n" + result["error"]
    else:
        output = format_result(result) if "verdict" in result else str(result.get("instructions", result))
    console.print(output, markup=False, highlight=False)
    raise click.exceptions.Exit(code)


@cli.command()
@click.option("--task", required=True, help="Ключ назначенной задачи Workflow")
@click.option("--report", default=None, help="JSON-отчёт: source, result, unresolved; - читает stdin")
@click.option("--start", is_flag=True, help="Явно начать самостоятельное исполнение")
@click.option("--workflow-id", type=click.IntRange(min=1), default=None, help="Workflow для --start")
@click.option("--mode-key", default=None, help="Режим Workflow для --start")
@click.option("--operation-key", default=None, help="Стабильный ключ операции отправки отчёта")
@click.option("--expected-version", type=click.IntRange(min=1), default=None,
              help="Версия из последнего ответа Workflow")
@click.option("--requirements-revision", type=click.IntRange(min=1), default=None,
              help="Подтверждённая редакция требований для финального PM отчёта")
@click.option("--requirements-sha256", default=None, help="Hash подтверждённой редакции требований")
@click.pass_context
def step_cmd(ctx: click.Context, task: str, report: str | None, operation_key: str | None,
             expected_version: int | None, requirements_revision: int | None,
             requirements_sha256: str | None, start: bool, workflow_id: int | None, mode_key: str | None) -> None:
    """Получить текущую фазу или отправить отчёт для оценки.

    Чтение: project-workflow --json step --task SDLC-42

    Отчёт через stdin: project-workflow --json step --task SDLC-42 --report -
    --operation-key phase-1-v1 --expected-version 1
    """
    try:
        start_options: dict[str, Any] = {}
        if start or workflow_id is not None or mode_key is not None:
            start_options = {"start": start, "workflow_id": workflow_id, "mode_key": mode_key}
        response = configured.step(task, report, operation_key, expected_version,
            requirements_revision=requirements_revision, requirements_sha256=requirements_sha256,
            **start_options)
    except PhaseReportFormatError as exc:
        response = configured.failure("invalid-phase-report")
        response["result"]["error"] = str(exc)
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
@click.option("--diagnostics", is_flag=True, help="Диагностика одной оценки за страницу")
@click.pass_context
def history_cmd(ctx: click.Context, task: str, n: int | None, operation_key: str | None,
                execution_ref: str | None, before_history_id: int | None, diagnostics: bool = False) -> None:
    """Прочитать сохранённую историю и результат операции.

    История: project-workflow --json history --task SDLC-42 --n 20

    Результат исходной операции: project-workflow --json history --task SDLC-42
    --operation-key phase-1-v1
    """
    try:
        response = configured.history(task, n, operation_key, execution_ref, before_history_id,
                                      **({"diagnostics": True} if diagnostics else {}))
    except ValueError:
        response = configured.failure("configuration-or-input-invalid")
    _output(ctx, response)
