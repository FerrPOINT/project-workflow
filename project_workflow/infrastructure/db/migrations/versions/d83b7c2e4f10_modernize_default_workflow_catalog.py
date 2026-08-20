"""modernize default workflow catalog

Revision ID: d83b7c2e4f10
Revises: f61c2a7d9e04
Create Date: 2026-08-20
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "d83b7c2e4f10"
down_revision: str | Sequence[str] | None = "f61c2a7d9e04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "project_workflow"
WORKFLOW_NAME = "Default Workflow"


def _phase(
    name: str,
    description: str,
    next_recommendation: str,
    instructions: list[str],
    checks: list[str],
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "next_recommendation": next_recommendation,
        "instructions": instructions,
        "checks": checks,
        "evidence": evidence,
    }


CURRENT = {
    "0.0a": _phase(
        "Runtime Readiness",
        "Проверить обязательные runtime-зависимости и канонические entrypoints",
        "Перейти к фиксации критериев приёмки",
        [
            "Проверить подключение к PostgreSQL и актуальность Alembic revision",
            "Проверить OpenAI-compatible endpoint и наличие настроенной модели без раскрытия API key",
            "Проверить канонические CLI entrypoints step и history на текущей revision",
        ],
        [
            "PostgreSQL доступна, DATABASE_URL настроен и Alembic находится на head",
            "OpenAI-compatible endpoint доступен и настроенная модель опубликована",
            "CLI step и history запускаются из текущей revision",
        ],
        [
            "Безопасный snapshot DB host, database name и Alembic revision",
            "Provider host, model и статус models endpoint без API key",
            "Текущий commit и результат CLI help",
        ],
    ),
    "0.01": _phase(
        "Acceptance Setup",
        "Зафиксировать критерии приёмки и план доказательств",
        "Перейти к проверке workspace",
        [
            "Сформулировать проверяемые критерии приёмки",
            "Определить positive, negative, edge и regression сценарии",
            "Зафиксировать источники доказательств и условия остановки",
        ],
        [
            "Критерии приёмки проверяемы и соответствуют scope",
            "План покрывает positive, negative, edge и regression сценарии",
            "Источники доказательств и условия провала определены",
        ],
        ["Список критериев приёмки", "План тестов и доказательств"],
    ),
    "0.000": _phase(
        "Workspace",
        "Проверить repository, project instructions и доступные инструменты",
        "Перейти к проверке git identity",
        [
            "Определить точный repository и worktree задачи",
            "Прочитать ближайшие project instructions и подтвердить обязательные инструменты",
        ],
        [
            "Выбран правильный repository и worktree",
            "Project instructions прочитаны и применимы",
            "Необходимые локальные инструменты доступны",
        ],
        [
            "Абсолютный путь repository и имя branch",
            "Список применимых project instructions и инструментов",
        ],
    ),
    "0.7": _phase(
        "Repo Sync",
        "Сверить рабочую ветку с актуальной base branch",
        "Перейти к preflight critic gate",
        [
            "Получить актуальное состояние remote",
            "Сравнить HEAD с фактической base branch и проверить рабочее дерево",
        ],
        [
            "Remote fetch завершён без ошибок",
            "Отставание или расхождение с base branch отсутствует либо явно зафиксировано",
            "Рабочее дерево clean либо содержит только ожидаемые изменения задачи",
        ],
        [
            "Активная branch, base branch и ahead/behind snapshot",
            "git status --short --branch",
        ],
    ),
    "0.5": _phase(
        "Work Start",
        "Зафиксировать начало работы и фактический scope",
        "Перейти к research и preflight",
        [
            "Подтвердить активный статус задачи в доступном source of truth",
            "Зафиксировать scope, owner и следующий шаг",
        ],
        [
            "Задача имеет активный статус в доступном source of truth",
            "Scope, owner и следующий шаг согласованы с фактической работой",
        ],
        ["Task status snapshot", "Краткий work-start record со scope и следующим шагом"],
    ),
    "6": _phase(
        "Commit",
        "Зафиксировать и отправить проверенное изменение",
        "Перейти к pull request",
        [
            "Добавить в commit только файлы текущей задачи",
            "Создать осмысленный commit и проверить clean status",
            "Отправить branch в origin без force push",
        ],
        ["Commit соответствует scope задачи", "Branch отправлена в origin и рабочее дерево clean"],
        ["Commit SHA и commit subject", "Remote branch SHA и git status"],
    ),
    "7": _phase(
        "Pull Request",
        "Создать или обновить GitHub pull request",
        "Перейти к review, QA и dataflow verification",
        [
            "Создать или обновить pull request для текущей branch",
            "Синхронизировать описание с фактическим diff и результатами проверок",
            "Проверить remote HEAD, mergeability и наличие checks",
        ],
        [
            "Pull request открыт на текущую branch",
            "Описание pull request соответствует фактическому diff и проверкам",
            "Remote HEAD и mergeability проверены, отсутствие checks явно указано",
        ],
        ["GitHub pull request URL", "Pull request HEAD, mergeability и checks snapshot"],
    ),
    "8": _phase(
        "Delivery Handoff",
        "Зафиксировать фактический результат и передать работу",
        "Перейти к ретроспективе",
        [
            "Сверить финальный статус задачи с фактическим результатом",
            "Собрать ссылки на pull request, commit и доказательства",
            "Явно перечислить выполненные, пропущенные и заблокированные проверки",
        ],
        [
            "Финальный статус соответствует фактическому результату",
            "Handoff содержит ссылки, проверки и оставшиеся риски",
        ],
        ["Финальный handoff с pull request, commit и verification summary"],
    ),
    "9": _phase(
        "Retro",
        "Собрать фактические выводы и улучшения процесса",
        "Перейти к фиксации improvement proposals",
        [
            "Разобрать историю решений, failures и повторные прогоны",
            "Собрать реальные метрики из тестов, runtime и audit",
            "Сформулировать конкретные выводы и следующие улучшения",
        ],
        [
            "Retro содержит конкретные выводы и действия",
            "Метрики и предложения основаны на реальных данных задачи",
        ],
        ["Retro summary с метриками, выводами и улучшениями"],
    ),
    "10": _phase(
        "Auto-Improve",
        "Зафиксировать решение по improvement proposals",
        "Workflow завершён",
        [
            "Преобразовать подтверждённые проблемы процесса в конкретные improvement proposals",
            "Если улучшения не нужны, явно зафиксировать причину",
        ],
        ["Решение по improvement proposals основано на фактах ретроспективы"],
        ["Список improvement proposals либо обоснование их отсутствия"],
    ),
}

def _table(name: str) -> str:
    return f"{SCHEMA}.{name}" if op.get_bind().dialect.name == "postgresql" else name


def _replace_catalog(catalog: dict[str, dict[str, Any]]) -> None:
    conn = op.get_bind()
    workflows = _table("workflows")
    phases = _table("phases")
    instructions = _table("instructions")
    checks = _table("checks")
    evidence = _table("evidence")

    for code, phase in catalog.items():
        phase_id = conn.execute(
            sa.text(
                f"SELECT p.id FROM {phases} p "
                f"JOIN {workflows} w ON w.id = p.workflow_id "
                "WHERE w.name = :workflow_name AND p.code = :code AND p.is_seed_managed = 1"
            ),
            {"workflow_name": WORKFLOW_NAME, "code": code},
        ).scalar()
        if phase_id is None:
            continue

        conn.execute(
            sa.text(
                f"UPDATE {phases} SET name = :name, description = :description, "
                "next_recommendation = :next_recommendation WHERE id = :phase_id"
            ),
            {
                "phase_id": phase_id,
                "name": phase["name"],
                "description": phase["description"],
                "next_recommendation": phase["next_recommendation"],
            },
        )
        for table in (instructions, checks, evidence):
            conn.execute(sa.text(f"DELETE FROM {table} WHERE phase_id = :phase_id"), {"phase_id": phase_id})
        for step_num, description in enumerate(phase["instructions"], start=1):
            conn.execute(
                sa.text(
                    f"INSERT INTO {instructions} "
                    "(phase_id, step_num, description, execution_type) "
                    "VALUES (:phase_id, :step_num, :description, 'sync')"
                ),
                {"phase_id": phase_id, "step_num": step_num, "description": description},
            )
        for description in phase["checks"]:
            conn.execute(
                sa.text(f"INSERT INTO {checks} (phase_id, description) VALUES (:phase_id, :description)"),
                {"phase_id": phase_id, "description": description},
            )
        for description in phase["evidence"]:
            conn.execute(
                sa.text(f"INSERT INTO {evidence} (phase_id, description) VALUES (:phase_id, :description)"),
                {"phase_id": phase_id, "description": description},
            )


def upgrade() -> None:
    _replace_catalog(CURRENT)


def downgrade() -> None:
    # Retired external-tool contracts are intentionally not restored.
    pass
