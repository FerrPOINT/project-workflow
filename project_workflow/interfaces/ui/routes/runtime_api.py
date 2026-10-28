"""Common configured CLI API and read-only catalog/legacy receipt helpers."""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from project_workflow import config
from project_workflow.build_provenance import (
    BuildProvenanceError,
    load_build_provenance,
)
from project_workflow.domain.base_binding import DatabaseId
from project_workflow.domain.configured_cli import (
    ConfiguredArtifactReadback,
    ConfiguredAssignment,
    ConfiguredStep,
    ConfiguredTerminalReadback,
)
from project_workflow.domain.runtime_assignment import (
    MANAGED_ROLE_MODE_SCOPES,
    MANAGED_WORKFLOW_KEYS,
    normalize_role_key,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork

_CATALOG_ROLE = "fleet-control"


@dataclass(frozen=True)
class _ServiceCredential:
    role_key: str
    kind: str



def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def _configured_tokens(setting_name: str) -> dict[str, str]:
    raw = str(getattr(config.get_settings(), setting_name)).strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Некорректная конфигурация runtime tokens") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Некорректная конфигурация runtime tokens")
    result: dict[str, str] = {}
    for role, token in value.items():
        try:
            normalized_role = normalize_role_key(role)
        except ValueError as exc:
            raise RuntimeError("Некорректная конфигурация runtime tokens") from exc
        if not isinstance(token, str) or len(token) < 32 or normalized_role in result:
            raise RuntimeError("Некорректная конфигурация runtime tokens")
        result[normalized_role] = token
    if len(result.values()) != len(set(result.values())):
        raise RuntimeError("Runtime tokens должны быть уникальными")
    return result


def _token_configuration() -> tuple[dict[str, str], dict[str, str], str]:
    runtime_tokens = _configured_tokens("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON")
    assignment_tokens = _configured_tokens("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON")
    catalog_token = config.get_settings().PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN.strip()
    if catalog_token and len(catalog_token) < 32:
        raise RuntimeError("Некорректная конфигурация Fleet catalog token")
    runtime_values = set(runtime_tokens.values())
    assignment_values = set(assignment_tokens.values())
    if runtime_values & assignment_values:
        raise RuntimeError("Assignment tokens должны отличаться от runtime и catalog tokens")
    if catalog_token and catalog_token in runtime_values | assignment_values:
        raise RuntimeError("Service tokens разных ролей должны быть уникальными")
    return runtime_tokens, assignment_tokens, catalog_token


def _authorized_assignment_role(authorization: str | None) -> str | None:
    credential = _authorized_service_credential(authorization, single_task=True)
    if credential is None or credential.kind != "assignment":
        return None
    return credential.role_key


def _authorized_service_credential(
    authorization: str | None,
    *, single_task: bool = False,
) -> _ServiceCredential | None:
    """Match all configured service credentials without value-based early exits."""
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        return None
    supplied = authorization[len(prefix) :]
    runtime_tokens, assignment_tokens, catalog_token = _token_configuration()
    matches: list[_ServiceCredential] = []
    for role, expected in runtime_tokens.items():
        if hmac.compare_digest(supplied, expected):
            matches.append(_ServiceCredential(role_key=role, kind="runtime"))
    for role, expected in assignment_tokens.items():
        if hmac.compare_digest(supplied, expected):
            matches.append(_ServiceCredential(role_key=role, kind="assignment"))
    if catalog_token and hmac.compare_digest(supplied, catalog_token):
        matches.append(_ServiceCredential(role_key=_CATALOG_ROLE, kind="catalog"))
    if len(matches) > 1:
        # _token_configuration normally catches this. Keep the auth boundary
        # fail-closed if configuration changes between validation and matching.
        raise RuntimeError("Service token configuration collision")
    credential = matches[0] if matches else None
    if credential is not None and credential.kind != "catalog" and config.CATALOG_VARIANT == "base" and not single_task:
        raise RuntimeError("Base assigned execution is not enabled; catalog credentials only")
    return credential


def runtime_capabilities(
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Return authenticated runtime contract and immutable build provenance."""
    try:
        credential = _authorized_service_credential(authorization, single_task=True)
    except RuntimeError:
        return _error("Runtime capability configuration unavailable", 503)
    if credential is None:
        return _error("Недействительный runtime token", 401)
    if credential.kind != "assignment":
        return _error("Configured role reader required", 403)

    try:
        provenance = load_build_provenance()
        provenance_ready = True
    except BuildProvenanceError:
        provenance = None
        provenance_ready = False

    schema_ready = False
    catalog_ready = False
    try:
        from project_workflow.infrastructure.db import session as db_session

        engine = db_session.get_engine()
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        schema_ready = db_session.schema_is_ready(engine)
    except Exception:
        schema_ready = False
    if schema_ready:
        try:
            with SAUnitOfWork(engine) as uow:
                from project_workflow.infrastructure.db.single_task_catalog import observe_installation

                installation = observe_installation(uow)
                if not any(b.role_key == credential.role_key for b in installation.bindings):
                    raise ValueError("Installed profession required")
                catalog_ready = True
        except Exception:
            catalog_ready = False

    if not provenance_ready or not schema_ready or not catalog_ready:
        return JSONResponse(
            {
                "ok": False,
                "error": "Runtime capabilities временно недоступны",
                "error_code": "runtime-capabilities-not-ready",
                "readiness": {
                    "service": "not_ready",
                    "schema": "ready" if schema_ready else "not_ready",
                    "catalog": "ready" if catalog_ready else "not_ready",
                },
            },
            status_code=503,
        )

    return {
        "ok": True,
        "role_key": credential.role_key,
        "credential_kind": credential.kind,
        "interaction_protocol": "configured-cli-v1",
        "capabilities": ["assign", "history", "terminal-readback"],
        "readiness": {"service": "ready", "schema": "ready", "catalog": "ready"},
        "source_provenance": provenance.to_dict() if provenance is not None else {},
        "instruction_profile": installation.instruction_profile,
        "instruction_manifest_sha256": installation.instruction_manifest_sha256,
        "workflow_catalog_sha256": installation.workflow_catalog_sha256,
    }


def _single_task_observation(authorization: str | None) -> Any:
    """Existing catalog credential; persisted observation only, no new registry."""
    from project_workflow.domain.single_task_profile import SingleTaskInstallationResponse
    from project_workflow.infrastructure.db.single_task_catalog import observe_installation

    try:
        credential = _authorized_service_credential(authorization, single_task=True)
        if credential is None:
            return _error("Invalid catalog credential", 401)
        if credential.kind != "catalog":
            return _error("Catalog credential required", 403)
        with SAUnitOfWork() as uow:
            result = observe_installation(uow)
        return SingleTaskInstallationResponse(installation=result)
    except ValueError:
        return _error("Single-task installation missing or divergent", 409)
    except (RuntimeError, OSError, SQLAlchemyError):
        return _error("Single-task installation observation unavailable", 503)


def single_task_installation(authorization: str | None = Header(default=None)) -> JSONResponse:
    result = _single_task_observation(authorization)
    if isinstance(result, JSONResponse):
        return result
    return JSONResponse(result.model_dump(mode="json", by_alias=True), headers={"Cache-Control": "no-store"})


def single_task_namespace_binding(namespace_id: str, authorization: str | None = Header(default=None)) -> Any:
    from project_workflow.domain.base_binding import DatabaseId
    from project_workflow.domain.single_task_profile import SingleTaskBindingResponse

    result = _single_task_observation(authorization)
    if isinstance(result, JSONResponse):
        return result
    from pydantic import TypeAdapter, ValidationError

    try:
        namespace_id = TypeAdapter(DatabaseId).validate_python(namespace_id)
    except ValidationError:
        return _error("Canonical namespace ID required", 422)
    binding = next((b for b in result.installation.bindings if b.namespace_id == namespace_id), None)
    if binding is None:
        return _error("Single-task namespace not found", 404)
    response = SingleTaskBindingResponse(binding=binding)
    return JSONResponse(response.model_dump(mode="json", by_alias=True), headers={"Cache-Control": "no-store"})


def runtime_catalog(
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Expose only the namespace/workflow directory to Fleet Control."""
    try:
        credential = _authorized_service_credential(authorization)
    except RuntimeError as exc:
        return _error(str(exc), 503)
    if credential is None:
        return _error("Недействительный runtime token", 401)
    if credential.kind != "catalog" or credential.role_key != _CATALOG_ROLE:
        return _error("Токен не разрешает чтение каталога", 403)
    from . import api

    namespaces = api.api_namespaces()
    workflows = api.api_workflows()
    namespace_items = namespaces.get("namespaces") if isinstance(namespaces, dict) else None
    workflow_items = workflows.get("workflows") if isinstance(workflows, dict) else None
    if not isinstance(namespace_items, list) or not isinstance(workflow_items, list):
        return _error("Каталог временно недоступен", 503)
    from project_workflow.domain.single_task_profile import PROFILE, is_single_task_key
    from project_workflow.infrastructure.db.single_task_catalog import observe_installation

    if (config.CATALOG_VARIANT == PROFILE
        or any(isinstance(item, dict) and is_single_task_key(item.get("key")) for item in workflow_items)
        or any(isinstance(item, dict) and str(item.get("cli_command", "")).startswith("workflow-single-task-")
               for item in namespace_items)):
        try:
            with SAUnitOfWork() as uow:
                installation = observe_installation(uow)
                return {
                    "ok": True,
                    "namespaces": [
                        {"id": int(binding.namespace_id), "name": binding.namespace_name,
                         "cli_command": binding.namespace_cli_command, "launch_profile": binding.profile,
                         "workflow_id": int(binding.workflow_id)}
                        for binding in installation.bindings
                    ],
                    "workflows": [
                        {"id": int(binding.workflow_id), "key": binding.workflow_key,
                         "name": config.MANAGED_NAMESPACE_WORKFLOW_NAME}
                        for binding in installation.bindings
                    ],
                }
        except ValueError:
            return _error("Single-task installation missing or divergent", 503)
        except (RuntimeError, OSError, SQLAlchemyError):
            return _error("Single-task installation observation unavailable", 503)
    managed_namespace_commands = {f"workflow-{role_key}" for role_key in MANAGED_ROLE_MODE_SCOPES}
    managed_namespaces = [
        item
        for item in namespace_items
        if isinstance(item, dict) and item.get("cli_command") in managed_namespace_commands
    ]
    managed_workflows = [
        item for item in workflow_items if isinstance(item, dict) and item.get("key") in MANAGED_WORKFLOW_KEYS
    ]
    if (
        len(managed_namespaces) != len(managed_namespace_commands)
        or {item.get("cli_command") for item in managed_namespaces} != managed_namespace_commands
        or len(managed_workflows) != len(MANAGED_WORKFLOW_KEYS)
        or {item.get("key") for item in managed_workflows} != MANAGED_WORKFLOW_KEYS
    ):
        return _error("Managed каталог временно недоступен", 503)
    keys_by_id = {item.get("id"): item.get("key") for item in managed_workflows}
    if any(
        keys_by_id.get(item.get("workflow_id")) != f"hermes-sdlc:{item['cli_command'].removeprefix('workflow-')}"
        for item in managed_namespaces
    ):
        return _error("Managed каталог временно недоступен", 503)
    return {
        "ok": True,
        "namespaces": managed_namespaces,
        "workflows": managed_workflows,
    }


def runtime_assign(
    payload: ConfiguredAssignment,
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    from . import configured_cli_api

    return configured_cli_api.assign(payload, authorization)


def runtime_step(
    payload: ConfiguredStep,
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    from . import configured_cli_api

    return configured_cli_api.step(payload, authorization)


def runtime_history(
    task: str = Query(...),
    n: int = Query(default=200, ge=1, le=200),
    authorization: str | None = Header(default=None),
    interaction_protocol: Literal["configured-cli-v1"] = Query(...),
    namespace_id: int = Query(..., gt=0),
    execution_ref: str | None = Query(default=None),
    operation_key: str | None = Query(default=None),
    assignment_operation_key: str | None = Query(default=None, min_length=1, max_length=128),
    projection: Literal["fleet-summary-v1"] | None = Query(default=None),
    before_history_id: DatabaseId | None = Query(default=None),
) -> dict[str, Any] | JSONResponse:
    """Read configured operations or retained history through the same authority."""
    from . import configured_cli_api

    return configured_cli_api.history(
        task, namespace_id, authorization, n=n, execution_ref=execution_ref,
        operation_key=operation_key, assignment_operation_key=assignment_operation_key,
        projection=projection, before_history_id=int(before_history_id) if before_history_id is not None else None,
    )


def runtime_terminal_readback(
    payload: ConfiguredTerminalReadback | ConfiguredArtifactReadback,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    from . import configured_cli_api

    if isinstance(payload, ConfiguredArtifactReadback):
        return configured_cli_api.artifact_readback(payload, authorization)
    return configured_cli_api.terminal_readback(payload, authorization)
