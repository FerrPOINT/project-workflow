"""Focused coverage for UI API error mapping branches."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.responses import JSONResponse

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.interfaces.ui.routes import api
from project_workflow.interfaces.ui.schemas import (
    AgentCreate,
    AgentUpdate,
    InstructionCreate,
    InstructionReorder,
    InstructionUpdate,
    NamespaceCreate,
    NamespaceUpdate,
    PhaseCreate,
    PhaseOrderUpdate,
    PhaseUpdate,
    WorkflowCreate,
    WorkflowUpdate,
)

pytestmark = [pytest.mark.ui]


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _raise(exc: Exception) -> None:
    raise exc


def _json(response: JSONResponse) -> dict[str, Any]:
    return json.loads(response.body)


class _State:
    def __init__(self, **services: Any) -> None:
        self._services = services

    def get_service(self) -> Any:
        return self._services["detail_service"]

    def phase_service(self) -> Any:
        return self._services["phase_service"]

    def workflow_service(self) -> Any:
        return self._services["workflow_service"]

    def project_service(self) -> Any:
        return self._services["project_service"]

    def agent_service(self) -> Any:
        return self._services["agent_service"]

    def instruction_service(self) -> Any:
        return self._services["instruction_service"]


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (NotFoundError("Фаза не найдена"), 404),
        (ConflictError("Конфликт графа фаз"), 409),
        (ValueError("Некорректная фаза"), 422),
    ],
)
def test_phase_create_maps_service_errors(monkeypatch, exc, status):
    monkeypatch.setattr(
        api,
        "_app_state",
        _State(phase_service=SimpleNamespace(create_phase=lambda _data: _raise(exc))),
    )

    response = _run(
        api.api_phase_create(PhaseCreate(workflow_id=1, phase_order=1, name="Новая фаза"))
    )

    assert response.status_code == status
    assert _json(response)["error"] == str(exc)


def test_phase_update_maps_aggregate_value_error(monkeypatch):
    monkeypatch.setattr(
        api,
        "_app_state",
        _State(
            detail_service=SimpleNamespace(
                update_phase_detail=lambda _phase_id, _aggregate: _raise(ValueError("bad nested item"))
            )
        ),
    )

    response = _run(
        api.api_phase_update(
            7,
            PhaseUpdate(
                description="Новая формулировка",
                checks=[{"id": None, "description": "Новая проверка"}],
            ),
        )
    )

    assert response.status_code == 422
    assert _json(response)["error"] == "bad nested item"


def test_phase_batch_order_rejects_workflow_owner_mismatch(monkeypatch):
    monkeypatch.setattr(
        api,
        "_app_state",
        _State(phase_service=SimpleNamespace(get_phase=lambda _phase_id: {"workflow_id": 2})),
    )

    response = _run(
        api.api_phase_batch_order(
            PhaseOrderUpdate(orders=[{"phase_id": 1, "phase_order": 1, "workflow_id": 1}])
        )
    )

    assert response.status_code == 409
    assert _json(response)["error"] == "workflow_id не совпадает с владельцем фазы"


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (ConflictError("Workflow conflict"), 409),
        (ValueError("Workflow value"), 422),
    ],
)
def test_workflow_create_maps_service_errors(monkeypatch, exc, status):
    monkeypatch.setattr(
        api,
        "_app_state",
        _State(workflow_service=SimpleNamespace(create_workflow=lambda _data: _raise(exc))),
    )

    response = _run(api.api_workflow_create(WorkflowCreate(name="Flow")))

    assert response.status_code == status
    assert _json(response)["error"] == str(exc)


def test_namespace_create_rejects_explicit_null_description():
    response = _run(
        api.api_namespace_create(
            NamespaceCreate(
                name="Namespace",
                description=None,
                workflow_id=1,
                cli_command="workflow-prj",
            )
        )
    )

    assert response.status_code == 422
    assert _json(response)["error"] == "description не может быть null"


def test_namespace_update_maps_value_error_before_readback(monkeypatch):
    service = SimpleNamespace(
        update_project=lambda _namespace_id, _updates: _raise(ValueError("bad namespace")),
        get_project=lambda _namespace_id: pytest.fail("namespace readback must not happen after error"),
    )
    monkeypatch.setattr(api, "_app_state", _State(project_service=service))

    response = _run(api.api_namespace_update(5, NamespaceUpdate(name="PX")))

    assert response.status_code == 422
    assert _json(response)["error"] == "bad namespace"


@pytest.mark.parametrize(
    ("route", "payload", "service_method", "exc", "status"),
    [
        (
            api.api_workflow_update,
            WorkflowUpdate(name="W"),
            "update_workflow",
            NotFoundError("Воркфлоу 1 не найден"),
            404,
        ),
        (api.api_workflow_update, WorkflowUpdate(name="W"), "update_workflow", ConflictError("Workflow conflict"), 409),
        (api.api_workflow_update, WorkflowUpdate(name="W"), "update_workflow", ValueError("Workflow value"), 422),
        (api.api_agent_update, AgentUpdate(name="A"), "update_agent", NotFoundError("Агент 1 не найден"), 404),
        (api.api_agent_update, AgentUpdate(name="A"), "update_agent", ConflictError("Agent conflict"), 409),
        (api.api_agent_update, AgentUpdate(name="A"), "update_agent", ValueError("Agent value"), 422),
    ],
)
def test_update_routes_map_service_errors(monkeypatch, route, payload, service_method, exc, status):
    service = SimpleNamespace(
        **{
            service_method: lambda _entity_id, _updates: _raise(exc),
            "get_workflow": lambda _entity_id: {"id": _entity_id},
            "get_agent": lambda _entity_id: {"id": _entity_id},
        }
    )
    state_method = "workflow_service" if service_method == "update_workflow" else "agent_service"
    monkeypatch.setattr(api, "_app_state", _State(**{state_method: service}))

    response = _run(route(1, payload))

    assert response.status_code == status
    assert _json(response)["error"] == str(exc)


@pytest.mark.parametrize(
    ("route", "service_method", "exc", "status"),
    [
        (api.api_namespace_delete, "delete_project", NotFoundError("Неймспейс 1 не найден"), 404),
        (api.api_namespace_delete, "delete_project", ConflictError("Namespace conflict"), 409),
        (api.api_agent_delete, "delete_agent", NotFoundError("Агент 1 не найден"), 404),
        (api.api_agent_delete, "delete_agent", ConflictError("Agent conflict"), 409),
    ],
)
def test_delete_routes_map_service_errors(monkeypatch, route, service_method, exc, status):
    service = SimpleNamespace(**{service_method: lambda _entity_id: _raise(exc)})
    state_method = "project_service" if service_method == "delete_project" else "agent_service"
    monkeypatch.setattr(api, "_app_state", _State(**{state_method: service}))

    response = _run(route(1))

    assert response.status_code == status
    assert _json(response)["error"] == str(exc)


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (ConflictError("Agent profile conflict"), 409),
        (ValueError("Agent profile bad"), 422),
    ],
)
def test_agent_create_maps_service_errors(monkeypatch, exc, status):
    monkeypatch.setattr(
        api,
        "_app_state",
        _State(agent_service=SimpleNamespace(create_agent=lambda _data: _raise(exc))),
    )

    response = _run(api.api_agent_create(AgentCreate(name="Agent")))

    assert response.status_code == status
    assert _json(response)["error"] == str(exc)


def test_instructions_list_rejects_unknown_phase(monkeypatch):
    monkeypatch.setattr(
        api,
        "_app_state",
        _State(phase_service=SimpleNamespace(get_phase=lambda _phase_id: None)),
    )

    response = _run(api.api_instructions_list(44))

    assert response.status_code == 404
    assert _json(response)["error"] == "Фаза 44 не найдена"


@pytest.mark.parametrize(
    ("route", "args", "service_method", "exc", "status"),
    [
        (
            api.api_instruction_create,
            (InstructionCreate(phase_id=1, description="Step"),),
            "create_instruction",
            NotFoundError("Фаза 1 не найдена"),
            404,
        ),
        (
            api.api_instruction_create,
            (InstructionCreate(phase_id=1, description="Step"),),
            "create_instruction",
            ConflictError("Instruction conflict"),
            409,
        ),
        (
            api.api_instruction_create,
            (InstructionCreate(phase_id=1, description="Step"),),
            "create_instruction",
            ValueError("Instruction value"),
            422,
        ),
        (
            api.api_instruction_update,
            (3, InstructionUpdate(description="Step")),
            "update_instruction",
            NotFoundError("Инструкция 3 не найдена"),
            404,
        ),
        (
            api.api_instruction_update,
            (3, InstructionUpdate(description="Step")),
            "update_instruction",
            ConflictError("Instruction update conflict"),
            409,
        ),
        (
            api.api_instruction_update,
            (3, InstructionUpdate(description="Step")),
            "update_instruction",
            ValueError("Instruction update value"),
            422,
        ),
        (
            api.api_instruction_delete,
            (3,),
            "delete_instruction",
            NotFoundError("Инструкция 3 не найдена"),
            404,
        ),
        (
            api.api_instruction_delete,
            (3,),
            "delete_instruction",
            ConflictError("Instruction delete conflict"),
            409,
        ),
        (
            api.api_instructions_reorder,
            (1, InstructionReorder(instruction_ids=[1])),
            "reorder_instructions",
            ValueError("Instruction reorder value"),
            422,
        ),
    ],
)
def test_instruction_routes_map_service_errors(monkeypatch, route, args, service_method, exc, status):
    def failing_method(*_args: Any) -> None:
        _raise(exc)

    service = SimpleNamespace(
        **{
            service_method: failing_method,
            "get_instruction": lambda _instruction_id: {"id": _instruction_id},
        }
    )
    monkeypatch.setattr(api, "_app_state", _State(instruction_service=service))

    response = _run(route(*args))

    assert response.status_code == status
    assert _json(response)["error"] == str(exc)
