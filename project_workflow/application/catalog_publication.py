"""Publish text using existing versioned modes, never another execution engine."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from project_workflow.domain.catalog_publication import CatalogDraft, CatalogPublish
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.runtime_assignment import canonical_json, payload_sha256
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.managed_catalog import (
    ManagedMode,
    _ArchivedWorkflowDefinition,
    _assert_existing_workflow,
    _persist_mode,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork


def _normalize(modes: list[dict]) -> list[dict]:
    result = []
    for raw in modes:
        mode = ManagedMode.model_validate(raw).model_dump(mode="json")
        for phase in mode["phases"]:
            for field in ("checks", "evidence"):
                phase[field] = [item if isinstance(item, str) else item["description"] for item in phase[field]]
                if any(not item.strip() for item in phase[field]):
                    raise ValueError("Published checks/evidence must not be blank")
        result.append(mode)
    return result


def _structure(modes: list[dict]) -> list[dict]:
    result = deepcopy(modes)
    for mode in result:
        mode["name"] = ""
        for phase in mode["phases"]:
            phase["name"] = phase["description"] = ""
            for instruction in phase["instructions"]:
                instruction["description"] = ""
            for field in ("checks", "evidence"):
                phase[field] = [""] * len(phase[field])
    return result


def _definition(workflow_key: str | None) -> dict:
    from project_workflow.infrastructure.db.single_task_catalog import load_profile

    catalog, _ = load_profile()
    definition = next((item for item in catalog["workflows"] if item["key"] == workflow_key), None)
    if definition is None:
        raise ConflictError("Current configured single-task workflow required")
    return definition


def _validate_rows(uow: SAUnitOfWork, workflow: Any, version: int, modes: list[dict]) -> None:
    definition = _definition(workflow.key)
    baseline = _normalize(definition["modes"])
    if _structure(modes) != _structure(baseline):
        raise ConflictError("Only text may change; role, scopes, skills and phase structure are frozen")
    expected = _ArchivedWorkflowDefinition(
        key=workflow.key, name=definition["name"], description=definition["description"],
        role_key=definition["role_key"], modes=[ManagedMode.model_validate(mode) for mode in modes],
    )
    _assert_existing_workflow(uow, workflow, expected, catalog_version=version)
    actual = uow.workflows.list_modes(workflow.id, catalog_version=version)
    if [mode.name for mode in actual] != [mode["name"] for mode in modes]:
        raise ConflictError("Published mode names changed")


def read_revision(uow: SAUnitOfWork, workflow: Any, version: int, *, selected: bool = False) -> dict:
    if selected:
        latest = uow.session.scalar(select(func.max(m.WorkflowCatalogPublication.catalog_version)).where(
            m.WorkflowCatalogPublication.workflow_id == workflow.id))
        if latest is not None and latest != workflow.active_catalog_version:
            raise ConflictError("Active publication pointer changed outside publication")
    if version == 1:
        modes = _normalize(_definition(workflow.key)["modes"])
    else:
        receipt = uow.session.get(m.WorkflowCatalogPublication, (workflow.id, version))
        if receipt is None:
            raise ConflictError("Unpublished instruction revision")
        modes = _normalize(json.loads(receipt.content))
        if payload_sha256(modes) != receipt.content_sha256:
            raise ConflictError("Publication receipt hash mismatch")
    _validate_rows(uow, workflow, version, modes)
    result = {"workflow_id": workflow.id, "catalog_version": version,
              "content_sha256": payload_sha256(modes), "modes": modes}
    if version > 1:
        assert receipt is not None
        published_at = receipt.published_at
        if published_at is not None:
            # SQLite drops tzinfo; persisted values are always server UTC.
            published_at = published_at.replace(tzinfo=timezone.utc) if published_at.tzinfo is None else published_at
        result.update(published_by_subject=receipt.published_by_subject,
                      published_at=published_at.astimezone(timezone.utc).isoformat() if published_at else None)
    return result


def _locked(uow: SAUnitOfWork, workflow_id: int) -> Any:
    uow.lock_catalog_state()
    workflow = uow.workflows.lock(workflow_id)
    if workflow is None:
        raise NotFoundError("Workflow not found")
    _definition(workflow.key)
    # Preserve sealed v1 provenance, all identities and profession membership guards.
    from project_workflow.infrastructure.db.single_task_catalog import observe_installation

    observe_installation(uow)
    return workflow


def read_active(uow: SAUnitOfWork, workflow_id: int) -> dict:
    workflow = _locked(uow, workflow_id)
    return read_revision(uow, workflow, workflow.active_catalog_version, selected=True)


def read_operation(uow: SAUnitOfWork, workflow_id: int, operation_key: str) -> dict:
    workflow = _locked(uow, workflow_id)
    receipt = uow.session.scalar(select(m.WorkflowCatalogPublication).where(
        m.WorkflowCatalogPublication.workflow_id == workflow_id,
        m.WorkflowCatalogPublication.operation_key == operation_key))
    if receipt is None:
        raise NotFoundError("Publication operation not found")
    return {**read_revision(uow, workflow, receipt.catalog_version), "published": True}


def _cas(uow: SAUnitOfWork, workflow: Any, version: int, digest: str) -> None:
    current = read_revision(uow, workflow, workflow.active_catalog_version, selected=True)
    if current["catalog_version"] != version or current["content_sha256"] != digest:
        raise ConflictError("Active instruction revision changed; reload before saving/publishing")


def _draft_result(workflow: Any, version: int, modes: list[dict]) -> dict:
    return {"workflow_id": workflow.id, "catalog_version": version, "content_sha256": payload_sha256(modes),
            "modes": modes, "published": False, "active_catalog_version": workflow.active_catalog_version}


def read_draft(uow: SAUnitOfWork, workflow_id: int, version: int) -> dict:
    workflow = _locked(uow, workflow_id)
    modes = _draft_modes(uow, workflow_id, version)
    if not modes:
        raise NotFoundError("Saved instruction draft not found")
    _validate_rows(uow, workflow, version, modes)
    if version == 1 or uow.session.get(m.WorkflowCatalogPublication, (workflow_id, version)) is not None:
        return {**read_revision(uow, workflow, version), "published": True,
                "active_catalog_version": workflow.active_catalog_version}
    return _draft_result(workflow, version, modes)


def read_pending_draft(uow: SAUnitOfWork, workflow_id: int) -> dict | None:
    workflow = _locked(uow, workflow_id)
    version = uow.session.scalar(select(func.max(m.WorkflowMode.catalog_version)).where(
        m.WorkflowMode.workflow_id == workflow_id, m.WorkflowMode.catalog_version > workflow.active_catalog_version))
    return read_draft(uow, workflow_id, version) if version is not None else None


def save_draft(uow: SAUnitOfWork, workflow_id: int, command: CatalogDraft) -> dict:
    workflow = _locked(uow, workflow_id)
    _cas(uow, workflow, command.expected_version, command.expected_sha256)
    modes = _normalize(command.modes)
    if _structure(modes) != _structure(_normalize(_definition(workflow.key)["modes"])):
        raise ConflictError("Only text may change; role, scopes, skills and phase structure are frozen")
    # Reconcile an unknown save result under the same catalog lock. Drafts use
    # existing version rows, not a second journal or a client-supplied identity.
    pending = uow.session.scalars(select(m.WorkflowMode.catalog_version).where(
        m.WorkflowMode.workflow_id == workflow_id, m.WorkflowMode.catalog_version > workflow.active_catalog_version,
    ).distinct().order_by(m.WorkflowMode.catalog_version.desc())).all()
    for version in pending:
        if _draft_modes(uow, workflow_id, version) == modes:
            _validate_rows(uow, workflow, version, modes)
            return _draft_result(workflow, version, modes)
    latest = uow.session.scalar(select(func.max(m.WorkflowMode.catalog_version)).where(
        m.WorkflowMode.workflow_id == workflow_id))
    assert latest is not None
    version = latest + 1
    for mode in modes:
        _persist_mode(uow, workflow_id=workflow_id, role_key=_definition(workflow.key)["role_key"],
                      mode=ManagedMode.model_validate(mode), catalog_version=version)
    _validate_rows(uow, workflow, version, modes)
    uow.commit()
    return _draft_result(workflow, version, modes)


def _draft_modes(uow: SAUnitOfWork, workflow_id: int, version: int) -> list[dict]:
    modes = []
    for mode in uow.workflows.list_modes(workflow_id, catalog_version=version):
        phases = []
        for phase in uow.phases.list(workflow_id, mode_id=mode.id):
            assert phase.id is not None
            phases.append({"code": phase.code, "name": phase.name, "description": phase.description or "",
                "phase_order": phase.phase_order, "execution_type": phase.execution_type,
                "parallel_with_phase_code": "invalid" if phase.parallel_with_phase_id else None,
                "rollback_target_phase_code": "invalid" if phase.rollback_target_phase_id else None,
                "instructions": [{k: item[k] for k in ("description", "execution_type", "skills")}
                                 for item in uow.phase_instructions.list(phase.id)],
                "checks": [item["description"] for item in uow.phase_checks.list(phase.id)],
                "evidence": [item["description"] for item in uow.phase_evidence_requirements.list(phase.id)]})
        modes.append({"key": mode.key, "name": mode.name, "mode_order": mode.mode_order,
                      "execution_scopes": mode.execution_scopes, "phases": phases})
    return _normalize(modes)


def publish(uow: SAUnitOfWork, workflow_id: int, draft_version: int, command: CatalogPublish, *,
            publisher_subject: str) -> dict:
    if not isinstance(publisher_subject, str) or not publisher_subject.strip() or len(publisher_subject) > 255:
        raise ValueError("Verified publication subject required")
    workflow = _locked(uow, workflow_id)
    read_revision(uow, workflow, workflow.active_catalog_version, selected=True)
    request_hash = payload_sha256({"workflow_id": workflow_id, "draft_version": draft_version,
                                  **command.model_dump(mode="json")})
    replay = uow.session.scalar(select(m.WorkflowCatalogPublication).where(
        m.WorkflowCatalogPublication.operation_key == command.operation_key))
    if replay is not None:
        if replay.request_sha256 != request_hash:
            raise ConflictError("Publication operation key payload conflict")
        result = read_revision(uow, workflow, replay.catalog_version)
        return {**result, "published": True}
    _cas(uow, workflow, command.expected_version, command.expected_sha256)
    if draft_version <= workflow.active_catalog_version:
        raise ConflictError("Publication must append a newer revision")
    modes = _draft_modes(uow, workflow_id, draft_version)
    _validate_rows(uow, workflow, draft_version, modes)
    digest = payload_sha256(modes)
    if digest != command.draft_sha256:
        raise ConflictError("Draft changed after review")
    uow.session.add(m.WorkflowCatalogPublication(
        workflow_id=workflow_id, catalog_version=draft_version, parent_version=workflow.active_catalog_version,
        operation_key=command.operation_key, request_sha256=request_hash, content_sha256=digest,
        content=canonical_json(modes), published_by_subject=publisher_subject, published_at=datetime.now(timezone.utc)))
    uow.session.flush()
    uow.workflows.update(workflow_id, {"active_catalog_version": draft_version})
    result = read_revision(uow, uow.workflows.get_by_id(workflow_id), draft_version)
    uow.commit()
    return {**result, "published": True}
