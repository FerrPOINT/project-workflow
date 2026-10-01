from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from project_workflow import config
from project_workflow.application.task import TaskService
from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.interfaces.ui.app import create_app
from project_workflow.interfaces.ui.routes import runtime_api
from project_workflow.interfaces.ui.schemas import RuntimeStepRequest


def test_optional_pm_uuid_preserves_ordinary_runtime_command_hash():
    from project_workflow.domain.runtime_assignment import payload_sha256

    legacy = {**_unknown_step_payload("DEV-25"), "report": "durable ordinary report"}
    parsed = RuntimeStepRequest.model_validate(legacy)
    assert payload_sha256(parsed.model_dump(mode="json")) == payload_sha256(legacy)
    assert "session_run_id" not in parsed.model_dump()
    pm_run_id = "11111111-1111-4111-8111-111111111111"
    scoped = RuntimeStepRequest.model_validate({**legacy, "session_run_id": pm_run_id})
    assert scoped.model_dump()["session_run_id"] == pm_run_id


def _namespace(code: str, cli_command: str, prefix: str) -> None:
    role = cli_command.removeprefix("workflow-")
    scope = "delivery" if role == "developer" else "business"
    with SAUnitOfWork() as uow:
        workflow_id = uow.workflows.create(
            {"key": f"hermes-sdlc:{role}", "name": f"Runtime {role}"}
        )
        mode_id = uow.workflows.create_mode(
            {
                "workflow_id": workflow_id,
                "key": "assigned",
                "name": "Assigned",
                "mode_order": 2,
                "role_key": role,
                "execution_scope": scope,
                "tech_workspace_policy": "required" if scope != "business" else "forbidden",
            }
        )
        uow.phases.create(
            {
                "workflow_id": workflow_id,
                "mode_id": mode_id,
                "code": "assigned",
                "name": "Assigned",
                "phase_order": 1,
            }
        )
        uow.projects.create(
            {
                "code": code,
                "name": code,
                "workflow_id": workflow_id,
                "cli_command": cli_command,
                "key_prefixes": [prefix],
            }
        )
        uow.commit()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _assignment(task: str, operation_key: str, role: str) -> dict[str, object]:
    scope = "delivery" if role == "developer" else "business"
    payload: dict[str, object] = {
        "task": task,
        "workflow_key": f"hermes-sdlc:{role}",
        "role_key": role,
        "mode_key": "assigned",
        "stage_key": role,
        "execution_scope": scope,
        "cycle_number": 0,
        "attempt_number": 1,
        "operation_key": operation_key,
        "business_task_ref": f"business-task:{task}@1",
        "root_task_ref": f"business-task:{task}@1",
        "work_item_ref": f"business-task:{task}@1",
        "work_item_revision": 1,
        "queue_item_ref": f"queue-item:{task}:{role}:0",
        "task_workspace_ref": f"task-workspace:{task}",
        "workspace_revision": 1,
        "decomposition_revision_ref": f"decomposition:{task}@1",
        "stage_revision": f"stage:{role}@1",
        "assignment_ref": f"assignment:{operation_key}",
        "workspace_generation": 1,
        "lease_generation": 1,
        "exact_input_refs": [
            {"kind": "business_task", "ref": f"business-task:{task}", "revision": "1"}
        ],
        "expected_revision": 0,
        "expected_status": "missing",
    }
    if scope == "delivery":
        payload["tech_execution_workspace_ref"] = f"tech-workspace:{task}"
        payload["tech_execution_attempt_ref"] = f"tech-attempt:{task}"
    return payload


def _bind_payload(
    assignment: dict[str, object],
    *,
    bind_operation_key: str | None = None,
    binding_ref: str | None = None,
    hermes_run_ref: str | None = None,
) -> dict[str, object]:
    operation_key = str(assignment["assignment_operation_key"])
    return {
        "task": assignment["task_key"],
        "bind_operation_key": bind_operation_key or f"bind:{operation_key}",
        "assignment_operation_key": operation_key,
        "assignment_revision": assignment["assignment_revision"],
        "assignment_ref": assignment["assignment_ref"],
        "binding_ref": binding_ref or f"binding:{operation_key}",
        "hermes_run_ref": hermes_run_ref or f"hermes-run:{operation_key}",
        "mode_key": assignment["mode_key"],
        "cycle_number": assignment["cycle_number"],
        "attempt_number": assignment["attempt_number"],
        "expected_binding_state": "unbound",
    }


def _bind_assignment(
    client: TestClient, assignment_token: str, assignment: dict[str, object]
) -> dict[str, object]:
    response = client.post(
        "/internal/runtime/bind",
        headers=_headers(assignment_token),
        json=_bind_payload(assignment),
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def _step_payload(
    assignment: dict[str, object],
    report: str | None = None,
    *,
    step_operation_key: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "task": assignment["task_key"],
        "step_operation_key": step_operation_key
        or "step:"
        + hashlib.sha256(
            (
                f"{assignment['task_key']}:{assignment['assignment_revision']}:"
                f"{report or 'instructions'}"
            ).encode()
        ).hexdigest()[:24],
        "assignment_revision": assignment["assignment_revision"],
        "assignment_ref": assignment["assignment_ref"],
        "binding_ref": assignment["binding_ref"],
        "hermes_run_ref": assignment["hermes_run_ref"],
        "mode_key": assignment["mode_key"],
        "cycle_number": assignment["cycle_number"],
        "attempt_number": assignment["attempt_number"],
        "expected_phase_code": assignment.get("current_phase_code", "assigned"),
        "expected_status": assignment["status"],
    }
    if report is not None:
        payload["report"] = report
    return payload


def _service_assignment(
    *, project_id: int, task: str, operation_key: str, role: str, **overrides: object
) -> dict[str, object]:
    payload = _assignment(task, operation_key, role)
    payload.update(overrides)
    payload["project_id"] = project_id
    payload["task_key"] = payload.pop("task")
    return payload


def _service_bind(
    uow: SAUnitOfWork,
    *,
    project_id: int,
    role: str,
    assignment: dict[str, object],
) -> dict[str, object]:
    payload = _bind_payload(assignment)
    return TaskService(uow).bind_runtime_assignment(
        project_id=project_id,
        task_key=str(payload["task"]),
        role_key=role,
        bind_operation_key=str(payload["bind_operation_key"]),
        assignment_operation_key=str(payload["assignment_operation_key"]),
        assignment_revision=int(payload["assignment_revision"]),
        assignment_ref=str(payload["assignment_ref"]),
        binding_ref=str(payload["binding_ref"]),
        hermes_run_ref=str(payload["hermes_run_ref"]),
        mode_key=str(payload["mode_key"]),
        cycle_number=int(payload["cycle_number"]),
        attempt_number=int(payload["attempt_number"]),
        expected_binding_state=str(payload["expected_binding_state"]),
    )


def _unknown_step_payload(task: str) -> dict[str, object]:
    return {
        "task": task,
        "step_operation_key": f"step:{task}:unknown",
        "assignment_revision": 1,
        "assignment_ref": "assignment:unknown",
        "binding_ref": "binding:unknown",
        "hermes_run_ref": "hermes-run:unknown",
        "mode_key": "assigned",
        "cycle_number": 0,
        "attempt_number": 1,
        "expected_phase_code": "assigned",
        "expected_status": "active",
    }


def test_runtime_step_is_fail_closed_without_configured_token():
    with TestClient(create_app()) as client:
        response = client.post(
            "/internal/runtime/step",
            headers=_headers("x" * 32),
            json=_unknown_step_payload("RUN-1"),
        )

    assert response.status_code == 401
    assert response.json() == {"ok": False, "error": "Недействительный runtime token"}


def test_runtime_step_requires_full_assignment_fence_after_authentication(monkeypatch):
    token = "z" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": token}),
    )
    config.get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.post(
            "/internal/runtime/step",
            headers=_headers(token),
            json={"task": "DEV-1", "report": "Нельзя выполнить без assignment fence"},
        )

    assert response.status_code == 422


def test_fleet_catalog_token_cannot_execute_steps_or_read_history(monkeypatch):
    catalog_token = "f" * 32
    worker_token = "w" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"worker": worker_token}),
    )
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", catalog_token)
    config.get_settings.cache_clear()
    managed_namespaces = [
        {"name": role.upper(), "cli_command": f"workflow-{role}"}
        for role in (
            "project_manager",
            "analyst",
            "architect",
            "developer",
            "reviewer",
            "tester",
            "devops",
        )
    ]
    managed_workflows = [
        {"key": f"hermes-sdlc:{role}"}
        for role in (
            "project_manager",
            "analyst",
            "architect",
            "developer",
            "reviewer",
            "tester",
            "devops",
        )
    ]
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow)

    with patch(
        "project_workflow.interfaces.ui.routes.api.api_namespaces",
        new=AsyncMock(
            return_value={
                "ok": True,
                "namespaces": [
                    {"name": "LEGACY", "cli_command": "workflow-run"},
                    *managed_namespaces,
                ],
            }
        ),
    ), patch(
        "project_workflow.interfaces.ui.routes.api.api_workflows",
        new=AsyncMock(
            return_value={
                "ok": True,
                "workflows": [{"key": "legacy:1"}, *managed_workflows],
            }
        ),
    ), TestClient(create_app()) as client:
        catalog = client.get("/internal/runtime/catalog", headers=_headers(catalog_token))
        missing = client.get("/internal/runtime/catalog")
        wrong_role = client.get("/internal/runtime/catalog", headers=_headers(worker_token))
        step = client.post(
            "/internal/runtime/step",
            headers=_headers(catalog_token),
            json=_unknown_step_payload("WRK-1"),
        )
        history = client.get(
            "/internal/runtime/history",
            headers=_headers(catalog_token),
            params={"task": "WRK-1"},
        )

    assert catalog.status_code == 200
    assert catalog.json()["ok"] is True
    assert catalog.json()["namespaces"] == managed_namespaces
    assert catalog.json()["workflows"] == managed_workflows
    assert missing.status_code == 401
    assert wrong_role.status_code == 403
    assert step.status_code == 403
    assert history.status_code == 403


def test_runtime_credential_named_fleet_control_cannot_read_control_catalog(monkeypatch):
    runtime_token = "r" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"fleet-control": runtime_token}),
    )
    config.get_settings.cache_clear()

    with TestClient(create_app()) as client:
        runtime_catalog = client.get(
            "/internal/runtime/catalog", headers=_headers(runtime_token)
        )

    assert runtime_catalog.status_code == 403
    assert runtime_catalog.json() == {
        "ok": False,
        "error": "Токен не разрешает чтение каталога",
    }


def test_fleet_catalog_fails_closed_on_partial_managed_inventory(monkeypatch):
    control_token = "c" * 32
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", control_token)
    config.get_settings.cache_clear()

    with patch(
        "project_workflow.interfaces.ui.routes.api.api_namespaces",
        new=AsyncMock(
            return_value={
                "ok": True,
                "namespaces": [
                    {"cli_command": "workflow-project_manager"},
                ],
            }
        ),
    ), patch(
        "project_workflow.interfaces.ui.routes.api.api_workflows",
        new=AsyncMock(
            return_value={
                "ok": True,
                "workflows": [{"key": "hermes-sdlc:project_manager"}],
            }
        ),
    ), TestClient(create_app()) as client:
        response = client.get(
            "/internal/runtime/catalog", headers=_headers(control_token)
        )

    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "error": "Managed каталог временно недоступен",
    }


def test_runtime_step_is_unavailable_for_malformed_or_duplicate_tokens(monkeypatch):
    for value in (
        "not-json",
        "[]",
        json.dumps({"analyst": "short"}),
        json.dumps({"analyst.v2": "x" * 32}),
        json.dumps({"analyst": "x" * 32, "architect": "x" * 32}),
        json.dumps({"analyst": "x" * 32, " analyst": "y" * 32}),
    ):
        monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", value)
        config.get_settings.cache_clear()
        with TestClient(create_app()) as client:
            response = client.post(
                "/internal/runtime/step",
                headers=_headers("x" * 32),
                json=_unknown_step_payload("RUN-1"),
            )
        assert response.status_code == 503
        assert response.json()["ok"] is False


@pytest.mark.parametrize(
    "catalog_token", ["short", "r" * 48, "a" * 48]
)
def test_invalid_or_colliding_catalog_credential_disables_every_runtime_surface(monkeypatch, catalog_token):
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"analyst": "r" * 48}))
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"analyst": "a" * 48}))
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", catalog_token)
    config.get_settings.cache_clear()
    binding = {
        "task_key": "ANA-1", "assignment_operation_key": "assign:ANA-1", "assignment_revision": 1,
        "assignment_ref": "assignment:ANA-1", "mode_key": "assigned", "cycle_number": 0,
        "attempt_number": 1,
    }
    with TestClient(create_app()) as client:
        responses = [
            client.get("/internal/runtime/capabilities", headers=_headers("r" * 48)),
            client.get("/internal/runtime/catalog", headers=_headers(catalog_token)),
            client.get("/internal/runtime/history", params={"task": "ANA-1"}, headers=_headers("r" * 48)),
            client.post("/internal/runtime/step", json=_unknown_step_payload("ANA-1"), headers=_headers("r" * 48)),
            client.post("/internal/runtime/assign", json=_assignment("ANA-1", "assign:ANA-1", "analyst"),
                        headers=_headers("a" * 48)),
            client.post("/internal/runtime/bind", json=_bind_payload(binding), headers=_headers("a" * 48)),
        ]
    for response in responses:
        assert response.status_code == 503, response.text
        assert response.json()["ok"] is False
        assert "r" * 48 not in response.text
        assert "a" * 48 not in response.text
    with SAUnitOfWork() as uow:
        assert uow.tasks.get_by_key("ANA-1") is None


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
        unassigned = client.post(
            "/internal/runtime/step",
            headers=_headers(analyst_token),
            json=_unknown_step_payload("ANA-2"),
        )
        assigned = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("ANA-1", "assign-ana-1", "analyst"),
        )
        bound = _bind_assignment(client, assignment_token, assigned.json()["result"])
        operation_collision = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("ANA-2", "assign-ana-1", "analyst"),
        )
        wrong_role_payload = _assignment("ANA-2", "assign-ana-role-mismatch", "analyst")
        wrong_role_payload["role_key"] = "developer"
        wrong_role_assignment = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=wrong_role_payload,
        )
        forbidden_assignment = client.post(
            "/internal/runtime/assign",
            headers=_headers(analyst_token),
            json=_assignment("ANA-2", "assign-ana-2", "analyst"),
        )
        forbidden_step = client.post(
            "/internal/runtime/step",
            headers=_headers(assignment_token),
            json=_unknown_step_payload("ANA-1"),
        )
        current = client.post(
            "/internal/runtime/step",
            headers=_headers(analyst_token),
            json=_step_payload(bound),
        )
        foreign = client.post(
            "/internal/runtime/step",
            headers=_headers(analyst_token),
            json=_unknown_step_payload("ARC-1"),
        )
        supervisor_llm("PASS")
        completed = client.post(
            "/internal/runtime/step",
            headers=_headers(analyst_token),
            json=_step_payload(bound, "Все требования выполнены."),
        )
        history = client.get(
            "/internal/runtime/history",
            headers=_headers(analyst_token),
            params={"task": "ANA-1"},
        )

    assert unassigned.status_code == 409
    assert assigned.status_code == 200
    assignment_result = assigned.json()["result"]
    assert assignment_result["task_key"] == "ANA-1"
    assert assignment_result["workflow_key"] == "hermes-sdlc:analyst"
    assert assignment_result["role_key"] == "analyst"
    assert assignment_result["stage_key"] == "analyst"
    assert assignment_result["attempt_number"] == 1
    assert assignment_result["execution_scope"] == "business"
    assert assignment_result["business_task_ref"] == "business-task:ANA-1@1"
    assert assignment_result["work_item_revision"] == 1
    assert assignment_result["queue_item_ref"] == "queue-item:ANA-1:analyst:0"
    assert assignment_result["workspace_revision"] == 1
    assert assignment_result["tech_execution_workspace_ref"] is None
    assert assignment_result["binding_state"] == "unbound"
    assert assignment_result["binding_ref"] is None
    assert assignment_result["hermes_run_ref"] is None
    assert bound["binding_state"] == "bound"
    assert assignment_result["exact_input_refs"] == [
        {
            "kind": "business_task",
            "ref": "business-task:ANA-1",
            "revision": "1",
        }
    ]
    assert operation_collision.status_code == 409
    assert wrong_role_assignment.status_code == 403
    assert forbidden_assignment.status_code == 403
    assert forbidden_step.status_code == 403
    assert current.status_code == 200
    assert current.json()["result"]["task_key"] == "ANA-1"
    assert foreign.status_code == 409
    assert completed.status_code == 200
    assert completed.json()["result"]["verdict"] == "PASS"
    assert history.status_code == 200
    assert history.json()["result"]["count"] == 1
    assert history.json()["result"]["records"][0]["retryable"] is False
    with SAUnitOfWork() as uow:
        assert uow.tasks.get_by_key("ANA-2") is None


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
            json=_assignment("DEV-1", "assign-dev-1", "developer"),
        )
        bound = _bind_assignment(client, assignment_token, assigned.json()["result"])
        current = client.post(
            "/internal/runtime/step",
            headers=_headers(token),
            json=_step_payload(bound),
        )
        with patch.object(
            OpenAICompatibleClient,
            "chat",
            side_effect=ValueError("invalid evaluator response"),
        ):
            blocked = client.post(
                "/internal/runtime/step",
                headers=_headers(token),
                json=_step_payload(bound, "Отчёт"),
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
    assert blocked.json()["result"]["binding_state"] == "bound"
    assert blocked.json()["result"]["status"] == "blocked"
    assert blocked.json()["result"]["current_phase_code"] == "assigned"
    assert blocked.json()["result"]["current_phase_name"] == "Assigned"
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
            "/internal/runtime/step",
            headers=_headers(shared),
            json=_unknown_step_payload("ANA-1"),
        )
        assignment = client.post(
            "/internal/runtime/assign",
            headers=_headers(shared),
            json=_assignment("ANA-1", "collision", "analyst"),
        )
        binding = client.post(
            "/internal/runtime/bind",
            headers=_headers(shared),
            json=_bind_payload(
                {
                    "task_key": "ANA-1",
                    "assignment_operation_key": "collision",
                    "assignment_revision": 1,
                    "assignment_ref": "assignment:collision",
                    "mode_key": "assigned",
                    "cycle_number": 0,
                    "attempt_number": 1,
                }
            ),
        )

    assert step.status_code == 503
    assert assignment.status_code == 503
    assert binding.status_code == 503


@pytest.mark.parametrize("work_item_revision", [1, 1790840000123])
def test_runtime_assignment_accepts_exact_business_snapshot_contract(monkeypatch, work_item_revision):
    assignment_token = "snapshot-assignment-token-1234567"
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")

    empty = _assignment("DEV-30", "assign-dev-30", "developer")
    empty["work_item_revision"] = work_item_revision
    empty["exact_input_refs"] = []
    snapshots = _assignment("DEV-31", "assign-dev-31", "developer")
    snapshots["exact_input_refs"] = [
        {
            "kind": "tech-execution-terminal-receipt",
            "ref": "terminal-receipt:architecture",
            "revision": "receipt-r1",
            "hash": "etag-v4",
        },
        {"kind": "requirement", "ref": "requirement:business-scope"},
    ]

    with TestClient(create_app()) as client:
        oversized = client.post(
            "/internal/runtime/assign", headers=_headers(assignment_token),
            json={**empty, "work_item_revision": 1 << 63},
        )
        accepted_empty = client.post(
            "/internal/runtime/assign", headers=_headers(assignment_token), json=empty
        )
        replay_empty = client.post(
            "/internal/runtime/assign", headers=_headers(assignment_token), json=empty
        )
        accepted_snapshots = client.post(
            "/internal/runtime/assign", headers=_headers(assignment_token), json=snapshots
        )
        changed = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json={
                **snapshots,
                "exact_input_refs": [
                    {**snapshots["exact_input_refs"][0], "hash": "etag-v5"},
                    snapshots["exact_input_refs"][1],
                ],
            },
        )
        absent_optional = _assignment("DEV-32", "assign-dev-32", "developer")
        absent_optional["exact_input_refs"] = [{"kind": "requirement", "ref": "req:32"}]
        assert client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=absent_optional,
        ).status_code == 200
        present_null = {
            **absent_optional,
            "exact_input_refs": [
                {"kind": "requirement", "ref": "req:32", "revision": None}
            ],
        }
        null_changed = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=present_null,
        )
        invalid_payloads = []
        for item in (
            {"kind": " ", "ref": "valid"},
            {"kind": "requirement", "ref": " "},
            {"kind": "requirement", "ref": "valid", "hash": " "},
            {"kind": "requirement", "ref": "valid", "hash": "h" * 257},
        ):
            payload = _assignment("DEV-33", f"invalid-{len(invalid_payloads)}", "developer")
            payload["exact_input_refs"] = [item]
            invalid_payloads.append(
                client.post(
                    "/internal/runtime/assign",
                    headers=_headers(assignment_token),
                    json=payload,
                )
            )

    assert oversized.status_code == 422
    assert accepted_empty.status_code == 200
    assert accepted_empty.json()["result"]["work_item_revision"] == work_item_revision
    assert accepted_empty.json()["result"]["exact_input_refs"] == []
    assert replay_empty.status_code == 200
    assert accepted_snapshots.status_code == 200
    assert accepted_snapshots.json()["result"]["exact_input_refs"] == [
        {"kind": "requirement", "ref": "requirement:business-scope"},
        {
            "kind": "tech-execution-terminal-receipt",
            "ref": "terminal-receipt:architecture",
            "revision": "receipt-r1",
            "hash": "etag-v4",
        },
    ]
    assert changed.status_code == 409
    assert null_changed.status_code == 409
    assert [response.status_code for response in invalid_payloads] == [422, 422, 422, 422]


def test_runtime_bind_is_role_scoped_idempotent_and_fenced(monkeypatch):
    runtime_token = "developer-runtime-token-123456789"
    developer_assignment_token = "developer-assignment-token-12345"
    analyst_assignment_token = "analyst-assignment-token-1234567"
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps(
            {
                "developer": developer_assignment_token,
                "analyst": analyst_assignment_token,
            }
        ),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")
    _namespace("ANALYST", "workflow-analyst", "ANA")

    with TestClient(create_app()) as client:
        accepted_response = client.post(
            "/internal/runtime/assign",
            headers=_headers(developer_assignment_token),
            json=_assignment("DEV-34", "assign-dev-34", "developer"),
        )
        assert accepted_response.status_code == 200
        accepted = accepted_response.json()["result"]
        assert accepted["binding_state"] == "unbound"
        assert accepted["binding_ref"] is None
        assert accepted["hermes_run_ref"] is None
        assert accepted["bind_operation_key"] is None

        before_bind = {**accepted, "binding_ref": "fake", "hermes_run_ref": "fake"}
        unbound_history = client.get(
            "/internal/runtime/history",
            headers=_headers(runtime_token),
            params={"task": "DEV-34"},
        )
        step_before_bind = client.post(
            "/internal/runtime/step",
            headers=_headers(runtime_token),
            json=_step_payload(before_bind),
        )
        bind_payload = _bind_payload(
            accepted,
            binding_ref="business-binding:real-34",
            hermes_run_ref="hermes-session:real-run-34",
        )
        execution_token_bind = client.post(
            "/internal/runtime/bind",
            headers=_headers(runtime_token),
            json=bind_payload,
        )
        wrong_role_bind = client.post(
            "/internal/runtime/bind",
            headers=_headers(analyst_assignment_token),
            json=bind_payload,
        )
        unknown_token_bind = client.post(
            "/internal/runtime/bind",
            headers=_headers("unknown-assignment-token-123456"),
            json=bind_payload,
        )
        for field, value in (
            ("task", "DEV-999"),
            ("assignment_operation_key", "assign-dev-34-other"),
            ("assignment_revision", 2),
            ("assignment_ref", "assignment:other"),
            ("mode_key", "other"),
            ("cycle_number", 1),
            ("attempt_number", 2),
        ):
            rejected = client.post(
                "/internal/runtime/bind",
                headers=_headers(developer_assignment_token),
                json={**bind_payload, field: value, "bind_operation_key": f"bad-bind:{field}"},
            )
            assert rejected.status_code == 409

        bound = client.post(
            "/internal/runtime/bind",
            headers=_headers(developer_assignment_token),
            json=bind_payload,
        )
        replay = client.post(
            "/internal/runtime/bind",
            headers=_headers(developer_assignment_token),
            json=bind_payload,
        )
        changed_same_key = client.post(
            "/internal/runtime/bind",
            headers=_headers(developer_assignment_token),
            json={**bind_payload, "hermes_run_ref": "hermes-session:other-run"},
        )
        second_binding = client.post(
            "/internal/runtime/bind",
            headers=_headers(developer_assignment_token),
            json={
                **bind_payload,
                "bind_operation_key": "bind:assign-dev-34:second",
                "binding_ref": "business-binding:second",
                "hermes_run_ref": "hermes-session:second",
            },
        )

    with TestClient(create_app()) as restarted_client:
        after_restart = restarted_client.post(
            "/internal/runtime/bind",
            headers=_headers(developer_assignment_token),
            json=bind_payload,
        )
        assignment_replay = restarted_client.post(
            "/internal/runtime/assign",
            headers=_headers(developer_assignment_token),
            json=_assignment("DEV-34", "assign-dev-34", "developer"),
        )

    assert step_before_bind.status_code == 409
    assert unbound_history.status_code == 200
    assert unbound_history.json()["result"]["records"] == []
    assert execution_token_bind.status_code == 403
    assert wrong_role_bind.status_code == 409
    assert unknown_token_bind.status_code == 401
    assert bound.status_code == 200
    assert bound.json()["result"]["binding_state"] == "bound"
    assert bound.json()["result"]["binding_ref"] == "business-binding:real-34"
    assert bound.json()["result"]["hermes_run_ref"] == "hermes-session:real-run-34"
    assert replay.status_code == 200
    assert replay.json()["result"] == bound.json()["result"]
    assert changed_same_key.status_code == 409
    assert second_binding.status_code == 409
    assert after_restart.status_code == 200
    assert after_restart.json()["result"] == bound.json()["result"]
    assert assignment_replay.status_code == 200
    assert assignment_replay.json()["result"]["binding_state"] == "bound"
    assert assignment_replay.json()["result"]["hermes_run_ref"] == "hermes-session:real-run-34"


def test_concurrent_identical_runtime_bind_has_one_durable_binding(monkeypatch):
    assignment_token = "concurrent-assignment-token-1234"
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")
    with TestClient(create_app()) as client:
        accepted = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("DEV-35", "assign-dev-35", "developer"),
        ).json()["result"]
    payload = _bind_payload(accepted)
    barrier = Barrier(2)

    def bind_once() -> tuple[int, dict[str, object]]:
        barrier.wait(timeout=5)
        with TestClient(create_app()) as client:
            response = client.post(
                "/internal/runtime/bind",
                headers=_headers(assignment_token),
                json=payload,
            )
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _index: bind_once(), range(2)))

    assert [status for status, _body in responses] == [200, 200]
    assert all(body["result"]["binding_state"] == "bound" for _status, body in responses)
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("DEV-35")
        assert task is not None and task.id is not None
        assignments = uow.tasks.list_assignments(task.id)
        assert len(assignments) == 1
        assert assignments[0].binding_ref == "binding:assign-dev-35"
        assert assignments[0].hermes_run_ref == "hermes-run:assign-dev-35"
        assert assignments[0].bind_request_sha256 is not None
        assert len(assignments[0].bind_request_sha256) == 64


def test_runtime_step_rejects_old_run_when_same_cycle_retry_wins_during_evaluation(
    monkeypatch,
):
    runtime_token = "r" * 32
    assignment_token = "q" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")

    with TestClient(create_app()) as client:
        assigned_response = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("DEV-7", "assign-dev-7-attempt-1", "developer"),
        )
        assert assigned_response.status_code == 200
        assigned = _bind_assignment(
            client, assignment_token, assigned_response.json()["result"]
        )

        def retry_during_provider_call(*_args, **_kwargs):
            with SAUnitOfWork() as uow:
                task = uow.tasks.get_by_key("DEV-7")
                assert task is not None and task.id is not None
                project_id = task.project_id
                uow.tasks.update(task.id, {"status": "done"})
                uow.commit()
                retry_assignment = TaskService(uow).assign_runtime_task(
                    **_service_assignment(
                        project_id=project_id,
                        task="DEV-7",
                        operation_key="assign-dev-7-attempt-2",
                        role="developer",
                        attempt_number=2,
                        assignment_ref="assignment:assign-dev-7-attempt-2",
                        tech_execution_workspace_ref="tech-workspace:DEV-7-retry",
                        tech_execution_attempt_ref="tech-attempt:DEV-7-retry",
                        workspace_generation=2,
                        lease_generation=2,
                        expected_revision=1,
                        expected_status="done",
                    )
                )
                _service_bind(
                    uow,
                    project_id=project_id,
                    role="developer",
                    assignment=retry_assignment,
                )
            return {
                "verdict": "PASS",
                "covered": [],
                "missing": [],
                "blockers": [],
                "message": "late result",
                "confidence": 1.0,
            }

        with patch.object(OpenAICompatibleClient, "chat", side_effect=retry_during_provider_call):
            stale = client.post(
                "/internal/runtime/step",
                headers=_headers(runtime_token),
                json=_step_payload(assigned, "Старый run завершился поздно"),
            )

    assert stale.status_code == 409
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("DEV-7")
        assert task is not None and task.id is not None
        assert task.assignment_revision == 2
        assert task.status == "active"
        assert uow.step_history.list(task_id=task.id, limit=None) == []
        events = uow.tasks.list_phase_events(task.id)
        assert len(events) == 2
        assert [event.cycle_number for event in events] == [0, 0]


def test_runtime_step_rejects_old_run_after_new_cycle_without_writing_history(monkeypatch):
    runtime_token = "u" * 32
    assignment_token = "v" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")

    with TestClient(create_app()) as client:
        assigned_response = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("DEV-8", "assign-dev-8-cycle-0", "developer"),
        )
        assert assigned_response.status_code == 200
        old_assignment = _bind_assignment(
            client, assignment_token, assigned_response.json()["result"]
        )
        with SAUnitOfWork() as uow:
            task = uow.tasks.get_by_key("DEV-8")
            assert task is not None and task.id is not None
            project_id = task.project_id
            uow.tasks.update(task.id, {"status": "done"})
            uow.commit()
            next_assignment = TaskService(uow).assign_runtime_task(
                **_service_assignment(
                    project_id=project_id,
                    task="DEV-8",
                    operation_key="assign-dev-8-cycle-1",
                    role="developer",
                    cycle_number=1,
                    assignment_ref="assignment:assign-dev-8-cycle-1",
                    tech_execution_workspace_ref="tech-workspace:DEV-8-cycle-1",
                    tech_execution_attempt_ref="tech-attempt:DEV-8-cycle-1",
                    workspace_generation=2,
                    lease_generation=2,
                    expected_revision=1,
                    expected_status="done",
                    expected_mode_key="assigned",
                    expected_cycle_number=0,
                )
            )
            _service_bind(
                uow,
                project_id=project_id,
                role="developer",
                assignment=next_assignment,
            )
        stale = client.post(
            "/internal/runtime/step",
            headers=_headers(runtime_token),
            json=_step_payload(old_assignment, "Поздний результат старого цикла"),
        )

    assert stale.status_code == 409
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("DEV-8")
        assert task is not None and task.id is not None
        assert task.assignment_revision == 2
        assert task.cycle_number == 1
        assert uow.step_history.list(task_id=task.id, limit=None) == []
        assert [event.cycle_number for event in uow.tasks.list_phase_events(task.id)] == [0, 1]


def test_runtime_step_replays_committed_response_before_cursor_rejection(
    monkeypatch, supervisor_llm
):
    runtime_token = "m" * 32
    assignment_token = "n" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")
    supervisor_llm("PASS")

    with TestClient(create_app()) as client:
        accepted = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("DEV-20", "assign-dev-20", "developer"),
        ).json()["result"]
        assigned = _bind_assignment(client, assignment_token, accepted)
        payload = _step_payload(
            assigned,
            "Готово",
            step_operation_key="step:DEV-20:complete",
        )
        first = client.post(
            "/internal/runtime/step", headers=_headers(runtime_token), json=payload
        )
        replay = client.post(
            "/internal/runtime/step", headers=_headers(runtime_token), json=payload
        )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    result = first.json()["result"]
    assert result["replayed"] is False
    assert result["binding_state"] == "bound"
    assert result["assignment_revision"] == 1
    assert result["assignment_ref"] == assigned["assignment_ref"]
    assert result["binding_ref"] == assigned["binding_ref"]
    assert result["hermes_run_ref"] == assigned["hermes_run_ref"]
    assert result["mode_key"] == "assigned"
    assert result["cycle_number"] == 0
    assert result["attempt_number"] == 1
    assert result["status"] == "done"
    assert result["current_phase_code"] == "assigned"
    assert result["current_phase_name"] == "Assigned"
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("DEV-20")
        assert task is not None and task.id is not None
        history = uow.step_history.list(task_id=task.id, limit=None)
        assert len(history) == 1
        assert history[0].step_operation_key == "step:DEV-20:complete"
        assert history[0].request_sha256 is not None
        assert history[0].assignment_revision == 1
        assert history[0].hermes_run_ref == assigned["hermes_run_ref"]
        assert history[0].supervisor_response == result
        assert len(uow.tasks.list_phase_events(task.id)) == 2


def test_runtime_step_returns_fresh_next_phase_cursor(monkeypatch, supervisor_llm):
    runtime_token = "next-phase-runtime-token-1234567"
    assignment_token = "next-phase-assignment-token-1234"
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")
    with SAUnitOfWork() as uow:
        project = next(
            item for item in uow.projects.list() if item.cli_command == "workflow-developer"
        )
        assert project.workflow_id is not None
        mode = uow.workflows.get_mode_by_key(project.workflow_id, "assigned")
        assert mode is not None and mode.id is not None
        uow.phases.create(
            {
                "workflow_id": project.workflow_id,
                "mode_id": mode.id,
                "code": "review",
                "name": "Review",
                "phase_order": 2,
            }
        )
        uow.commit()
    supervisor_llm("PASS")

    with TestClient(create_app()) as client:
        accepted = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("DEV-26", "assign-dev-26", "developer"),
        ).json()["result"]
        assigned = _bind_assignment(client, assignment_token, accepted)
        payload = _step_payload(
            assigned,
            "Первая фаза завершена",
            step_operation_key="step:DEV-26:assigned",
        )
        first = client.post(
            "/internal/runtime/step", headers=_headers(runtime_token), json=payload
        )
        replay = client.post(
            "/internal/runtime/step", headers=_headers(runtime_token), json=payload
        )

    assert first.status_code == 200
    assert replay.json() == first.json()
    result = first.json()["result"]
    assert result["phase_code"] == "assigned"
    assert result["current_phase_code"] == "review"
    assert result["current_phase_name"] == "Review"
    assert result["status"] == "active"


def test_runtime_step_operation_key_rejects_changed_payload(monkeypatch, supervisor_llm):
    runtime_token = "o" * 32
    assignment_token = "p" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")
    supervisor_llm("PASS")

    with TestClient(create_app()) as client:
        accepted = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("DEV-21", "assign-dev-21", "developer"),
        ).json()["result"]
        assigned = _bind_assignment(client, assignment_token, accepted)
        original = _step_payload(
            assigned,
            "Первый отчёт",
            step_operation_key="step:DEV-21:complete",
        )
        first = client.post(
            "/internal/runtime/step", headers=_headers(runtime_token), json=original
        )
        changed = client.post(
            "/internal/runtime/step",
            headers=_headers(runtime_token),
            json={**original, "report": "Другой отчёт"},
        )

    assert first.status_code == 200
    assert changed.status_code == 409
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("DEV-21")
        assert task is not None and task.id is not None
        assert len(uow.step_history.list(task_id=task.id, limit=None)) == 1


def test_runtime_step_integrity_error_replays_from_fresh_uow(monkeypatch):
    runtime_token = "fresh-transaction-runtime-token-123"
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    config.get_settings.cache_clear()
    payload = RuntimeStepRequest.model_validate(
        {**_unknown_step_payload("DEV-25"), "report": "Готово"}
    )
    first_uow = MagicMock()
    first_uow.__enter__.return_value = first_uow
    first_uow.__exit__.return_value = False
    replay_uow = MagicMock()
    replay_uow.__enter__.return_value = replay_uow
    replay_uow.__exit__.return_value = False
    replay_response = {
        "ok": True,
        "exit_code": 0,
        "output": "replayed",
        "result": {"replayed": True},
    }

    with (
        patch.object(runtime_api, "SAUnitOfWork", side_effect=[first_uow, replay_uow]) as factory,
        patch.object(runtime_api, "_namespace_id", return_value=1),
        patch.object(runtime_api, "_require_valid_key", return_value="DEV-25"),
        patch.object(runtime_api, "_assert_task_key_in_namespace"),
        patch.object(runtime_api, "_runtime_step_replay", side_effect=[None, replay_response]),
        patch.object(TaskService, "validate_runtime_step", return_value=MagicMock()),
        patch.object(
            runtime_api,
            "execute_namespace_step",
            side_effect=IntegrityError("duplicate operation key", {}, RuntimeError("race")),
        ),
    ):
        response = runtime_api.runtime_step(
            payload,
            authorization=f"Bearer {runtime_token}",
        )

    assert response == replay_response
    assert factory.call_count == 2
    assert first_uow is not replay_uow


def test_completed_step_cannot_replay_into_retry_or_new_cycle(monkeypatch, supervisor_llm):
    runtime_token = "g" * 32
    assignment_token = "h" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")
    supervisor_llm("PASS")

    for task_key, next_cycle in (("DEV-22", 0), ("DEV-23", 1)):
        with TestClient(create_app()) as client:
            accepted = client.post(
                "/internal/runtime/assign",
                headers=_headers(assignment_token),
                json=_assignment(task_key, f"assign-{task_key}-initial", "developer"),
            ).json()["result"]
            initial = _bind_assignment(client, assignment_token, accepted)
            old_payload = _step_payload(
                initial,
                "Готово",
                step_operation_key=f"step:{task_key}:complete",
            )
            completed = client.post(
                "/internal/runtime/step",
                headers=_headers(runtime_token),
                json=old_payload,
            )
            assert completed.status_code == 200
            with SAUnitOfWork() as uow:
                task = uow.tasks.get_by_key(task_key)
                assert task is not None and task.id is not None
                project_id = task.project_id
                next_assignment = TaskService(uow).assign_runtime_task(
                    **_service_assignment(
                        project_id=project_id,
                        task=task_key,
                        operation_key=f"assign-{task_key}-next",
                        role="developer",
                        cycle_number=next_cycle,
                        attempt_number=2 if next_cycle == 0 else 1,
                        assignment_ref=f"assignment:assign-{task_key}-next",
                        tech_execution_workspace_ref=f"tech-workspace:{task_key}-next",
                        tech_execution_attempt_ref=f"tech-attempt:{task_key}-next",
                        workspace_generation=2,
                        lease_generation=2,
                        expected_revision=1,
                        expected_status="done",
                        expected_mode_key="assigned",
                        expected_cycle_number=0,
                    )
                )
                _service_bind(
                    uow,
                    project_id=project_id,
                    role="developer",
                    assignment=next_assignment,
                )
            stale = client.post(
                "/internal/runtime/step",
                headers=_headers(runtime_token),
                json=old_payload,
            )
            assert stale.status_code == 409
            with SAUnitOfWork() as uow:
                task = uow.tasks.get_by_key(task_key)
                assert task is not None and task.id is not None
                assert len(uow.step_history.list(task_id=task.id, limit=None)) == 1
                assert len(uow.tasks.list_phase_events(task.id)) == 3


def test_concurrent_identical_runtime_step_has_one_durable_mutation(
    monkeypatch,
):
    runtime_token = "i" * 32
    assignment_token = "j" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")
    with TestClient(create_app()) as setup_client:
        accepted = setup_client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("DEV-24", "assign-dev-24", "developer"),
        ).json()["result"]
        assigned = _bind_assignment(setup_client, assignment_token, accepted)
    payload = _step_payload(
        assigned,
        "Готово",
        step_operation_key="step:DEV-24:complete",
    )
    nested_responses: list[tuple[int, dict]] = []
    nested_started = False

    def pass_with_duplicate_arrival(*_args, **_kwargs):
        nonlocal nested_started
        if not nested_started:
            nested_started = True
            with TestClient(create_app()) as duplicate_client:
                duplicate = duplicate_client.post(
                    "/internal/runtime/step",
                    headers=_headers(runtime_token),
                    json=payload,
                )
                nested_responses.append((duplicate.status_code, duplicate.json()))
        return {
            "verdict": "PASS",
            "covered": [],
            "missing": [],
            "blockers": [],
            "message": "concurrent pass",
            "confidence": 1.0,
        }

    with patch.object(OpenAICompatibleClient, "chat", side_effect=pass_with_duplicate_arrival):
        with TestClient(create_app()) as client:
            original = client.post(
                "/internal/runtime/step",
                headers=_headers(runtime_token),
                json=payload,
            )
            responses = nested_responses + [(original.status_code, original.json())]

    assert [status for status, _body in responses] == [200, 200]
    assert responses[0][1] == responses[1][1]
    assert responses[0][1]["result"]["replayed"] is False
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("DEV-24")
        assert task is not None and task.id is not None
        assert len(uow.step_history.list(task_id=task.id, limit=None)) == 1
        assert len(uow.tasks.list_phase_events(task.id)) == 2
