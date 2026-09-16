#!/usr/bin/env python3
"""Нагоняем много данных в SQLite smoke-базу для UI/UX-проверки списков.

Использует те же сервисные вызовы, что и prepare_ui_smoke_data.py, но:
- 3 неймспейса вместо 2 (включая длинные имена/команды);
- 40+ задач на неймспейс со всеми статусами/вердиктами и длинными текстами;
- 3 воркфлоу, включая длинный с параллельными группами;
- больше агентов и длинные описания;
- длинные названия фаз/шагов для проверки переполнения.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", f"sqlite:///{ROOT / '.smoke/ui-smoke.db'}")

from sqlalchemy import select  # noqa: E402

from project_workflow.application.phase import PhaseServiceApp  # noqa: E402
from project_workflow.application.task import TaskService  # noqa: E402
from project_workflow.application.workflow import WorkflowService  # noqa: E402
from project_workflow.config import get_settings  # noqa: E402
from project_workflow.infrastructure.db import models as m  # noqa: E402
from project_workflow.infrastructure.db import schema  # noqa: E402
from project_workflow.infrastructure.db.session import (  # noqa: E402
    ensure_migrated,
    get_engine,
    initialization_transaction,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork  # noqa: E402
from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project  # noqa: E402


def _sorted_phases(uow: SAUnitOfWork, workflow_id: int) -> list[Any]:
    return sorted(
        uow.phases.list(workflow_id=workflow_id),
        key=lambda p: int(p.phase_order or 0),
    )


def _records(uow: SAUnitOfWork, model: Any, **filters: Any) -> list[Any]:
    stmt = select(model)
    for key, value in filters.items():
        stmt = stmt.where(getattr(model, key) == value)
    return list(uow.session.execute(stmt).scalars())


def _workflow_ids(workflows: Sequence[Any]) -> list[int]:
    """Return only persisted workflow identifiers for fixture references."""
    return [workflow.id for workflow in workflows if workflow.id is not None]


def seed() -> None:
    settings = get_settings()
    engine = get_engine(settings.DATABASE_URL)
    with initialization_transaction(engine) as connection:
        ensure_migrated(connection)
        with SAUnitOfWork(connection) as uow:
            schema.ensure_phase_catalog(uow)
            bootstrap_default_project(uow)

    with SAUnitOfWork() as uow:
        # ── воркфлоу: 3 штуки, разные размеры ────────────────────────────
        wf_service = WorkflowService(uow)
        existing = {w.name: w.id for w in uow.workflows.list()}
        long_name = ("Воркфлоу полного цикла поставки с параллельной проверкой "
                     "и финальной приёмкой результата")
        if long_name not in existing:
            wf_service.create_workflow({
                "name": long_name,
                "description": "Длинное описание воркфлоу для проверки переносов и переполнения ячеек в списках.",
            })
            uow.commit()
        wf_ids = _workflow_ids(uow.workflows.list())

        # ── агенты: 10 с длинными описаниями ─────────────────────────────
        agent_rows = [
            ("Координатор", "run-coord",
             "Ведёт постановку задачи, синхронизирует переходы между фазами и фиксирует решения."),
            ("Оператор", "run-operator", "Проверяет план, слияние и ручные решения перед переходом дальше."),
            ("Инженер запуска", "run-runtime",
             "Отвечает за окружение, миграции, контрольные проверки и готовность приложения."),
            ("Аналитик", "run-analysis", "Разбирает поток данных, зависимости и фактическое поведение системы."),
            ("Контролёр качества", "run-quality",
             "Ищет риски, пропуски в плане и слабые места регрессионного покрытия."),
            ("Разработчик", "run-dev",
             "Вносит минимальные изменения, добавляет тесты и готовит проверяемый результат."),
            ("Ревьюер", "run-review",
             "Проверяет реализацию, архитектурные границы и отсутствие лишней сложности."),
            ("Технический писатель с очень длинным именем", None,
             "Поддерживает документацию, README и инструкции запуска в актуальном состоянии."),
            ("Инженер по надёжности", "run-sre",
             "Наблюдает за метриками, инцидентами и деградациями, готовит постмортемы."),
            ("Архитектор платформы", "run-arch",
             "Отвечает за границы модулей, контракты API и технический долг."),
        ]
        have = {a.name: a for a in uow.agents.list()}
        for name, profile, desc in agent_rows:
            if name in have:
                uow.agents.update(int(have[name].id or 0), {"description": desc})
            else:
                uow.agents.create({"name": name, "description": desc, "hermes_profile": profile})
        uow.commit()
        agents = {a.name: int(a.id or 0) for a in uow.agents.list()}

        # ── фазы в новом длинном воркфлоу: 10, с парой параллельных ──────
        phase_service = PhaseServiceApp(uow)
        long_wf = next((w for w in uow.workflows.list() if int(w.id or 0) == wf_ids[-1]), None)
        if long_wf and not uow.phases.list(workflow_id=int(long_wf.id or 0)):
            phase_defs = [
                ("Поступление требований и первичный разбор", "sync", "Координатор"),
                ("Проектирование решения и оценка рисков", "sync", "Архитектор платформы"),
                ("Реализация изменения с тестами", "sync", "Разработчик"),
                ("Самопроверка реализации исполнителем", "parallel", "Разработчик"),
                ("Независимое ревью изменения", "parallel", "Ревьюер"),
                ("Подготовка документации к поставке", "parallel", "Технический писатель с очень длинным именем"),
                ("Интеграционная проверка и регрессия", "sync", "Контролёр качества"),
                ("Контрольный прогон в продакшен-подобном окружении", "sync",
                 "Инженер по надёжности"),
                ("Финальная приёмка результата владельцем продукта", "sync", "Координатор"),
                ("Закрытие задачи и архивирование подтверждений", "sync", "Оператор"),
            ]
            for order, (name, etype, agent_name) in enumerate(phase_defs, start=1):
                phase_service.create_phase({
                    "workflow_id": int(long_wf.id or 0),
                    "name": name,
                    "description": f"Описание фазы «{name}»: что делаем и кто отвечает.",
                    "phase_order": order,
                    "execution_type": etype,
                    "agent_id": agents.get(agent_name),
                })
            uow.commit()
            # параллельная связь: 5 параллелит с 4
            ph = sorted(uow.phases.list(workflow_id=long_wf.id), key=lambda p: p.phase_order)
            phase_service.update_phase(int(ph[4].id or 0), {"parallel_with_phase_id": int(ph[3].id or 0)})
            uow.commit()

        # ── 3-й неймспейс с длинным названием ────────────────────────────
        ns = uow.projects.list()
        have_codes = {p.code for p in ns}
        if "DELIVERY" not in have_codes:
            uow.projects.create({
                "code": "DELIVERY",
                "name": "Доставка и выпуск — очень длинное название неймспейса",
                "description": "Поток выпуска.",
                "workflow_id": int(wf_ids[-1]),
                "theme_icon": "rocket",
                "theme_color": "#F59E0B",
                "cli_command": "workflow-delivery",
                "key_prefixes": [],
            })
            uow.commit()

        # ── задачи: 40 на неймспейс ──────────────────────────────────────
        task_service = TaskService(uow)
        statuses = ["active", "active", "active", "blocked", "done"]
        titles = [
            "Реализовать проверяемое изменение в модуле обработки событий",
            "Закрыть замечания по ревью и обновитьпокрытие тестами",
            "Обновить документацию запуска под новую схему окружения",
            "Проверить миграцию данных на объёме, близком к продакшену",
            "Сверить страницу списка задач с данными API и исправить расхождения",
            "Подготовить регрессионный прогон по всем ключевым сценариям",
            "Собрать риски релиза и план откатывания",
            "Проверить пакет CLI на чистой машине без локальных зависимостей",
            "Передать UX-сценарий на ревью дизайнеру и собрать обратную связь",
            "Зафиксировать итог приёмки и передать задачу в архив",
            "Починить заедающий ползунок прогресса в списке задач",
            "Добавить индексы под тяжёлые запросы списка задач",
            "Выпрямить типы полей ответа API задач",
            "Разобраться с деградацией времени ответа при 40+ задачах",
            "Убрать дубли агентов после импорта из старой базы",
            "Синхронизировать сид каталога с актуальной схемой БД",
            "Включить строгую валидацию verdict в парсере ответов LLM",
            "Навести порядок в истории фаз задачи",
            "Проверить поведение UI при недоступной базе данных",
            "Сократить число запросов на дашборде",
        ]
        project_list = list(uow.projects.list())
        for p_idx, project in enumerate(project_list):
            phases = _sorted_phases(uow, int(project.workflow_id or 0))
            if not phases:
                continue
            n_phases = len(phases)
            for i in range(40):
                key = f"RUN-{1000 + p_idx * 100 + i}"
                title = titles[i % len(titles)]
                cur = phases[(i * 3) % n_phases]
                existing_task = task_service.get_task_by_key(key, project_id=int(project.id or 0))
                payload: dict[str, Any] = {
                    "project_id": int(project.id or 0),
                    "task_key": key,
                    "title": title,
                    "current_phase_id": int(cur.id or 0),
                }
                if existing_task is None:
                    task_service.create_task(payload)
                else:
                    uow.tasks.update(int(existing_task["id"]), payload)
            uow.commit()

        # проставить статусы отдельным проходом (update_task без history)
        for project in uow.projects.list():
            phases = _sorted_phases(uow, int(project.workflow_id or 0))
            n_phases = len(phases)
            rows = _records(uow, m.Task, project_id=int(project.id or 0))
            for i, row in enumerate(rows):
                row.status = statuses[i % len(statuses)]
                row.current_phase_id = int(phases[(i * 3) % n_phases].id or 0)
            uow.commit()
        print("OK: нагнано данных")


if __name__ == "__main__":
    seed()
