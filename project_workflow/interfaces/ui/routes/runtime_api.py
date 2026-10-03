"""Private role-scoped runtime bridge for isolated Hermes wrappers."""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from typing import Any

from fastapi import Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from project_workflow import config, supervisor
from project_workflow.application.base_admission import admission_receipt, assert_base_step
from project_workflow.application.state import _app_state
from project_workflow.application.task import TaskService
from project_workflow.build_provenance import (
    BuildProvenanceError,
    load_build_provenance,
    runtime_compatibility_descriptor,
)
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import (
    MANAGED_ROLE_MODE_SCOPES,
    MANAGED_WORKFLOW_KEYS,
    RuntimeStepFence,
    normalize_role_key,
    payload_sha256,
    phase_allowed_tools,
)
from project_workflow.infrastructure.db.managed_catalog import validate_managed_catalog_state
from project_workflow.infrastructure.db.models import PMExecution, PMRun
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.cli.core import _require_valid_key, _resolve_namespace_id
from project_workflow.interfaces.ui.schemas import (
    RuntimeAssignmentRequest,
    RuntimeBindRequest,
    RuntimeRebindRequest,
    RuntimeStepRequest,
)
from project_workflow.supervisor import format_result

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
    credential = _authorized_service_credential(authorization)
    if credential is None or credential.kind != "assignment":
        return None
    return credential.role_key


def _authorized_service_credential(
    authorization: str | None,
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
    return matches[0] if matches else None


def runtime_capabilities(
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Return authenticated runtime contract and immutable build provenance."""
    try:
        credential = _authorized_service_credential(authorization)
    except RuntimeError:
        return _error("Runtime capability configuration unavailable", 503)
    if credential is None:
        return _error("Недействительный runtime token", 401)
    if credential.kind == "catalog":
        return _error("Токен каталога не разрешает runtime capabilities", 403)

    try:
        provenance = load_build_provenance()
        compatibility = runtime_compatibility_descriptor(provenance=provenance)
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
                catalog_ready = validate_managed_catalog_state(uow)
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

    capabilities = ["assign", "bind", "rebind"] if credential.kind == "assignment" else ["step", "history"]
    response: dict[str, Any] = {
        "ok": True,
        "role_key": credential.role_key,
        "credential_kind": credential.kind,
        "capabilities": capabilities,
        "readiness": {"service": "ready", "schema": "ready", "catalog": "ready"},
        "source_provenance": provenance.to_dict() if provenance is not None else {},
        "runtimeCompatibility": compatibility,
    }
    from . import pm_api

    if credential.role_key == "project_manager" and pm_api.configured():
        response["pm_continuation"] = {
            "contract_version": 1,
            "base_path": "/internal/runtime/v1/pm",
            "commands": ["bind", "resume", "rebind", "readback"]
            if credential.kind == "assignment" else ["checkpoint", "readback"],
            "terminal_proof": "configured-runtime-readback",
            "dispatch_owner": "fleet",
            "execution_token_header": "X-Workflow-Execution-Token",
        }
    return response


def _namespace_id(uow: SAUnitOfWork, role: str) -> int:
    value = _resolve_namespace_id(uow, f"workflow-{role}")
    if value is None:
        raise ValueError("Namespace роли не найден")
    return value


def _assert_task_key_in_namespace(uow: SAUnitOfWork, namespace_id: int, task_key: str) -> None:
    """Role token may only touch tasks whose key prefix belongs to its namespace.

    Namespaces without configured prefixes impose no prefix policy (master
    treats key_prefixes as metadata, not routing rules); namespaces with
    prefixes restrict the bridge to their own keys.
    """
    project = uow.projects.get_by_id(namespace_id)
    if project is None:
        raise ValueError("Namespace роли не найден")
    prefixes = [prefix for prefix in (project.to_dict().get("key_prefixes") or []) if prefix]
    if not prefixes:
        return
    if not any(task_key == prefix or task_key.startswith(f"{prefix}-") for prefix in prefixes):
        raise ValueError(f"Ключ задачи {task_key!r} не соответствует префиксам неймспейса роли")


def _history_rows(uow: SAUnitOfWork, task_key: str, namespace_id: int, limit: int | None) -> list[dict[str, Any]]:
    task = uow.tasks.get_by_key(task_key, project_id=namespace_id)
    task_id = task.id if task else None
    rows: list[dict[str, Any]] = []
    for entry in uow.step_history.list(
        task_id=task_id,
        task_key=task_key,
        project_id=namespace_id,
        limit=limit,
    ):
        item = entry.to_dict()
        supervisor_response = item.get("supervisor_response")
        if not isinstance(supervisor_response, dict):
            supervisor_response = {}
        phase = uow.phases.get_by_id(int(item.get("phase_id") or 0))
        next_id = item.get("next_phase_id")
        rollback_id = item.get("rollback_phase_id")
        next_phase = uow.phases.get_by_id(int(next_id)) if next_id is not None else None
        rollback = uow.phases.get_by_id(int(rollback_id)) if rollback_id is not None else None
        if phase is None:
            raise ValueError("История step ссылается на неизвестную фазу")
        rows.append(
            {
                "phase_code": phase.code,
                "verdict": item.get("verdict"),
                "worker_report": item.get("worker_report"),
                "supervisor_message": supervisor_response.get("message"),
                "retryable": supervisor_response.get("retryable") is True,
                "next_phase_code": next_phase.code if next_phase else None,
                "rollback_phase_code": rollback.code if rollback else None,
                "created_at": item.get("created_at"),
                "workflow_id": item.get("workflow_id"),
                "mode_id": item.get("mode_id"),
                "mode_key": item.get("mode_key"),
                "cycle_number": item.get("cycle_number"),
            }
        )
        if "execution_ref" in supervisor_response:
            rows[-1].update({key: supervisor_response.get(key) for key in (
                "execution_ref", "session_run_id", "execution_version", "execution_fence",
                "binding_ref", "hermes_run_ref", "assignment_ref", "assignment_revision",
            )})
    return rows


def _step_response(result: dict[str, Any]) -> dict[str, Any]:
    exit_code = 1 if result.get("verdict") == "BLOCKED" else 0
    return {
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "output": format_result(result),
        "result": result,
    }


def _runtime_step_replay(
    uow: SAUnitOfWork,
    *,
    payload: RuntimeStepRequest,
    request_sha256: str,
    role_key: str,
    namespace_id: int,
    task_key: str,
) -> dict[str, Any] | None:
    """Return one exact committed response or reject an operation-key collision."""
    entry = uow.step_history.get_by_step_operation_key(payload.step_operation_key)
    if entry is None:
        return None
    history = entry.to_dict()
    task = uow.tasks.get_by_id(entry.task_id)
    assignment_operation_key = history.get("assignment_operation_key")
    assignment = (
        uow.tasks.get_assignment_by_operation_key(assignment_operation_key)
        if isinstance(assignment_operation_key, str)
        else None
    )
    assignment_data = assignment.to_dict() if assignment is not None else {}
    if role_key == "project_manager" and payload.session_run_id is not None and assignment is not None:
        pm_run = uow.session.get(PMRun, payload.session_run_id)
        pm_execution = uow.session.get(PMExecution, pm_run.execution_ref) if pm_run is not None else None
        if (
            pm_run is None or pm_execution is None or pm_execution.task_id != history.get("task_id")
            or pm_execution.assignment_id != assignment.id
        ):
            raise ConflictError("PM history run does not belong to this execution/assignment")
        assignment_data = {**assignment_data, "binding_ref": pm_run.binding_ref, "hermes_run_ref": pm_run.run_ref}
    expected_history = {
        "step_operation_key": payload.step_operation_key,
        "request_sha256": request_sha256,
        "assignment_revision": payload.assignment_revision,
        "assignment_ref": payload.assignment_ref,
        "binding_ref": payload.binding_ref,
        "hermes_run_ref": payload.hermes_run_ref,
        "mode_key": payload.mode_key,
        "cycle_number": payload.cycle_number,
        "attempt_number": payload.attempt_number,
        "role_key": role_key,
    }
    mismatched = [name for name, value in expected_history.items() if history.get(name) != value]
    invalid_task = (
        task is None
        or task.project_id != namespace_id
        or task.task_key != task_key
        or task.assignment_revision != history.get("assignment_revision")
        or task.assignment_operation_key != assignment_operation_key
        or task.mode_id != history.get("mode_id")
        or task.mode_key != history.get("mode_key")
        or task.cycle_number != history.get("cycle_number")
    )
    immutable_fields = (
        "task_id",
        "workflow_id",
        "assignment_revision",
        "assignment_ref",
        "binding_ref",
        "hermes_run_ref",
        "mode_id",
        "mode_key",
        "cycle_number",
        "attempt_number",
        "role_key",
    )
    invalid_assignment = (
        assignment is None
        or assignment_data.get("project_id") != namespace_id
        or assignment_data.get("operation_key") != assignment_operation_key
        or any(assignment_data.get(name) != history.get(name) for name in immutable_fields)
    )
    if mismatched or invalid_task or invalid_assignment:
        raise ConflictError("step_operation_key уже использован для другого runtime step")
    if task is not None:
        assert_base_step(
            uow, task.to_dict(), assignment_data,
            config_ref=payload.base_config_ref, config_sha256=payload.base_config_sha256,
        )
    response = history.get("supervisor_response")
    if not isinstance(response, dict):
        raise ConflictError("Сохранённый runtime step не содержит корректный ответ")
    if assignment_data.get("payload", {}).get("base_admission") is not None and (
        response.get("status") == "done" or response.get("complete") is True
        or "base_terminal_receipt" in response
        or history.get("verdict") == "pass" and history.get("next_phase_id") is None
        and history.get("rollback_phase_id") is None
    ):
        from project_workflow.application.base_terminal import read_terminal_receipt

        read_terminal_receipt(uow, payload.step_operation_key)
    result = _step_response(dict(response))
    receipt = admission_receipt(assignment_data, task.to_dict() if task is not None else {})
    if receipt is not None:
        result["base_admission_receipt"] = receipt
    return result


def _read_committed_runtime_step(
    *,
    payload: RuntimeStepRequest,
    request_sha256: str,
    role_key: str,
) -> dict[str, Any]:
    """Read a committed operation response in a fresh transaction."""
    with SAUnitOfWork() as uow:
        namespace_id = _namespace_id(uow, role_key)
        task_key = _require_valid_key(payload.task, uow, project_id=namespace_id)
        _assert_task_key_in_namespace(uow, namespace_id, task_key)
        replay = _runtime_step_replay(
            uow,
            payload=payload,
            request_sha256=request_sha256,
            role_key=role_key,
            namespace_id=namespace_id,
            task_key=task_key,
        )
        if replay is None:
            raise ConflictError("Runtime step конфликтует с параллельно сохранённым состоянием")
        return replay


def execute_namespace_step(
    uow: SAUnitOfWork,
    *,
    namespace_id: int,
    task: str,
    report: str | None,
    create_if_missing: bool,
    runtime_fence: RuntimeStepFence | None = None,
) -> dict[str, Any]:
    """Execute one Supervisor step inside an already-authorized namespace."""
    task_key = _require_valid_key(task, uow, project_id=namespace_id)
    _assert_task_key_in_namespace(uow, namespace_id, task_key)
    engine = supervisor.SupervisorEngine(
        task_key,
        uow=uow,
        create_if_missing=create_if_missing,
        project_id=namespace_id,
        runtime_fence=runtime_fence,
    )
    if report is None:
        if engine._get_current_phase_obj() is None:
            result = engine._blocked_result()
            return {
                "ok": False,
                "exit_code": 1,
                "output": format_result(result),
                "result": result,
            }
        contract = engine.get_phase_contract()
        if contract is not None:
            contract["allowed_tools"] = phase_allowed_tools(
                runtime_fence.role_key if runtime_fence is not None else "",
                engine.current_phase_code or "",
            )
        result = {
            "ok": True,
            "task_key": task_key,
            "phase_code": engine.current_phase_code,
            "status": engine.task.get("status") if engine.task else None,
            "instructions": engine.format_current_phase_instructions(),
            "phase_contract": contract,
            "workflow_id": engine.task.get("workflow_id") if engine.task else None,
            "mode_id": engine.task.get("mode_id") if engine.task else None,
            "mode_key": engine.task.get("mode_key") if engine.task else None,
            "cycle_number": engine.task.get("cycle_number") if engine.task else None,
        }
        if runtime_fence is not None and runtime_fence.base_admission_sha256 is not None:
            result["complete"] = False
        return {"ok": True, "exit_code": 0, "output": result["instructions"], "result": result}
    result = engine.evaluate(report)
    return _step_response(result)


def _assignment_response(task: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "task_key",
        "workflow_id",
        "workflow_key",
        "mode_id",
        "mode_key",
        "cycle_number",
        "attempt_number",
        "assignment_operation_key",
        "assignment_revision",
        "role_key",
        "execution_scope",
        "stage_key",
        "business_task_ref",
        "root_task_ref",
        "work_item_ref",
        "work_item_revision",
        "queue_item_ref",
        "task_workspace_ref",
        "workspace_revision",
        "tech_execution_workspace_ref",
        "tech_execution_attempt_ref",
        "decomposition_revision_ref",
        "stage_revision",
        "assignment_ref",
        "binding_ref",
        "hermes_run_ref",
        "bind_operation_key",
        "concrete_agent_ref",
        "workspace_generation",
        "lease_generation",
        "exact_input_refs",
        "binding_state",
        "status",
        "current_phase_id",
        "current_phase_code",
        "current_phase_name",
    )
    return {
        "ok": True,
        "exit_code": 0,
        "result": {**{key: task.get(key) for key in keys},
                   **({"assignment_shape": task["assignment_shape"]} if task.get("assignment_shape") else {})},
        **({"base_admission_receipt": task["base_admission_receipt"]} if "base_admission_receipt" in task else {}),
    }


def runtime_assign(
    payload: RuntimeAssignmentRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Accept one authorized Business assignment and persist its technical cursor."""
    try:
        role = _authorized_assignment_role(authorization)
    except RuntimeError as exc:
        return _error(str(exc), 503)
    if role is None:
        try:
            # A valid execution/catalog credential is deliberately distinguishable
            # from an unknown credential: only the adapter credential may assign.
            if _authorized_service_credential(authorization) is not None:
                return _error("Runtime token не разрешает назначение задач", 403)
        except RuntimeError as exc:
            return _error(str(exc), 503)
        return _error("Недействительный runtime token", 401)
    if payload.role_key != role:
        return _error("role_key не совпадает с ролью assignment token", 403)
    try:
        if (
            payload.runtime_compatibility is not None
            and payload.runtime_compatibility != runtime_compatibility_descriptor()
        ):
            return _error("Runtime compatibility mismatch", 409)
        with SAUnitOfWork() as uow:
            namespace_id = _namespace_id(uow, role)
            task_key = _require_valid_key(payload.task, uow, project_id=namespace_id)
            _assert_task_key_in_namespace(uow, namespace_id, task_key)
            task = TaskService(uow).assign_runtime_task(
                project_id=namespace_id,
                task_key=task_key,
                role_key=payload.role_key,
                workflow_key=payload.workflow_key,
                mode_key=payload.mode_key,
                execution_scope=payload.execution_scope,
                stage_key=payload.stage_key,
                cycle_number=payload.cycle_number,
                attempt_number=payload.attempt_number,
                operation_key=payload.operation_key,
                business_task_ref=payload.business_task_ref,
                root_task_ref=payload.root_task_ref,
                work_item_ref=payload.work_item_ref,
                work_item_revision=payload.work_item_revision,
                queue_item_ref=payload.queue_item_ref,
                task_workspace_ref=payload.task_workspace_ref,
                workspace_revision=payload.workspace_revision,
                tech_execution_workspace_ref=payload.tech_execution_workspace_ref,
                tech_execution_attempt_ref=payload.tech_execution_attempt_ref,
                decomposition_revision_ref=payload.decomposition_revision_ref,
                stage_revision=payload.stage_revision,
                assignment_ref=payload.assignment_ref,
                workspace_generation=payload.workspace_generation,
                lease_generation=payload.lease_generation,
                exact_input_refs=[item.model_dump(exclude_unset=True) for item in payload.exact_input_refs],
                expected_revision=payload.expected_revision,
                expected_status=payload.expected_status,
                expected_mode_key=payload.expected_mode_key,
                expected_cycle_number=payload.expected_cycle_number,
                runtime_compatibility=payload.runtime_compatibility,
                base_admission=payload.base_admission.model_dump(mode="json") if payload.base_admission else None,
                assignment_shape=payload.assignment_shape,
            )
            return _assignment_response(task)
    except (ConflictError, RuntimeError, ValueError) as exc:
        return _error(str(exc), 409)


def runtime_rebind(
    payload: RuntimeRebindRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Role assignment credentials alone may prepare a fenced continuation."""
    try:
        role = _authorized_assignment_role(authorization)
        if role is None:
            return _error("Недействительный assignment token", 401)
        with SAUnitOfWork() as uow:
            namespace_id = _namespace_id(uow, role)
            task_key = _require_valid_key(payload.task, uow, project_id=namespace_id)
            _assert_task_key_in_namespace(uow, namespace_id, task_key)
            values = payload.model_dump()
            values["task"] = task_key
            task = TaskService(uow).rebind_runtime_assignment(
                project_id=namespace_id,
                role_key=role,
                request=values,
            )
            return _assignment_response(task)
    except (ConflictError, ValueError) as exc:
        return _error(str(exc), 409)
    except RuntimeError as exc:
        return _error(str(exc), 503)


def runtime_bind(
    payload: RuntimeBindRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Attach the adapter's real Hermes binding to one accepted assignment."""
    try:
        role = _authorized_assignment_role(authorization)
    except RuntimeError as exc:
        return _error(str(exc), 503)
    if role is None:
        try:
            if _authorized_service_credential(authorization) is not None:
                return _error("Runtime token не разрешает связывание задач", 403)
        except RuntimeError as exc:
            return _error(str(exc), 503)
        return _error("Недействительный runtime token", 401)
    try:
        with SAUnitOfWork() as uow:
            namespace_id = _namespace_id(uow, role)
            task_key = _require_valid_key(payload.task, uow, project_id=namespace_id)
            _assert_task_key_in_namespace(uow, namespace_id, task_key)
            task = TaskService(uow).bind_runtime_assignment(
                project_id=namespace_id,
                task_key=task_key,
                role_key=role,
                bind_operation_key=payload.bind_operation_key,
                assignment_operation_key=payload.assignment_operation_key,
                assignment_revision=payload.assignment_revision,
                assignment_ref=payload.assignment_ref,
                binding_ref=payload.binding_ref,
                hermes_run_ref=payload.hermes_run_ref,
                mode_key=payload.mode_key,
                cycle_number=payload.cycle_number,
                attempt_number=payload.attempt_number,
                expected_binding_state=payload.expected_binding_state,
                concrete_agent_ref=payload.concrete_agent_ref,
            )
            return _assignment_response(task)
    except (ConflictError, RuntimeError, ValueError) as exc:
        return _error(str(exc), 409)


def runtime_step(
    payload: RuntimeStepRequest,
    authorization: str | None = Header(default=None),
    x_workflow_execution_token: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Execute one role-scoped step in the trusted workflow service."""
    try:
        credential = _authorized_service_credential(authorization)
    except RuntimeError as exc:
        return _error(str(exc), 503)
    if credential is None:
        return _error("Недействительный runtime token", 401)
    if credential.kind != "runtime":
        return _error("Токен не разрешает выполнение шагов", 403)
    role = credential.role_key
    request_digest = payload_sha256(payload.model_dump(mode="json"))
    try:
        response: dict[str, Any] | None = None
        with SAUnitOfWork() as uow:
            namespace_id = _namespace_id(uow, role)
            task_key = _require_valid_key(payload.task, uow, project_id=namespace_id)
            _assert_task_key_in_namespace(uow, namespace_id, task_key)
            from project_workflow.application.pm_execution import PMExecutionService

            from . import pm_api

            task_row = uow.tasks.get_by_key(task_key, project_id=namespace_id)
            if role == "project_manager" and task_row is not None:
                execution = uow.session.scalar(select(PMExecution).where(PMExecution.task_id == task_row.id))
                if execution is not None:
                    snapshot = PMExecutionService(uow).snapshot(execution)
                    if not pm_api.scope_matches(
                        snapshot["identity"], snapshot["hermes_run_ref"], snapshot["binding_ref"],
                        snapshot["fence"], snapshot["session_run_id"], x_workflow_execution_token,
                    ):
                        return _error("Current PM execution/run credential required", 403)
                    if payload.session_run_id != snapshot["session_run_id"]:
                        return _error("Current Fleet session_run_id required", 409)
                else:
                    PMExecutionService(uow).supervisor_binding(int(task_row.id or 0))
            replay = _runtime_step_replay(
                uow,
                payload=payload,
                request_sha256=request_digest,
                role_key=role,
                namespace_id=namespace_id,
                task_key=task_key,
            )
            if replay is not None:
                return replay
            fence = TaskService(uow).validate_runtime_step(
                project_id=namespace_id,
                task_key=task_key,
                role_key=role,
                step_operation_key=payload.step_operation_key,
                request_sha256=request_digest,
                assignment_revision=payload.assignment_revision,
                assignment_ref=payload.assignment_ref,
                binding_ref=payload.binding_ref,
                hermes_run_ref=payload.hermes_run_ref,
                mode_key=payload.mode_key,
                cycle_number=payload.cycle_number,
                attempt_number=payload.attempt_number,
                expected_phase_code=payload.expected_phase_code,
                expected_status=payload.expected_status,
                base_config_ref=payload.base_config_ref,
                base_config_sha256=payload.base_config_sha256,
            )
            try:
                response = execute_namespace_step(
                    uow,
                    namespace_id=namespace_id,
                    task=task_key,
                    report=payload.report,
                    create_if_missing=False,
                    runtime_fence=fence,
                )
                if fence.base_admission_sha256 is not None:
                    assignment = uow.tasks.get_assignment_by_operation_key(fence.assignment_operation_key)
                    current = uow.tasks.get_by_key(task_key, project_id=namespace_id)
                    if assignment is not None and current is not None:
                        response["base_admission_receipt"] = admission_receipt(
                            assignment.to_dict(), current.to_dict(),
                        )
            except (ConflictError, RuntimeError, ValueError):
                uow.rollback()
                replay = _runtime_step_replay(
                    uow,
                    payload=payload,
                    request_sha256=request_digest,
                    role_key=role,
                    namespace_id=namespace_id,
                    task_key=task_key,
                )
                if replay is not None:
                    return replay
                raise
        if payload.report is None:
            if response is None:
                raise RuntimeError("Runtime step не вернул ответ")
            return response
        return _read_committed_runtime_step(
            payload=payload,
            request_sha256=request_digest,
            role_key=role,
        )
    except IntegrityError:
        try:
            return _read_committed_runtime_step(
                payload=payload,
                request_sha256=request_digest,
                role_key=role,
            )
        except (ConflictError, RuntimeError, ValueError) as exc:
            return _error(str(exc), 409)
    except (ConflictError, RuntimeError, ValueError) as exc:
        return _error(str(exc), 409)


def runtime_history(
    task: str = Query(...),
    n: int = Query(default=200, ge=1, le=200),
    authorization: str | None = Header(default=None),
    x_workflow_execution_token: str | None = Header(default=None),
    session_run_id: str | None = Query(default=None),
) -> dict[str, Any] | JSONResponse:
    """Return history only from the namespace bound to the supplied role token."""
    try:
        credential = _authorized_service_credential(authorization)
    except RuntimeError as exc:
        return _error(str(exc), 503)
    if credential is None:
        return _error("Недействительный runtime token", 401)
    if credential.kind != "runtime":
        return _error("Токен не разрешает чтение истории", 403)
    role = credential.role_key
    try:
        with SAUnitOfWork() as uow:
            namespace_id = _namespace_id(uow, role)
            task_key = _require_valid_key(task, uow, project_id=namespace_id)
            _assert_task_key_in_namespace(uow, namespace_id, task_key)
            if role == "project_manager":
                from project_workflow.application.pm_execution import PMExecutionService

                from . import pm_api

                task_row = uow.tasks.get_by_key(task_key, project_id=namespace_id)
                execution = uow.session.scalar(select(PMExecution).where(
                    PMExecution.task_id == task_row.id,
                )) if task_row is not None else None
                if execution is not None:
                    snapshot = PMExecutionService(uow).snapshot(execution)
                    if not pm_api.scope_matches(
                        snapshot["identity"], snapshot["hermes_run_ref"], snapshot["binding_ref"],
                        snapshot["fence"], snapshot["session_run_id"], x_workflow_execution_token,
                    ):
                        return _error("Current PM execution/run credential required", 403)
                    if session_run_id != snapshot["session_run_id"]:
                        return _error("Current Fleet session_run_id required", 409)
                elif task_row is not None:
                    PMExecutionService(uow).supervisor_binding(int(task_row.id or 0))
            rows = _history_rows(uow, task_key, namespace_id, n)
            return {
                "ok": True,
                "exit_code": 0,
                "output": json.dumps(rows, ensure_ascii=False),
                "result": {"task_key": task_key, "count": len(rows), "records": rows},
            }
    except (ConflictError, RuntimeError, ValueError) as exc:
        return _error(str(exc), 409)


async def runtime_catalog(
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
    try:
        if not validate_managed_catalog_state(_app_state.get_uow()):
            return _error("Managed каталог временно недоступен", 503)
    except (FileNotFoundError, ValueError):
        return _error("Managed каталог временно недоступен", 503)
    from . import api

    namespaces = await api.api_namespaces()
    workflows = await api.api_workflows()
    namespace_items = namespaces.get("namespaces") if isinstance(namespaces, dict) else None
    workflow_items = workflows.get("workflows") if isinstance(workflows, dict) else None
    if not isinstance(namespace_items, list) or not isinstance(workflow_items, list):
        return _error("Каталог временно недоступен", 503)
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
    return {
        "ok": True,
        "namespaces": managed_namespaces,
        "workflows": managed_workflows,
    }
