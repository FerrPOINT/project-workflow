#!/usr/bin/env python3
"""Prepare neutral multi-namespace data for UI screenshots and browser checks."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from project_workflow.application.phase import PhaseServiceApp
from project_workflow.application.project import ProjectService
from project_workflow.application.task import TaskService
from project_workflow.application.workflow import WorkflowService
from project_workflow.config import DEFAULT_PROJECT_CODE, get_settings
from project_workflow.infrastructure.db import models as m
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
DEFAULT_DEMO_WORKFLOW_NAME = "Воркфлоу разработки"
QA_WORKFLOW_NAME = "Воркфлоу проверки"
TASK_SCENARIOS = {
    "workflow-dev": [
        {
            "key": TASK_KEY,
            "title": "Реализовать проверяемое изменение",
            "status": "active",
            "current_order": 4,
            "verdict": "partial",
        },
        {
            "key": "RUN-77",
            "title": "Закрыть замечания по ревью",
            "status": "blocked",
            "current_order": 7,
            "verdict": "blocked",
        },
        {
            "key": "RUN-88",
            "title": "Обновить документацию запуска",
            "status": "done",
            "current_order": -1,
            "verdict": "pass",
        },
        {
            "key": "RUN-105",
            "title": "Проверить миграцию данных",
            "status": "active",
            "current_order": 10,
            "verdict": "pass",
        },
        {
            "key": "RUN-120",
            "title": "Проверить набор экранов интерфейса",
            "status": "blocked",
            "current_order": 12,
            "verdict": "blocked",
        },
        {
            "key": "RUN-130",
            "title": "Сверить API-ответы с интерфейсом",
            "status": "active",
            "current_order": 13,
            "verdict": "partial",
        },
        {
            "key": "RUN-143",
            "title": "Подготовить регрессионный прогон",
            "status": "active",
            "current_order": 8,
            "verdict": "pass",
        },
        {
            "key": "RUN-160",
            "title": "Закрыть финальную приёмку",
            "status": "done",
            "current_order": -1,
            "verdict": "pass",
        },
        {
            "key": "RUN-171",
            "title": "Собрать риски релиза",
            "status": "blocked",
            "current_order": 14,
            "verdict": "blocked",
        },
        {
            "key": "RUN-180",
            "title": "Проверить пакет CLI",
            "status": "active",
            "current_order": 11,
            "verdict": "pass",
        },
        {
            "key": "RUN-190",
            "title": "Сверить страницу списка задач",
            "status": "active",
            "current_order": 12,
            "verdict": "partial",
        },
        {
            "key": "RUN-205",
            "title": "Повторить smoke-прогон",
            "status": "blocked",
            "current_order": 13,
            "verdict": "blocked",
        },
        {
            "key": "RUN-215",
            "title": "Передать UX-сценарий на ревью",
            "status": "active",
            "current_order": 15,
            "verdict": "delegate",
        },
        {
            "key": "RUN-225",
            "title": "Проверить сценарий отката",
            "status": "active",
            "current_order": 9,
            "verdict": "rollback",
        },
        {
            "key": "RUN-240",
            "title": "Дособрать подтверждения по задаче",
            "status": "active",
            "current_order": 16,
            "verdict": "partial",
        },
        {
            "key": "RUN-255",
            "title": "Проверить отказоустойчивость запуска",
            "status": "blocked",
            "current_order": 17,
            "verdict": "blocked",
        },
        {
            "key": "RUN-270",
            "title": "Закрыть ручной сценарий проверки",
            "status": "done",
            "current_order": -1,
            "verdict": "pass",
        },
        {
            "key": "RUN-285",
            "title": "Проверить независимый запуск потока",
            "status": "active",
            "current_order": 18,
            "verdict": "pass",
        },
    ],
    "workflow-qa": [
        {
            "key": TASK_KEY,
            "title": "Независимо проверить ту же внешнюю задачу",
            "status": "active",
            "current_order": 3,
            "verdict": "partial",
        },
        {
            "key": "RUN-77",
            "title": "Проверить исправления после ревью",
            "status": "active",
            "current_order": 2,
            "verdict": "pass",
        },
        {
            "key": "RUN-88",
            "title": "Подтвердить готовность документации",
            "status": "done",
            "current_order": -1,
            "verdict": "pass",
        },
        {
            "key": "RUN-120",
            "title": "Проверить набор экранов интерфейса",
            "status": "blocked",
            "current_order": 4,
            "verdict": "blocked",
        },
        {
            "key": "RUN-105",
            "title": "Проверить миграцию данных",
            "status": "active",
            "current_order": 4,
            "verdict": "pass",
        },
        {
            "key": "RUN-130",
            "title": "Сверить API-ответы с интерфейсом",
            "status": "active",
            "current_order": 3,
            "verdict": "partial",
        },
        {
            "key": "RUN-143",
            "title": "Подготовить регрессионный прогон",
            "status": "active",
            "current_order": 4,
            "verdict": "pass",
        },
        {
            "key": "RUN-160",
            "title": "Закрыть финальную приёмку",
            "status": "done",
            "current_order": -1,
            "verdict": "pass",
        },
        {
            "key": "RUN-171",
            "title": "Собрать риски релиза",
            "status": "blocked",
            "current_order": 5,
            "verdict": "blocked",
        },
        {
            "key": "RUN-180",
            "title": "Проверить пакет CLI",
            "status": "active",
            "current_order": 4,
            "verdict": "pass",
        },
        {
            "key": "RUN-190",
            "title": "Сверить страницу списка задач",
            "status": "blocked",
            "current_order": 5,
            "verdict": "blocked",
        },
        {
            "key": "RUN-205",
            "title": "Повторить smoke-прогон",
            "status": "active",
            "current_order": 6,
            "verdict": "partial",
        },
        {
            "key": "RUN-215",
            "title": "Проверить передачу UX-сценария",
            "status": "active",
            "current_order": 5,
            "verdict": "delegate",
        },
        {
            "key": "RUN-225",
            "title": "Подтвердить сценарий отката",
            "status": "active",
            "current_order": 4,
            "verdict": "rollback",
        },
        {
            "key": "RUN-240",
            "title": "Дособрать проверочные подтверждения",
            "status": "active",
            "current_order": 6,
            "verdict": "partial",
        },
        {
            "key": "RUN-255",
            "title": "Проверить отказоустойчивость запуска",
            "status": "blocked",
            "current_order": 5,
            "verdict": "blocked",
        },
        {
            "key": "RUN-270",
            "title": "Закрыть ручной сценарий проверки",
            "status": "done",
            "current_order": -1,
            "verdict": "pass",
        },
        {
            "key": "RUN-285",
            "title": "Проверить независимый запуск потока",
            "status": "active",
            "current_order": 6,
            "verdict": "pass",
        },
    ],
}
QA_PHASES = [
    ("Проверка сценариев", "Зафиксировать ожидаемое поведение и границы проверки."),
    ("Проверка интерфейса", "Открыть ключевые страницы и сверить состояние с данными."),
    ("Проверка API", "Сверить ответы JSON с тем, что показывает интерфейс."),
    ("Регрессия", "Повторить критичные сценарии после исправлений."),
    ("Отчёт о рисках", "Собрать замечания, риски и подтверждения."),
    ("Финальный отчёт", "Зафиксировать итог проверки."),
]
DEMO_AGENT_PROFILES: dict[str, dict[str, Any]] = {
    "orchestrator": {
        "name": "Координатор",
        "description": "Ведёт постановку задачи, синхронизирует переходы и фиксирует решения.",
        "hermes_profile": "launch-coordinator",
    },
    "codex-operator": {
        "name": "Оператор",
        "description": "Проверяет план, слияние и ручные решения перед переходом дальше.",
        "hermes_profile": None,
    },
    "ops": {
        "name": "Инженер запуска",
        "description": "Отвечает за окружение, миграции, smoke-проверки и готовность приложения.",
        "hermes_profile": "launch-runtime",
    },
    "researcher": {
        "name": "Аналитик",
        "description": "Разбирает поток данных, зависимости и фактическое поведение системы.",
        "hermes_profile": "launch-analyst",
    },
    "critic": {
        "name": "Контролёр качества",
        "description": "Ищет риски, пропуски в плане и слабые места регрессионного покрытия.",
        "hermes_profile": "launch-quality",
    },
    "coder": {
        "name": "Разработчик",
        "description": "Вносит минимальные изменения, добавляет тесты и готовит проверяемый результат.",
        "hermes_profile": "launch-developer",
    },
    "reviewer": {
        "name": "Ревьюер",
        "description": "Проверяет реализацию, архитектурные границы и отсутствие лишней сложности.",
        "hermes_profile": "launch-review",
    },
}
DEMO_AGENT_PROFILES_BY_DISPLAY_NAME = {
    str(profile["name"]): profile for profile in DEMO_AGENT_PROFILES.values()
}


def _assert_smoke_database_url(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        raise RuntimeError("Для UI smoke укажите отдельную SQLite-базу .smoke/ui-smoke.db")
    if url.database in (None, "", ":memory:"):
        return
    db_path = Path(url.database)
    parts = {part.casefold() for part in db_path.parts}
    if db_path.name.casefold() != "ui-smoke.db" and ".smoke" not in parts:
        raise RuntimeError("Для UI smoke укажите отдельную SQLite-базу .smoke/ui-smoke.db")


def _neutral_profile_name(agent_name: str, agent_id: int) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", agent_name.casefold()).strip("-_")
    return f"launch-{normalized or 'agent'}-{agent_id}"


def _configure_output_encoding() -> None:
    sample = "Демо-данные UI подготовлены"
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
    _assert_smoke_database_url(settings.DATABASE_URL)
    engine = get_engine(settings.DATABASE_URL)
    with initialization_transaction(engine) as connection:
        ensure_migrated(connection)
        with SAUnitOfWork(connection) as uow:
            schema.ensure_phase_catalog(uow)
            bootstrap_default_project(uow)


def _reset_smoke_rows(uow: SAUnitOfWork) -> None:
    uow.session.execute(delete(m.TaskPhaseEvent))
    uow.session.execute(delete(m.TaskStepHistoryEntry))
    uow.session.execute(delete(m.Task))
    uow.session.execute(delete(m.Project).where(m.Project.code != DEFAULT_PROJECT_CODE))
    uow.session.execute(delete(m.Workflow).where(m.Workflow.is_default == 0))
    referenced_agent_ids = [
        int(agent_id)
        for (agent_id,) in uow.session.execute(select(m.Phase.agent_id).where(m.Phase.agent_id.is_not(None)))
        if agent_id is not None
    ]
    if referenced_agent_ids:
        uow.session.execute(delete(m.Agent).where(m.Agent.id.not_in(referenced_agent_ids)))
    else:
        uow.session.execute(delete(m.Agent))
    uow.commit()


def _ensure_qa_workflow(uow: SAUnitOfWork) -> int:
    workflow = _workflow_by_name(uow, QA_WORKFLOW_NAME)
    if workflow is None:
        workflow = WorkflowService(uow).create_workflow(
            {
                "name": QA_WORKFLOW_NAME,
                "description": "Нейтральный сценарий проверки интерфейса, API и регрессии.",
            }
        )
    workflow_id = int(workflow["id"])
    phase_service = PhaseServiceApp(uow)
    for order, (name, description) in enumerate(QA_PHASES, start=1):
        phases = phase_service.list_phases(workflow_id)
        existing = next((phase for phase in phases if phase["phase_order"] == order), None)
        if existing is None:
            phase_service.create_phase(
                {
                    "workflow_id": workflow_id,
                    "phase_order": order,
                    "name": name,
                    "description": description,
                }
            )
            continue
        phase_service.update_phase(
            int(existing["id"]),
            {
                "name": name,
                "description": description,
            }
        )
    return workflow_id


def _ensure_default_demo_workflow(uow: SAUnitOfWork) -> dict[str, Any]:
    workflow = next((item.to_dict() for item in uow.workflows.list() if item.is_default), None)
    if workflow is None:
        raise RuntimeError("Воркфлоу по умолчанию не найден")
    workflow_id = int(workflow["id"])
    payload = {
        "name": DEFAULT_DEMO_WORKFLOW_NAME,
        "description": "Нейтральный сценарий разработки для проверки интерфейса.",
    }
    if workflow.get("name") != payload["name"] or workflow.get("description") != payload["description"]:
        WorkflowService(uow).update_workflow(workflow_id, payload)
        workflow = WorkflowService(uow).get_workflow(workflow_id)
        if workflow is None:
            raise RuntimeError("Не удалось обновить демо-воркфлоу")
    return workflow


def _neutralize_agents(uow: SAUnitOfWork) -> None:
    for agent in uow.agents.list():
        if agent.id is None:
            continue
        demo_agent = DEMO_AGENT_PROFILES.get(agent.name) or DEMO_AGENT_PROFILES_BY_DISPLAY_NAME.get(agent.name)
        if demo_agent is None:
            if agent.hermes_profile is None:
                continue
            neutral_profile = _neutral_profile_name(agent.name, int(agent.id))
            if agent.hermes_profile == neutral_profile:
                continue
            uow.agents.update(int(agent.id), {"hermes_profile": neutral_profile})
            continue
        uow.agents.update(int(agent.id), demo_agent)
    uow.commit()


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
            raise RuntimeError("Не удалось обновить демо-неймспейс")
    return namespace


def _phase_by_order(phases: list[dict[str, Any]], order: int) -> dict[str, Any]:
    index = len(phases) + order + 1 if order < 0 else order
    phase = next((item for item in phases if item["phase_order"] == index), None)
    if phase is None:
        raise RuntimeError(f"Фаза с порядком {order} не найдена")
    return phase


def _reset_task_history(uow: SAUnitOfWork, task_id: int) -> None:
    uow.session.execute(delete(m.TaskPhaseEvent).where(m.TaskPhaseEvent.task_id == task_id))
    uow.session.execute(delete(m.TaskStepHistoryEntry).where(m.TaskStepHistoryEntry.task_id == task_id))
    uow.session.flush()


def _record_demo_step(
    uow: SAUnitOfWork,
    *,
    task_id: int,
    phase: dict[str, Any],
    verdict: str,
    report: str,
    next_phase: dict[str, Any] | None = None,
) -> int:
    phase_name = str(phase["name"])
    phase_code = str(phase["code"])
    missing = ["Нужно приложить подтверждение результата"] if verdict == "partial" else []
    blockers = ["Ожидается ручное подтверждение владельца"] if verdict == "blocked" else []
    covered = [] if verdict == "blocked" else ["Сценарий выполнен", "Результат сверён с интерфейсом"]
    messages = {
        "pass": "Проверка принята",
        "partial": "Нужна доработка",
        "blocked": "Нужна доработка",
        "delegate": "Передать проверку назначенному участнику",
        "rollback": "Нужен откат к предыдущему шагу",
    }
    response: dict[str, Any] = {
        "covered": covered,
        "missing": missing,
        "blockers": blockers,
        "message": messages.get(verdict, "Нужна доработка"),
    }
    if verdict == "delegate":
        response["delegate_agent"] = "Ревьюер"
    if verdict == "rollback":
        response["rollback_phase_code"] = phase_code
    if next_phase is not None:
        response["next_phase_contract"] = {
            "phase_code": next_phase["code"],
            "phase_name": next_phase["name"],
            "description": next_phase.get("description", ""),
            "instructions": ["Выполнить следующий шаг и зафиксировать результат"],
            "required_checks": ["Результат проверен"],
            "required_evidence": ["Ссылка или краткое подтверждение"],
        }
    return uow.record_step(
        task_id=task_id,
        phase_id=int(phase["id"]),
        verdict=verdict,
        worker_report=report,
        covered_item_ids=covered,
        missing_item_ids=missing,
        blocker_messages=blockers,
        next_phase_id=int(next_phase["id"]) if next_phase is not None and verdict == "pass" else None,
        rollback_phase_id=None,
        replay_fingerprint=f"ui-demo-{task_id}-{phase['id']}-{verdict}",
        evaluation_snapshot={
            "phase_code": phase_code,
            "phase_name": phase_name,
            "contract_snapshot": {
                "phase_code": phase_code,
                "phase_name": phase_name,
            },
        },
        supervisor_response=response,
    )


def _apply_task_scenario(uow: SAUnitOfWork, namespace: dict[str, Any], scenario: dict[str, Any]) -> None:
    task_service = TaskService(uow)
    namespace_id = int(namespace["id"])
    workflow_id = int(namespace["workflow_id"])
    phases = sorted(
        (phase.to_dict() for phase in uow.phases.list(workflow_id=workflow_id)),
        key=lambda item: item["phase_order"],
    )
    current_phase = _phase_by_order(phases, int(scenario["current_order"]))
    existing = task_service.get_task_by_key(str(scenario["key"]), project_id=namespace_id)
    if existing is None:
        task = task_service.create_task(
            {
                "project_id": namespace_id,
                "task_key": scenario["key"],
                "title": scenario["title"],
                "current_phase_id": int(current_phase["id"]),
            }
        )
        task_id = int(task["id"])
    else:
        task_id = int(existing["id"])
        uow.tasks.update(
            task_id,
            {
                "title": scenario["title"],
                "status": "active",
                "current_phase_id": int(phases[0]["id"]),
            },
        )
        uow.commit()

    _reset_task_history(uow, task_id)
    completed_phases = [
        phase for phase in phases if int(phase["phase_order"]) < int(current_phase["phase_order"])
    ]
    for index, phase in enumerate(completed_phases):
        next_phase = phases[index + 1] if index + 1 < len(phases) else None
        step_id = _record_demo_step(
            uow,
            task_id=task_id,
            phase=phase,
            verdict="pass",
            report=f"{scenario['key']}: этап '{phase['name']}' выполнен.",
            next_phase=next_phase,
        )
        uow.tasks.record_phase_event(task_id, int(phase["id"]), "completed", step_history_id=step_id)

    final_status = str(scenario["status"])
    latest_verdict = str(scenario["verdict"])
    if final_status == "blocked":
        step_id = _record_demo_step(
            uow,
            task_id=task_id,
            phase=current_phase,
            verdict="blocked",
            report=f"{scenario['key']}: нужен ответ по открытому вопросу.",
        )
        uow.tasks.record_phase_event(task_id, int(current_phase["id"]), "blocked", step_history_id=step_id)
    elif final_status == "done":
        last_phase = phases[-1]
        if last_phase not in completed_phases:
            step_id = _record_demo_step(
                uow,
                task_id=task_id,
                phase=last_phase,
                verdict="pass",
                report=f"{scenario['key']}: финальная проверка завершена.",
            )
            uow.tasks.record_phase_event(task_id, int(last_phase["id"]), "completed", step_history_id=step_id)
        current_phase = last_phase
    else:
        uow.tasks.record_phase_event(task_id, int(current_phase["id"]), "entered")
        if latest_verdict != "pass":
            step_id = _record_demo_step(
                uow,
                task_id=task_id,
                phase=current_phase,
                verdict=latest_verdict,
                report=f"{scenario['key']}: часть работ готова, остаток зафиксирован.",
            )
            uow.tasks.record_phase_event(task_id, int(current_phase["id"]), "resumed", step_history_id=step_id)

    uow.tasks.update(
        task_id,
        {
            "title": scenario["title"],
            "status": final_status,
            "current_phase_id": int(current_phase["id"]),
        },
    )
    uow.commit()


def _ensure_tasks(uow: SAUnitOfWork, namespace: dict[str, Any]) -> None:
    command = str(namespace["cli_command"])
    for scenario in TASK_SCENARIOS[command]:
        _apply_task_scenario(uow, namespace, scenario)


def prepare_smoke_data() -> None:
    _ensure_bootstrap()
    with SAUnitOfWork() as uow:
        _reset_smoke_rows(uow)
        _neutralize_agents(uow)
        default_workflow = _ensure_default_demo_workflow(uow)
        qa_workflow_id = _ensure_qa_workflow(uow)
        dev_namespace = _ensure_namespace(
            uow,
            code=DEFAULT_PROJECT_CODE,
            name="Разработка",
            command="workflow-dev",
            workflow_id=int(default_workflow["id"]),
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
        _ensure_tasks(uow, dev_namespace)
        _ensure_tasks(uow, qa_namespace)


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
        print("Не удалось подготовить демо-данные UI", file=sys.stderr)
        return 1
    print("Демо-данные UI подготовлены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
