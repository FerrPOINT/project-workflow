"""CLI commands — ровно 2 команды: step, history.

ПРАВИЛО CLI: новые CLI-команды ЗАПРЕЩЕНЫ.
Весь CRUD воркфлоу, фаз и профессий и администрирование выполняется через Web UI.
Если кто-то добавит @cli.command() сюда — тесты поймают
(см. test_ui.py::test_only_two_commands_allowed).

Разрешённые команды:
- step    --task RUN-42 [--report TEXT]
- history --task RUN-42 [--n N]
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import click
import requests

from ... import supervisor
from ...domain.exceptions import ConflictError
from ...infrastructure.db.uow import SAUnitOfWork
from ...supervisor import format_result
from .core import (
    NAMESPACE_ENV_VAR,
    WARN,
    _require_valid_key,
    _resolve_namespace_id_from_env,
    blocked_result,
    cli,
    console,
    out_json,
)

# ── Guard: новые команды запрещены ──────────────────────────────────────
# Если кто-то добавит @cli.command() сюда — тесты поймают.
# См. test_ui.py::test_only_two_commands_allowed


def _token_namespace_id() -> int | None:
    raw = os.environ.get(NAMESPACE_ENV_VAR)
    if raw is None or not raw.strip():
        return None
    selector = raw.strip()
    if not selector.isdecimal() or int(selector) <= 0:
        raise ValueError(f"{NAMESPACE_ENV_VAR} должен содержать положительный ID")
    return int(selector)


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND: step
# ═══════════════════════════════════════════════════════════════════════


def _platform_request(
    method: str, path: str, *, body: dict | None = None, params: dict | None = None,
    execution_token: str | None = None,
) -> dict:
    try:
        from sdlc_cli_core import ApiClient, ApiError
    except ImportError as exc:  # pragma: no cover - exercised via test_token_step_explains_missing_transport
        if execution_token is not None:
            raise ValueError("Runtime CLI требует sdlc-cli-core; DB fallback запрещён") from exc
        raise ValueError(
            "Токен-режим требует пакет sdlc-cli-core (services-base/python/cli-core); "
            "без него используйте локальный режим с DATABASE_URL"
        ) from exc

    try:
        service_url = os.environ.get("PROJECT_WORKFLOW_URL", "http://localhost:8812")
        if execution_token is not None:
            service_url = os.environ.get("PROJECT_WORKFLOW_URL", "").strip()
            if not service_url:
                raise ValueError("Runtime step требует явный PROJECT_WORKFLOW_URL; адрес по умолчанию запрещён")
        client = ApiClient(service_url)
        if execution_token is None:
            return client.request_json(method, path, body=body, params=params)
        # The shared PAT client cannot send the existing PM execution-scoped header.
        if method != "POST" or path != "internal/runtime/step" or params is not None:
            raise ValueError("Неподдерживаемый runtime CLI запрос")
        try:
            response = requests.request(
                method, urljoin(client.base_url, path), json=body, timeout=client.timeout, allow_redirects=False,
                headers={"Authorization": f"Bearer {client.token}", "Accept": "application/json",
                         "X-Workflow-Execution-Token": execution_token},
            )
            if not 200 <= response.status_code < 300:
                raise ValueError(f"Runtime step отклонён (HTTP {response.status_code}); не повторять вслепую")
            value = response.json()
        except (requests.RequestException, ValueError) as exc:
            # Never print a private response body, request or credential.
            if isinstance(exc, requests.RequestException):
                raise ValueError("Runtime step недоступен; принятие неизвестно, автоматического повтора нет") from exc
            raise ValueError("Runtime step не подтвердил результат; автоматического повтора нет") from exc
        if (not isinstance(value, dict) or type(value.get("ok")) is not bool
                or type(value.get("exit_code")) is not int or value["exit_code"] not in {0, 1}
                or value["ok"] != (value["exit_code"] == 0) or not isinstance(value.get("result"), dict)):
            raise ValueError("Runtime step вернул некорректный ответ")
        return value
    except ApiError as exc:
        raise ValueError(str(exc)) from exc


def _runtime_step_inputs(
    task: str, report: str | None, operation_key: str | None,
    runtime_request: Path | None, execution_token_file: Path | None,
) -> tuple[dict, str]:
    if not os.environ.get("SDLC_API_TOKEN", "").strip():
        raise ValueError("Runtime step требует SDLC_API_TOKEN; локальный DB fallback запрещён")
    if (not operation_key or operation_key != operation_key.strip() or len(operation_key) > 128
            or runtime_request is None or execution_token_file is None):
        raise ValueError("Runtime step требует --operation-key, --runtime-request и --execution-token-file")
    try:
        with runtime_request.open("rb") as source:
            raw = source.read(262_145)
        with execution_token_file.open("rb") as source:
            token_bytes = source.read(129)
        if len(raw) > 262_144 or len(token_bytes) > 128:
            raise ValueError
        body = json.loads(raw)
        token = token_bytes.decode("ascii").strip()
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError("Некорректные runtime request/token inputs") from exc
    if (not isinstance(body, dict) or body.get("task") != task or body.get("report") != report
            or body.get("step_operation_key") != operation_key or re.fullmatch(r"[0-9a-f]{64}", token) is None):
        raise ValueError("Runtime request не совпадает с task/report/operation key или scoped token некорректен")
    # Forward the existing RuntimeStepRequest unchanged; the server validates its full fence.
    return body, token


@cli.command()
@click.option("--task", required=True, help="Ключ задачи (например, RUN-42)")
@click.option("--report", default=None, help="Отчёт исполнителя CLI (оценить и перейти)")
@click.option("--operation-key", default=None, help="Исходный step_operation_key назначенного runtime step")
@click.option("--runtime-request", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None, help="Замороженный JSON существующего RuntimeStepRequest, включая полный fence")
@click.option("--execution-token-file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None, help="Приватный файл scoped token из actual PM bind/resume receipt")
@click.pass_context
def step_cmd(
    ctx: click.Context,
    task: str,
    report: str | None,
    operation_key: str | None,
    runtime_request: Path | None,
    execution_token_file: Path | None,
) -> None:
    """Движение по workflow: показать текущую фазу или отчитаться и перейти.

    Примеры:
      project-workflow step --task RUN-42                -> текущие инструкции
      project-workflow step --task RUN-42 --report "..."  -> оценить отчёт исполнителя CLI и перейти
    """
    jmode = ctx.obj.get("json_mode", False)
    if report is not None and not report.strip():
        result = blocked_result(task, "Отчёт не может быть пустым")
        if jmode:
            out_json(result, exit_code=1)
            return
        console.print(format_result(result))
        raise click.exceptions.Exit(1)
    machine = any(value is not None for value in (operation_key, runtime_request, execution_token_file))
    if machine or os.environ.get("SDLC_API_TOKEN"):
        try:
            if machine:
                body, execution_token = _runtime_step_inputs(
                    task, report, operation_key, runtime_request, execution_token_file,
                )
                response = _platform_request(
                    "POST", "internal/runtime/step", body=body, execution_token=execution_token,
                )
            else:
                body = {"task": task, "report": report}
                namespace_id = _token_namespace_id()
                if namespace_id is not None:
                    body["namespace_id"] = namespace_id
                response = _platform_request("POST", "api/cli/step", body=body)
        except ValueError as exc:
            response = {"ok": False, "exit_code": 1, "output": str(exc), "result": blocked_result(task, str(exc))}
        result = response.get("result", response)
        exit_code = int(response.get("exit_code", 0 if response.get("ok") else 1))
        if jmode:
            out_json(result, exit_code=exit_code)
            return
        console.print(str(response.get("output", result)))
        if exit_code:
            raise click.exceptions.Exit(exit_code)
        return
    uow: SAUnitOfWork | None = None
    try:
        uow = SAUnitOfWork()
        project_id = _resolve_namespace_id_from_env(uow)
        task_key = _require_valid_key(task, uow, project_id=project_id)
        engine = supervisor.SupervisorEngine(task_key, uow=uow, project_id=project_id)
    except (ConflictError, RuntimeError, ValueError) as exc:
        if uow is not None:
            uow.close()
        result = blocked_result(task, str(exc))
        if jmode:
            out_json(result, exit_code=1)
            return
        console.print(format_result(result))
        raise click.exceptions.Exit(1) from exc

    try:
        # --report : evaluate report
        if report is not None:
            result = engine.evaluate(report)
            if jmode:
                out_json(result, exit_code=1 if result["verdict"] == "BLOCKED" else 0)
                return
            console.print(format_result(result))
            raise click.exceptions.Exit(1 if result["verdict"] == "BLOCKED" else 0)

        if engine._get_current_phase_obj() is None:
            result = engine._blocked_result()
            if jmode:
                out_json(result, exit_code=1)
                return
            console.print(format_result(result))
            raise click.exceptions.Exit(1)

        # default: show phase prompt/instructions
        prompt = engine.get_phase_prompt()
        phase_contract = engine.get_phase_contract()
        if jmode:
            # For completed tasks return a compact contract without the heavy prompt.
            if engine.task and engine.task.get("status") == "done":
                out_json(
                    {
                        "ok": True,
                        "task_key": task_key,
                        "phase_code": engine.current_phase_code,
                        "status": "done",
                        "instructions": engine.format_current_phase_instructions(),
                        "phase_contract": phase_contract,
                        "next_phase_code": None,
                    }
                )
                return
            out_json(
                {
                    "ok": True,
                    "task_key": task_key,
                    "phase_code": engine.current_phase_code,
                    "prompt": prompt,
                    "phase_contract": phase_contract,
                }
            )
            return
        instructions = engine.format_current_phase_instructions()
        console.print(instructions)
        return
    finally:
        if uow is not None:
            uow.close()


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND: history
# ═══════════════════════════════════════════════════════════════════════


@cli.command()
@click.option("--task", required=True, help="Ключ задачи")
@click.option("--n", type=click.IntRange(min=1), default=None, help="Количество записей (по умолчанию: все)")
@click.pass_context
def history_cmd(
    ctx: click.Context,
    task: str,
    n: int | None,
) -> None:
    """История отчётов, переходов и статусов по задаче.

    Примеры:
      project-workflow history --task RUN-42            -> все записи
      project-workflow history --task RUN-42 --n 50     -> последние 50 записей
    """
    jmode = ctx.obj.get("json_mode", False)
    if os.environ.get("SDLC_API_TOKEN"):
        try:
            params = {"task": task, "n": n}
            namespace_id = _token_namespace_id()
            if namespace_id is not None:
                params["namespace_id"] = namespace_id
            response = _platform_request("GET", "api/cli/history", params=params)
        except ValueError as exc:
            result = blocked_result(task, str(exc))
            if jmode:
                out_json(result, exit_code=1)
                return
            console.print(format_result(result))
            raise click.exceptions.Exit(1) from exc
        result = response.get("result", response)
        if jmode:
            out_json({"ok": True, **result})
            return
        records = result.get("records", [])
        if not records:
            console.print(f"{WARN} История для {task} пуста.")
        else:
            console.print(f"[bold]История: {task}[/bold] (последние {len(records)} записей)")
            for record in records:
                phase = record.get("phase_code", "-")
                verdict = record.get("verdict", "-")
                created_at = record.get("created_at", "-")
                console.print(f"{phase} · {verdict} · {created_at}")
        return
    try:
        with SAUnitOfWork() as uow:
            project_id = _resolve_namespace_id_from_env(uow)
            task_key = _require_valid_key(task, uow, project_id=project_id)
            task_obj = uow.tasks.get_by_key(task_key, project_id=project_id)
            task_id = task_obj.id if task_obj else None
            runs_raw = uow.step_history.list(
                task_id=task_id,
                task_key=task_key,
                project_id=project_id,
                limit=n,
            )
            runs: list[dict[str, Any]] = []
            for raw in runs_raw:
                rd: dict[str, Any] = raw.to_dict()
                next_phase_id = rd.get("next_phase_id")
                rollback_phase_id = rd.get("rollback_phase_id")
                evaluated_phase = uow.phases.get_by_id(int(rd.get("phase_id") or 0))
                next_phase = uow.phases.get_by_id(int(next_phase_id)) if next_phase_id is not None else None
                rollback_phase = uow.phases.get_by_id(int(rollback_phase_id)) if rollback_phase_id is not None else None
                if evaluated_phase is None:
                    raise ValueError("История step ссылается на неизвестную фазу")
                rd["phase_code"] = evaluated_phase.code
                rd["next_phase_code"] = next_phase.code if next_phase else None
                rd["rollback_phase_code"] = rollback_phase.code if rollback_phase else None
                runs.append(rd)
    except (ConflictError, RuntimeError, ValueError) as exc:
        result = blocked_result(task, str(exc))
        if jmode:
            out_json(result, exit_code=1)
            return
        console.print(format_result(result))
        raise click.exceptions.Exit(1) from exc

    if jmode:
        out_json(
            {
                "ok": True,
                "task_key": task_key,
                "count": len(runs),
                "records": [
                    {
                        "phase_code": r.get("phase_code"),
                        "verdict": r.get("verdict"),
                        "worker_report": r.get("worker_report"),
                        "supervisor_message": (r.get("supervisor_response") or {}).get("message"),
                        "next_phase_code": r.get("next_phase_code"),
                        "rollback_phase_code": r.get("rollback_phase_code"),
                        "created_at": r.get("created_at"),
                    }
                    for r in runs
                ],
            }
        )
        return

    if not runs:
        console.print(f"{WARN} История для {task_key} пуста.")
        return

    console.print(f"[bold]История: {task_key}[/bold] (последние {len(runs)} записей)\n")
    for r in runs:
        verdict = r.get("verdict")
        verdict_label = "ПРОЙДЕНО" if verdict == "pass" else "ОТКАТ" if verdict == "rollback" else "ПРОВЕРКА"
        phase_code = r.get("phase_code", "-")
        next_phase_code = r.get("next_phase_code") or "—"
        rollback_phase_code = r.get("rollback_phase_code") or "—"
        created_at = r.get("created_at", "-")
        console.print(
            f"{verdict_label} [{created_at}] Фаза {phase_code} -> {next_phase_code} "
            f"(откат: {rollback_phase_code})"
        )
        console.print(f"  Отчёт исполнителя: {r.get('worker_report') or '—'}")
        response = r.get("supervisor_response") or {}
        console.print(f"  Ответ Supervisor: {response.get('message') or '—'}")
