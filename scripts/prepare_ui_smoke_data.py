#!/usr/bin/env python3
"""Prepare neutral multi-namespace data for UI screenshots and browser smoke."""

from __future__ import annotations

import sys
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from project_workflow.application.phase import PhaseServiceApp
from project_workflow.application.project import ProjectService
from project_workflow.application.task import TaskService
from project_workflow.application.workflow import WorkflowService
from project_workflow.config import DEFAULT_PROJECT_CODE, get_settings
from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db.session import (
    DatabaseRecreateRequired,
    DatabaseUnavailable,
    ensure_migrated,
    get_engine,
    initialization_transaction,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

TASK_KEY = "RUN-42"
QA_WORKFLOW_NAME = "Проверочный флоу"


def _configure_output_encoding() -> None:
    sample = "Smoke-данные UI подготовлены"
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None) or "utf-8"
        try:
            sample.encode(encoding)
        except (LookupError, UnicodeEncodeError):
            reconfigure = getattr(stream, "reconfigure", None)
            if callable(reconfigure):
                reconfigure(encoding="utf-8", errors="replace")


def _settings_error_message(exc: ValidationError) -> str:
    if any(tuple(error.get("loc", ())) == ("DATABASE_URL",) for error in exc.errors()):
        return "Переменная DATABASE_URL обязательна"
    return "Некорректная конфигурация"


def _workflow_by_name(uow: SAUnitOfWork, name: str) -> dict[str, Any] | None:
    return next((workflow.to_dict() for workflow in uow.workflows.list() if workflow.name == name), None)


def _namespace_by_command(uow: SAUnitOfWork, command: str) -> dict[str, Any] | None:
    namespace = uow.projects.get_by_cli_command(command)
    return namespace.to_dict() if namespace else None


def _ensure_bootstrap() -> None:
    settings = get_settings()
    engine = get_engine(settings.DATABASE_URL)
    with initialization_transaction(engine) as connection:
        ensure_migrated(connection)
        with SAUnitOfWork(connection) as uow:
            schema.ensure_phase_catalog(uow)
            bootstrap_default_project(uow)


def _ensure_qa_workflow(uow: SAUnitOfWork) -> int:
    workflow = _workflow_by_name(uow, QA_WORKFLOW_NAME)
    if workflow is None:
        workflow = WorkflowService(uow).create_workflow(
            {
                "name": QA_WORKFLOW_NAME,
                "description": "Нейтральный сценарий для проверки интерфейса.",
            }
        )
    workflow_id = int(workflow["id"])
    phase_service = PhaseServiceApp(uow)
    phases = phase_service.list_phases(workflow_id)
    if phases:
        phase_service.update_phase(
            int(phases[0]["id"]),
            {
                "name": "Проверка задачи",
                "description": "Зафиксировать сценарии проверки и результат.",
            },
        )
    if not any(phase["name"] == "Финальный отчёт" for phase in phase_service.list_phases(workflow_id)):
        phase_service.create_phase(
            {
                "workflow_id": workflow_id,
                "phase_order": len(phase_service.list_phases(workflow_id)) + 1,
                "name": "Финальный отчёт",
                "description": "Собрать выводы по проверке.",
            }
        )
    return workflow_id


def _ensure_namespace(
    uow: SAUnitOfWork,
    *,
    code: str,
    name: str,
    command: str,
    workflow_id: int,
    theme_icon: str,
    theme_color: str,
) -> dict[str, Any]:
    service = ProjectService(uow)
    namespace = _namespace_by_command(uow, command)
    if namespace is None and code == DEFAULT_PROJECT_CODE:
        default_namespace = uow.projects.get_by_code(DEFAULT_PROJECT_CODE)
        namespace = default_namespace.to_dict() if default_namespace else None
    payload = {
        "name": name,
        "description": "Нейтральные данные для проверки интерфейса.",
        "workflow_id": workflow_id,
        "theme_icon": theme_icon,
        "theme_color": theme_color,
        "cli_command": command,
    }
    if namespace is None:
        namespace = service.create_project({**payload, "code": code, "key_prefixes": []})
    else:
        service.update_project(int(namespace["id"]), payload)
        namespace = service.get_project(int(namespace["id"]))
        if namespace is None:
            raise RuntimeError("Не удалось обновить smoke-неймспейс")
    return namespace


def _ensure_task(uow: SAUnitOfWork, namespace: dict[str, Any], title: str) -> None:
    task_service = TaskService(uow)
    namespace_id = int(namespace["id"])
    existing = task_service.get_task_by_key(TASK_KEY, project_id=namespace_id)
    if existing is None:
        task_service.create_task({"project_id": namespace_id, "task_key": TASK_KEY, "title": title})
        return
    uow.tasks.update(int(existing["id"]), {"title": title, "status": "active"})
    uow.commit()


def prepare_smoke_data() -> None:
    _ensure_bootstrap()
    with SAUnitOfWork() as uow:
        default_workflow = next((workflow for workflow in uow.workflows.list() if workflow.is_default), None)
        if default_workflow is None or default_workflow.id is None:
            raise RuntimeError("Воркфлоу по умолчанию не найден")
        qa_workflow_id = _ensure_qa_workflow(uow)
        dev_namespace = _ensure_namespace(
            uow,
            code=DEFAULT_PROJECT_CODE,
            name="Разработка",
            command="workflow-dev",
            workflow_id=default_workflow.id,
            theme_icon="code",
            theme_color="#3B82F6",
        )
        qa_namespace = _ensure_namespace(
            uow,
            code="QA",
            name="Проверка качества",
            command="workflow-qa",
            workflow_id=qa_workflow_id,
            theme_icon="bug",
            theme_color="#22C55E",
        )
        _ensure_task(uow, dev_namespace, "Реализовать и проверить обработку задачи")
        _ensure_task(uow, qa_namespace, "Независимо проверить ту же внешнюю задачу")


def main() -> int:
    _configure_output_encoding()
    try:
        prepare_smoke_data()
    except ValidationError as exc:
        print(_settings_error_message(exc), file=sys.stderr)
        return 1
    except DatabaseRecreateRequired as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except DatabaseUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (SQLAlchemyError, OSError):
        print("Не удалось подготовить smoke-данные UI", file=sys.stderr)
        return 1
    print("Smoke-данные UI подготовлены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
