"""Регрессии русскоязычного пользовательского контракта."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from project_workflow.domain.validation import TaskKeyValidator
from project_workflow.infrastructure.llm import LlmConfigurationError
from project_workflow.supervisor.evaluate import _blocked
from project_workflow.supervisor.formatting import format_result

ROOT = Path(__file__).parents[1]
TEMPLATES = ROOT / "project_workflow" / "interfaces" / "ui" / "templates"


def test_primary_ui_labels_do_not_expose_internal_english_enums() -> None:
    sources = "\n".join(
        (TEMPLATES / name).read_text(encoding="utf-8")
        for name in (
            "phases.html",
            "phase_detail.html",
            "instructions.html",
            "task_detail.html",
            "namespaces.html",
            "agents.html",
            "settings.html",
        )
    )

    for forbidden in (
        ">parallel<",
        ">sync<",
        "⚡ parallel",
        "⏱ sync",
        ">Evidence<",
        "Hermes profile:",
        "Профиль Hermes",
        "профиль Hermes",
        "Профиль запуска",
        "Циклы Supervisor",
        "История проверок Supervisor",
        "Ответ Supervisor",
        "Задание Supervisor",
        "Проверок Supervisor",
        "Добавить skill",
        "Фазы workflow",
        "Контуры workflow",
        "workflow CLI",
        'data-field="hermes_profile"',
    ):
        assert forbidden not in sources
    assert "data-execution-type" in sources
    assert "параллельно" in sources
    assert "последовательно" in sources
    assert "Подтверждения" in sources
    assert "Ключ запуска" in sources


def test_working_pages_do_not_render_internal_launch_profile_values() -> None:
    phase_detail = (TEMPLATES / "phase_detail.html").read_text(encoding="utf-8")
    task_detail = (TEMPLATES / "task_detail.html").read_text(encoding="utf-8")

    assert "a.hermes_profile" not in phase_detail
    assert "detail.hermes_profile" not in task_detail
    assert "contract.hermes_profile" not in task_detail


def test_packaged_phase_names_are_localized_without_changing_codes() -> None:
    catalog = json.loads((ROOT / "project_workflow" / "references" / "seed.json").read_text(encoding="utf-8"))
    by_code = {item["code"]: item["name"] for item in catalog}

    assert by_code["1.INTAKE"] == "Приём задачи"
    assert by_code["3.DOR_GATE"] == "Готовность к работе"
    assert by_code["9.PR"] == "Запрос на слияние"
    assert by_code["10.REVIEW"] == "Проверка кода"
    assert by_code["11.RUNTIME"] == "Приёмка приложения"

    user_text = "\n".join(
        str(value)
        for phase in catalog
        for key, value in phase.items()
        if key in {"name", "description", "instructions", "checks", "evidence"}
    )
    for forbidden in (
        "Используй skills",
        "acceptance criteria",
        "Operator review",
        "Readback",
        "evidence сохранены",
        "Runtime acceptance",
        "Unknown phase",
        "выполнить merge",
    ):
        assert forbidden not in user_text


def test_user_facing_docs_do_not_name_specific_executor_runtime() -> None:
    docs = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in (
            "AGENTS.md",
            "README.md",
            "LIVE_TEST_PLAN.md",
            "docs/architecture.md",
            "docs/quality-gate.md",
            "docs/bug-audit.md",
        )
    )

    assert "Hermes" not in docs
    assert "гермес" not in docs.lower()


def test_cli_result_and_task_key_errors_are_in_russian() -> None:
    rendered = format_result(
        {
            "verdict": "PASS",
            "next_phase": None,
            "group_details": [],
            "next_phase_contract": {},
        }
    )
    assert rendered == "Воркфлоу завершён: задача уже прошла все фазы."

    error = TaskKeyValidator([]).validate("UNKNOWN-TEXT").error_message
    assert error is not None
    assert "должен соответствовать" in error
    assert "Префиксы:" not in error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (LlmConfigurationError("secret"), "не настроен"),
        (requests.Timeout("secret"), "не ответил"),
        (requests.ConnectionError("secret"), "соединение"),
        (requests.HTTPError("secret"), "отклонил"),
        (requests.RequestException("secret"), "обмена данными"),
        (ValueError("secret"), "некорректный ответ"),
    ],
)
def test_provider_failure_blocker_is_user_facing_russian(error: Exception, expected: str) -> None:
    blocker = _blocked(error).blockers[0]

    assert expected in blocker
    assert "secret" not in blocker
