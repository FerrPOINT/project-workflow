"""Agent CLI: two commands over the configured Workflow API."""

from __future__ import annotations

from typing import Any

import click

from project_workflow.domain.background import BackgroundConclusion
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
@click.option("--task", default=None, help="Ключ назначенной задачи Workflow")
@click.option("--background-run", default=None, help="UUID фонового запуска Fleet без задачи Tracker")
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
@click.option("--research-result", default=None,
              help="Итог последней фоновой фазы: JSON status, summary, coverage, limitations")
@click.pass_context
def step_cmd(ctx: click.Context, task: str | None, report: str | None, operation_key: str | None,
             expected_version: int | None, requirements_revision: int | None,
             requirements_sha256: str | None, start: bool, workflow_id: int | None, mode_key: str | None,
             background_run: str | None = None, research_result: str | None = None) -> None:
    """Получить текущую фазу или отправить отчёт для оценки.

    Чтение: project-workflow --json step --task SDLC-42

    Отчёт через stdin: project-workflow --json step --task SDLC-42 --report -
    --operation-key phase-1-v1 --expected-version 1
    """
    if (task is None) == (background_run is None):
        raise click.UsageError("Укажите ровно один --task или --background-run")
    try:
        start_options: dict[str, Any] = {}
        if start or workflow_id is not None or mode_key is not None:
            start_options = {"start": start, "workflow_id": workflow_id, "mode_key": mode_key}
        if background_run is not None:
            start_options["background_run"] = background_run
        if research_result is not None:
            start_options["research_result"] = BackgroundConclusion.model_validate_json(research_result).model_dump(
                mode="json")
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
@click.option("--task", default=None, help="Ключ назначенной задачи Workflow")
@click.option("--background-run", default=None, help="UUID фонового запуска Fleet без задачи Tracker")
@click.option("--n", type=click.IntRange(min=1, max=200), default=None,
              help="Количество последних записей, не больше 200")
@click.option("--operation-key", default=None, help="Прочитать результат исходной операции")
@click.option("--execution-ref", default=None, help="Идентификатор исполнения из ответа Workflow")
@click.option("--before-history-id", type=click.IntRange(min=1, max=2**63 - 1), default=None,
              help="Следующая страница: значение next_before из предыдущего ответа")
@click.option("--diagnostics", is_flag=True, help="Диагностика одной оценки за страницу")
@click.pass_context
def history_cmd(ctx: click.Context, task: str | None, n: int | None, operation_key: str | None,
                execution_ref: str | None, before_history_id: int | None, diagnostics: bool = False,
                background_run: str | None = None) -> None:
    """Прочитать сохранённую историю и результат операции.

    История: project-workflow --json history --task SDLC-42 --n 20

    Результат исходной операции: project-workflow --json history --task SDLC-42
    --operation-key phase-1-v1
    """
    if (task is None) == (background_run is None):
        raise click.UsageError("Укажите ровно один --task или --background-run")
    try:
        options: dict[str, Any] = {}
        if diagnostics:
            options["diagnostics"] = True
        if background_run is not None:
            options["background_run"] = background_run
        response = configured.history(task, n, operation_key, execution_ref, before_history_id,
                                      **options)
    except ValueError:
        response = configured.failure("configuration-or-input-invalid")
    _output(ctx, response)
