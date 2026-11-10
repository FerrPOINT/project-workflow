"""Publish instruction revisions without changing existing execution snapshots."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Row

from project_workflow.domain.catalog_publication import CatalogDraft, CatalogPublish
from project_workflow.domain.configured_cli import PROTOCOL
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.runtime_assignment import canonical_json, payload_sha256
from project_workflow.domain.single_task_profile import CATALOG_MANIFESTS
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


BASELINE_OPERATION = "@catalog-baseline:"


def _definition(workflow_key: str | None, manifest: str | None = None) -> dict:
    from project_workflow.infrastructure.db.single_task_catalog import load_profile

    catalog, _ = load_profile(manifest) if manifest is not None else load_profile()
    definition = next((item for item in catalog["workflows"] if item["key"] == workflow_key), None)
    if definition is None:
        raise ConflictError("Current configured single-task workflow required")
    return definition


def _initial_definition(workflow_key: str | None) -> dict:
    definition = _definition(workflow_key)
    visited = set()
    while previous := definition.get("previous_baseline_manifest_sha256"):
        if previous in visited:
            raise ConflictError("Cyclic sealed baseline lineage")
        visited.add(previous)
        definition = _definition(workflow_key, previous)
    return definition


def _baseline_request(workflow_id: int, version: int, parent: int, manifest: str) -> dict:
    return {"operation": "catalog-baseline", "workflow_id": workflow_id, "catalog_version": version,
            "parent_version": parent, "instruction_manifest_sha256": manifest}


def _baseline_receipt(
    uow: SAUnitOfWork, workflow: Any, version: int | None = None,
) -> Row | None:
    prefix = f"{BASELINE_OPERATION}{workflow.id}:"
    row = m.WorkflowCatalogPublication
    query = select(row.workflow_id, row.catalog_version, row.parent_version, row.operation_key,
                   row.request_sha256, row.content_sha256, row.content).where(
        m.WorkflowCatalogPublication.workflow_id == workflow.id,
        m.WorkflowCatalogPublication.operation_key.startswith(prefix),
    )
    if version is not None:
        query = query.where(m.WorkflowCatalogPublication.catalog_version <= version)
    return uow.session.execute(query.order_by(row.catalog_version.desc()).limit(1)).first()


def _baseline_manifest(receipt: Row) -> str:
    return receipt.operation_key.removeprefix(f"{BASELINE_OPERATION}{receipt.workflow_id}:")


def _validate_baseline_receipt(receipt: Row, definition: dict) -> None:
    modes = _normalize(definition["modes"])
    if (receipt.request_sha256 != payload_sha256(_baseline_request(
                receipt.workflow_id, receipt.catalog_version, receipt.parent_version, _baseline_manifest(receipt)))
            or receipt.content_sha256 != payload_sha256(modes)
            or receipt.content != canonical_json(modes)):
        raise ConflictError("Sealed baseline receipt changed")


def sealed_baseline(uow: SAUnitOfWork, workflow: Any, version: int | None = None) -> tuple[dict, int]:
    """Resolve immutable source provenance from the existing publication ledger."""
    receipt = _baseline_receipt(uow, workflow, version)
    if receipt is None:
        return _initial_definition(workflow.key), 1
    definition = _definition(workflow.key, _baseline_manifest(receipt))
    _validate_baseline_receipt(receipt, definition)
    return definition, receipt.catalog_version


def publish_baseline(uow: SAUnitOfWork, workflow: Any, manifest: str, *, existing_version: int | None = None) -> int:
    """Bootstrap/migrations append a source revision; the caller owns locks/transaction."""
    operation = f"{BASELINE_OPERATION}{workflow.id}:{manifest}"
    latest_publication = uow.session.scalar(select(func.max(m.WorkflowCatalogPublication.catalog_version)).where(
        m.WorkflowCatalogPublication.workflow_id == workflow.id))
    if latest_publication is not None and latest_publication != workflow.active_catalog_version:
        raise ConflictError("Active publication pointer changed outside publication")
    replay = uow.session.scalar(select(m.WorkflowCatalogPublication).where(
        m.WorkflowCatalogPublication.operation_key == operation))
    if replay is not None:
        read_revision(uow, workflow, replay.catalog_version)
        return replay.catalog_version
    definition = _definition(workflow.key, manifest)
    modes = _normalize(definition["modes"])
    parent = workflow.active_catalog_version if existing_version is None else 1
    if existing_version is None:
        latest = uow.session.scalar(select(func.max(m.WorkflowMode.catalog_version)).where(
            m.WorkflowMode.workflow_id == workflow.id))
        version = max(latest or 1, parent) + 1
        for mode in modes:
            _persist_mode(uow, workflow_id=workflow.id, role_key=definition["role_key"],
                          mode=ManagedMode.model_validate(mode), catalog_version=version)
    else:
        # Only the corrective migration adopts the exact already-installed 0029 baseline.
        version = existing_version
    expected = _ArchivedWorkflowDefinition(
        key=workflow.key, name=definition["name"], description=definition["description"],
        role_key=definition["role_key"], modes=[ManagedMode.model_validate(mode) for mode in modes],
    )
    _assert_existing_workflow(uow, workflow, expected, catalog_version=version)
    uow.session.execute(insert(m.WorkflowCatalogPublication).values(
        workflow_id=workflow.id, catalog_version=version, parent_version=parent,
        operation_key=operation,
        request_sha256=payload_sha256(_baseline_request(workflow.id, version, parent, manifest)),
        content_sha256=payload_sha256(modes), content=canonical_json(modes),
    ))
    uow.session.flush()
    if existing_version is None:
        uow.workflows.update(workflow.id, {"active_catalog_version": version})
    return version


def _mode_identity(modes: list[dict]) -> list[tuple]:
    return [(mode["key"], mode["mode_order"], mode["execution_scopes"]) for mode in modes]


def _validate_modes(workflow: Any, modes: list[dict], definition: dict) -> None:
    baseline = _normalize(definition["modes"])
    if workflow.key != "single-task-v1:architect":
        if _structure(modes) != _structure(baseline):
            raise ConflictError("Only text may change; role, scopes, skills and phase structure are frozen")
        return
    if _mode_identity(modes) != _mode_identity(baseline):
        raise ConflictError("Architect mode identity and scopes are immutable")
    allowed = {skill for mode in baseline for phase in mode["phases"]
               for instruction in phase["instructions"] for skill in instruction["skills"]}
    for mode in modes:
        for phase in mode["phases"]:
            if (phase["code"] != f"AR-DECOMP-{phase['phase_order']:02d}"
                    or phase["execution_type"] != "sync"
                    or phase["parallel_with_phase_code"] is not None
                    or phase["rollback_target_phase_code"] is not None
                    or not phase["instructions"] or not phase["checks"] or not phase["evidence"]):
                raise ConflictError("Architect phases require ordered synchronous work, checks and evidence")
            for instruction in phase["instructions"]:
                skills = set(instruction["skills"])
                if (instruction["execution_type"] != "sync" or "project-workflow-executor" not in skills
                        or not skills <= allowed):
                    raise ConflictError("Architect instructions must use the existing synchronous role skills")


def _validate_rows(
    uow: SAUnitOfWork, workflow: Any, version: int, modes: list[dict], definition: dict | None = None,
) -> None:
    if definition is None:
        definition, _ = sealed_baseline(uow, workflow, version)
    # Readback validates saved content, not a later policy for publishing new content.
    if _mode_identity(modes) != _mode_identity(definition["modes"]):
        raise ConflictError("Published mode identity and scopes changed")
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
    definition, baseline_version = sealed_baseline(uow, workflow, version)
    return _read_revision(uow, workflow, version, definition, baseline_version)


def _read_revision(
    uow: SAUnitOfWork, workflow: Any, version: int, definition: dict, baseline_version: int,
) -> dict:
    if version == baseline_version:
        modes = _normalize(definition["modes"])
    else:
        receipt = uow.session.get(m.WorkflowCatalogPublication, (workflow.id, version))
        if receipt is None:
            raise ConflictError("Unpublished instruction revision")
        modes = _normalize(json.loads(receipt.content))
        if payload_sha256(modes) != receipt.content_sha256:
            raise ConflictError("Publication receipt hash mismatch")
    _validate_rows(uow, workflow, version, modes, definition)
    result = {"workflow_id": workflow.id, "catalog_version": version,
              "content_sha256": payload_sha256(modes), "modes": modes}
    if version != baseline_version:
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
    # Validate namespace and selected-source provenance before historical revision reads.
    from project_workflow.infrastructure.db.single_task_catalog import observe_installation

    if not any(int(binding.workflow_id) == workflow_id for binding in observe_installation(uow).bindings):
        raise ConflictError("Installed single-task workflow required")
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
    if (version == sealed_baseline(uow, workflow, version)[1]
            or uow.session.get(m.WorkflowCatalogPublication, (workflow_id, version)) is not None):
        return {**read_revision(uow, workflow, version), "published": True,
                "active_catalog_version": workflow.active_catalog_version}
    return _draft_result(workflow, version, modes)


def read_pending_draft(uow: SAUnitOfWork, workflow_id: int) -> dict | None:
    _locked(uow, workflow_id)
    version = uow.session.scalar(select(func.max(m.WorkflowMode.catalog_version)).where(
        m.WorkflowMode.workflow_id == workflow_id, m.WorkflowMode.catalog_version > 1,
        ~select(m.WorkflowCatalogPublication.catalog_version).where(
            m.WorkflowCatalogPublication.workflow_id == workflow_id,
            m.WorkflowCatalogPublication.catalog_version == m.WorkflowMode.catalog_version,
        ).exists()))
    return read_draft(uow, workflow_id, version) if version is not None else None


def _editable_baseline(uow: SAUnitOfWork, workflow: Any) -> dict:
    receipt = _baseline_receipt(uow, workflow)
    if receipt is None:
        raise ConflictError("Missing installed baseline receipt")
    digest = _baseline_manifest(receipt)
    source = CATALOG_MANIFESTS.get(digest)
    if source is None or source.execution_protocol != PROTOCOL:
        raise ConflictError("Installed catalog does not support configured-cli-v1 publication")
    definition = _definition(workflow.key, digest)
    _validate_baseline_receipt(receipt, definition)
    return definition


def save_draft(uow: SAUnitOfWork, workflow_id: int, command: CatalogDraft) -> dict:
    workflow = _locked(uow, workflow_id)
    definition = _editable_baseline(uow, workflow)
    _cas(uow, workflow, command.expected_version, command.expected_sha256)
    modes = _normalize(command.modes)
    _validate_modes(workflow, modes, definition)
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
        _persist_mode(uow, workflow_id=workflow_id, role_key=definition["role_key"],
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
    _validate_modes(workflow, modes, _editable_baseline(uow, workflow))
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
