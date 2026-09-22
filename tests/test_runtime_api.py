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


def _assignment(task: str, operation_key: str) -> dict[str, object]:
    return {
        "task": task,
        "mode_key": "default",
        "cycle_number": 0,
        "operation_key": operation_key,
        "expected_revision": 0,
        "expected_status": "missing",
    }


def test_runtime_step_is_fail_closed_without_configured_token():
    with TestClient(create_app()) as client:
        response = client.post(
            "/internal/runtime/step",
            headers=_headers("x" * 32),
            json={"task": "RUN-1"},
        )

    assert response.status_code == 401
    assert response.json() == {"ok": False, "error": "Недействительный runtime token"}


def test_fleet_catalog_token_cannot_execute_steps_or_read_history(monkeypatch):
    catalog_token = "f" * 32
    worker_token = "w" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"worker": worker_token}),
    )
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", catalog_token)
    config.get_settings.cache_clear()
    _namespace("WORKER", "workflow-worker", "WRK")

    with TestClient(create_app()) as client:
        catalog = client.get("/internal/runtime/catalog", headers=_headers(catalog_token))
        missing = client.get("/internal/runtime/catalog")
        wrong_role = client.get("/internal/runtime/catalog", headers=_headers(worker_token))
        step = client.post(
            "/internal/runtime/step",
            headers=_headers(catalog_token),
            json={"task": "WRK-1"},
        )
        history = client.get(
            "/internal/runtime/history",
            headers=_headers(catalog_token),
            params={"task": "WRK-1"},
        )

    assert catalog.status_code == 200
    assert catalog.json()["ok"] is True
    assert any(item["name"] == "WORKER" for item in catalog.json()["namespaces"])
    assert catalog.json()["workflows"]
    assert missing.status_code == 401
    assert wrong_role.status_code == 403
    assert step.status_code == 403
    assert history.status_code == 403


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
    assignment_token = "c" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"analyst": analyst_token, "architect": architect_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"analyst": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("ANALYST", "workflow-analyst", "ANA")
    _namespace("ARCHITECT", "workflow-architect", "ARC")

    with TestClient(create_app()) as client:
        assigned = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("ANA-1", "assign-ana-1"),
        )
        operation_collision = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("ANA-2", "assign-ana-1"),
        )
        forbidden_assignment = client.post(
            "/internal/runtime/assign",
            headers=_headers(analyst_token),
            json=_assignment("ANA-2", "assign-ana-2"),
        )
        forbidden_step = client.post(
            "/internal/runtime/step",
            headers=_headers(assignment_token),
            json={"task": "ANA-1"},
        )
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

    assert assigned.status_code == 200
    assert assigned.json()["result"]["task_key"] == "ANA-1"
    assert operation_collision.status_code == 409
    assert forbidden_assignment.status_code == 403
    assert forbidden_step.status_code == 401
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
    assignment_token = "e" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")

    with TestClient(create_app()) as client:
        assigned = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("DEV-1", "assign-dev-1"),
        )
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

    assert assigned.status_code == 200
    assert current.status_code == 200
    assert blocked.status_code == 200
    assert blocked.json()["result"]["retryable"] is True
    assert history.status_code == 200
    assert history.json()["result"]["records"][0]["retryable"] is True


def test_token_collision_closes_runtime_and_assignment_endpoints(monkeypatch):
    shared = "s" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"analyst": shared}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"analyst": shared}),
    )
    config.get_settings.cache_clear()

    with TestClient(create_app()) as client:
        step = client.post(
            "/internal/runtime/step", headers=_headers(shared), json={"task": "ANA-1"}
        )
        assignment = client.post(
            "/internal/runtime/assign",
            headers=_headers(shared),
            json=_assignment("ANA-1", "collision"),
        )

    assert step.status_code == 503
    assert assignment.status_code == 503
