"""Регрессии русскоязычного пользовательского контракта."""

from __future__ import annotations

import hashlib
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


def test_packaged_v1_is_the_exact_historical_catalog() -> None:
    seed_path = ROOT / "project_workflow" / "references" / "seed.json"
    raw = seed_path.read_bytes()
    catalog = json.loads(raw)
    by_code = {item["code"]: item["name"] for item in catalog}

    normalized_raw = raw.replace(b"\r\n", b"\n")
    assert hashlib.sha256(normalized_raw).hexdigest() == (
        "abdb166bc9734630769cbb1eae165c0ac066e783cda8179d909a5c5a1beecec6"
    )
    assert len(catalog) == 19
    assert by_code["1.INTAKE"] == "Intake"
    assert by_code["3.DOR_GATE"] == "Definition of Ready"
    assert by_code["9.PR"] == "Pull Request"
    assert by_code["10.REVIEW"] == "Code review"
    assert by_code["11.RUNTIME"] == "Runtime acceptance"


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
