from __future__ import annotations

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.interfaces.ui.app import create_app


def _namespace(code: str, cli_command: str, prefix: str) -> None:
    with SAUnitOfWork() as uow:
        workflow = uow.workflows.list()[0]
        uow.projects.create(
            {
                "code": code,
                "name": code,
                "workflow_id": workflow.id,
                "cli_command": cli_command,
                "key_prefixes": [prefix],
            }
        )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_runtime_step_is_fail_closed_without_configured_token():
    with TestClient(create_app()) as client:
        response = client.post(
            "/internal/runtime/step",
            headers=_headers("x" * 32),
            json={"task": "RUN-1"},
        )

    assert response.status_code == 401
    assert response.json() == {"ok": False, "error": "Недействительный runtime token"}


def test_runtime_step_is_unavailable_for_malformed_or_duplicate_tokens(monkeypatch):
    for value in (
        "not-json",
        json.dumps({"analyst": "short"}),
        json.dumps({"analyst": "x" * 32, "architect": "x" * 32}),
    ):
        monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", value)
        config.get_settings.cache_clear()
        with TestClient(create_app()) as client:
            response = client.post(
                "/internal/runtime/step",
                headers=_headers("x" * 32),
                json={"task": "RUN-1"},
            )
        assert response.status_code == 503
        assert response.json()["ok"] is False


def test_runtime_token_is_bound_to_one_namespace(monkeypatch, supervisor_llm):
    analyst_token = "a" * 32
    architect_token = "b" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"analyst": analyst_token, "architect": architect_token}),
    )
    config.get_settings.cache_clear()
    _namespace("ANALYST", "workflow-analyst", "ANA")
    _namespace("ARCHITECT", "workflow-architect", "ARC")

    with TestClient(create_app()) as client:
        current = client.post(
            "/internal/runtime/step",
            headers=_headers(analyst_token),
            json={"task": "ANA-1"},
        )
        foreign = client.post(
            "/internal/runtime/step",
            headers=_headers(analyst_token),
            json={"task": "ARC-1"},
        )
        supervisor_llm("PASS")
        completed = client.post(
            "/internal/runtime/step",
            headers=_headers(analyst_token),
            json={"task": "ANA-1", "report": "Все требования выполнены."},
        )
        history = client.get(
            "/internal/runtime/history",
            headers=_headers(analyst_token),
            params={"task": "ANA-1"},
        )

    assert current.status_code == 200
    assert current.json()["result"]["task_key"] == "ANA-1"
    assert foreign.status_code == 409
    assert completed.status_code == 200
    assert completed.json()["result"]["verdict"] == "PASS"
    assert history.status_code == 200
    assert history.json()["result"]["count"] == 1
    assert history.json()["result"]["records"][0]["retryable"] is False


def test_runtime_history_exposes_retryable_supervisor_failure(monkeypatch):
    token = "d" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")

    with TestClient(create_app()) as client:
        current = client.post(
            "/internal/runtime/step",
            headers=_headers(token),
            json={"task": "DEV-1"},
        )
        with patch.object(
            OpenAICompatibleClient,
            "chat",
            side_effect=ValueError("invalid evaluator response"),
        ):
            blocked = client.post(
                "/internal/runtime/step",
                headers=_headers(token),
                json={"task": "DEV-1", "report": "Отчёт"},
            )
        history = client.get(
            "/internal/runtime/history",
            headers=_headers(token),
            params={"task": "DEV-1"},
        )

    assert current.status_code == 200
    assert blocked.status_code == 200
    assert blocked.json()["result"]["retryable"] is True
    assert history.status_code == 200
    assert history.json()["result"]["records"][0]["retryable"] is True
