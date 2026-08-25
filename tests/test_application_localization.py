"""Регрессии русскоязычного пользовательского контракта."""

from __future__ import annotations

import json
from pathlib import Path

from project_workflow.domain.validation import TaskKeyValidator
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
            "projects.html",
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
        "Добавить skill",
        "Фазы workflow",
        "Проекты workflow",
        "workflow CLI",
    ):
        assert forbidden not in sources
    assert "data-execution-type" in sources
    assert "параллельно" in sources
    assert "последовательно" in sources
    assert "Подтверждения" in sources


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

    error = TaskKeyValidator([]).validate("UNKNOWN-1").error_message
    assert error is not None
    assert "не соответствует" in error
    assert "Префиксы:" in error


def test_provider_failure_blocker_is_user_facing_russian() -> None:
    blocker = _blocked(ConnectionError("provider down")).blockers[0]

    assert blocker.startswith("Проверяющий LLM недоступен:")
    assert "unavailable" not in blocker.lower()
