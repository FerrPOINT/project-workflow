"""Known old formats stay readable after upgrade without gaining execution rights."""

import json
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from project_workflow import build_provenance
from project_workflow.application.pm_execution import PMExecutionService
from project_workflow.application.single_task_runtime import retained_context
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.pm_execution import PMIdentity, PMReviewAdmissionContext
from project_workflow.domain.runtime_assignment import canonical_json, payload_sha256
from project_workflow.domain.single_task_profile import SUPPORTED_MANIFESTS
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._retained_pm_history import retained_pm
from tests.test_retained_single_task_binding import stored_pm as stored_pm


@pytest.fixture
def historical(monkeypatch):
    yield from retained_pm(monkeypatch)


def snapshot():
    with SAUnitOfWork() as uow:
        result = {}
        for model in (m.Task, m.TaskRuntimeAssignment, m.PMExecution, m.PMRun, m.PMOperation):
            mapper = inspect(model)
            rows = uow.session.scalars(select(model).order_by(*mapper.primary_key)).all()
            result[model.__name__] = [
                {column.key: getattr(row, column.key) for column in mapper.columns} for row in rows
            ]
        return result


def read(identity):
    with SAUnitOfWork() as uow:
        namespace = uow.projects.get_by_cli_command("workflow-project_manager")
        return PMExecutionService(uow).readback(PMIdentity.model_validate(identity), namespace.id, None)


def test_saved_pm_history_survives_foreign_or_unavailable_current_image(historical, monkeypatch):
    current_image = Mock(side_effect=AssertionError("history must not require the old executing image"))
    monkeypatch.setattr(build_provenance, "runtime_compatibility_descriptor", current_image)
    before = snapshot()
    for _ in range(2):
        result = read(historical[1])
        assert result["identity"] == historical[1]
        assert result["workflow_step_allowed"] is False
        assert result["session_run_id"] == before["PMRun"][0]["session_run_id"]
    current_image.assert_not_called()
    assert snapshot() == before


@pytest.mark.parametrize("corruption", ["payload_hash", "rehash_foreign_root", "concrete_agent", "identity"])
def test_read_only_decoding_does_not_accept_tampered_custody(historical, corruption):
    with SAUnitOfWork() as uow:
        assignment = uow.session.scalar(select(m.TaskRuntimeAssignment))
        if corruption in {"payload_hash", "rehash_foreign_root"}:
            payload = json.loads(assignment.payload)
            payload["root_task_ref"] = "foreign-retained-root"
            assignment.payload = canonical_json(payload)
            if corruption == "rehash_foreign_root":
                assignment.payload_sha256 = payload_sha256(payload)
        elif corruption == "concrete_agent":
            assignment.concrete_agent_ref = str(uuid4())
        else:
            execution = uow.session.scalar(select(m.PMExecution))
            execution.agent_ref = str(uuid4())
    before = snapshot()
    with pytest.raises(ConflictError):
        read(historical[1])
    assert snapshot() == before


@pytest.mark.parametrize("manifest", sorted(SUPPORTED_MANIFESTS))
def test_retained_known_manifest_decoding_is_independent_from_new_installation(manifest):
    context = {"instruction_profile": "single-task-v1", "instruction_manifest_sha256": manifest,
               "tracker_instance_ref": "tracker:one", "tracker_project_ref": str(uuid4()),
               "execution_ref": str(uuid4()), "concrete_agent_ref": str(uuid4()),
               "task_revision": 1, "lease_ref": str(uuid4()), "lease_version": 1, "fencing_token": 1}
    assert retained_context(context) == context
    with pytest.raises(ValueError):
        retained_context({**context, "instruction_manifest_sha256": "0" * 64})


@pytest.mark.parametrize("field,value", [
    ("tracker_assignment_revision", 1), ("tracker_assignment_revision", True),
    ("owner_version", 1), ("owner_version", 9007199254740992), ("blocker_version", "2"),
    ("blocker_id", "not-a-uuid"), ("blocker_sha256", "not-a-hash"), ("purpose", "initial"),
    ("requirements", {"revision": 7, "content_hash": "a" * 64, "foreign": True}),
])
def test_retained_review_context_remains_closed(field, value):
    context = {
        "purpose":"critical_business_review", "tracker_assignment_revision":8, "owner_version":2,
        "blocker_id":"22222222-2222-4222-8222-222222222205", "blocker_sha256":"c"*64,
        "blocker_version":2, "requirements":{"revision":7,"content_hash":"a"*64},
    }
    assert PMReviewAdmissionContext.model_validate(context).model_dump() == context
    with pytest.raises(ValidationError):
        PMReviewAdmissionContext.model_validate({**context,field:value})


@pytest.mark.parametrize("kind", ["bind", "checkpoint", "resume", "rebind", "resume_retry"])
def test_saved_operation_readback_returns_original_result_without_reexecution(historical, kind):
    identity = PMIdentity.model_validate(historical[1])
    saved = {"state": "waiting", "version": 7, "original": {"text": "saved owner input"}}
    with SAUnitOfWork() as uow:
        uow.session.add(m.PMOperation(
            operation_key="retained:operation", execution_ref=identity.execution_ref,
            kind=kind, request_sha256="a" * 64, result_json=canonical_json(saved),
        ))
    before = snapshot()
    with SAUnitOfWork() as uow:
        namespace = uow.projects.get_by_cli_command("workflow-project_manager")
        service = PMExecutionService(uow)
        for _ in range(2):
            result = service.readback(identity, namespace.id, "retained:operation")
            assert result["operation"] == {
                "operation_key": "retained:operation", "kind": kind,
                "request_sha256": "a" * 64, "result": saved,
            }
            assert result["workflow_step_allowed"] is False
        assert service.readback(identity, namespace.id, "missing:operation")["operation"] is None
    assert snapshot() == before


@pytest.mark.parametrize("field,value", [
    ("bind_operation_key", None), ("bind_request_sha256", "0" * 64),
    ("binding_ref", None), ("hermes_run_ref", None),
])
def test_database_or_reader_rejects_missing_or_forged_binding_provenance(historical, field, value):
    if value is None:
        before = snapshot()
        with pytest.raises(IntegrityError), SAUnitOfWork() as uow:
            assignment = uow.session.scalar(select(m.TaskRuntimeAssignment))
            setattr(assignment, field, value)
        assert snapshot() == before
        assert read(historical[1])["workflow_step_allowed"] is False
        return
    with SAUnitOfWork() as uow:
        assignment = uow.session.scalar(select(m.TaskRuntimeAssignment))
        setattr(assignment, field, value)
    before = snapshot()
    with pytest.raises(ConflictError):
        read(historical[1])
    assert snapshot() == before


@pytest.mark.parametrize("corruption", ["descriptor", "execution_identity", "missing_run"])
def test_retained_pm_authority_is_checked_before_returning_saved_results(historical, corruption):
    with SAUnitOfWork() as uow:
        assignment = uow.session.scalar(select(m.TaskRuntimeAssignment))
        if corruption == "descriptor":
            payload = json.loads(assignment.payload)
            payload["runtime_compatibility"] = {"catalogVersion": 999}
            assignment.payload = canonical_json(payload)
            assignment.payload_sha256 = payload_sha256(payload)
        elif corruption == "execution_identity":
            execution = uow.session.scalar(select(m.PMExecution))
            identity = json.loads(execution.identity_json)
            identity["tracker_project_ref"] = str(uuid4())
            execution.identity_json = canonical_json(identity)
        else:
            uow.session.delete(uow.session.scalar(select(m.PMRun)))
    before = snapshot()
    with pytest.raises(ConflictError):
        read(historical[1])
    assert snapshot() == before


def test_retained_pm_operation_cannot_be_read_through_another_execution(historical, stored_pm):
    with SAUnitOfWork() as uow:
        uow.session.add(m.PMOperation(
            operation_key="foreign:operation", execution_ref=stored_pm[0].execution_ref, kind="checkpoint",
            request_sha256="a" * 64, result_json=canonical_json({"private": "foreign saved result"}),
        ))
    before = snapshot()
    with pytest.raises(ConflictError, match="Foreign command key"), SAUnitOfWork() as uow:
        namespace = uow.projects.get_by_cli_command("workflow-project_manager")
        PMExecutionService(uow).readback(PMIdentity.model_validate(historical[1]), namespace.id, "foreign:operation")
    assert snapshot() == before
