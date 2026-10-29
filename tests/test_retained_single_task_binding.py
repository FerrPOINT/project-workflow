"""Saved binding integrity is checked without executing or reopening an old run."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from project_workflow.application.single_task_runtime import context_hash, current_binding
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.domain.single_task_profile import SUPPORTED_MANIFESTS


def saved(manifest):
    agent, execution, root = (str(uuid4()) for _ in range(3))
    context = {"instruction_profile": "single-task-v1", "instruction_manifest_sha256": manifest,
               "tracker_instance_ref": "tracker:retained", "tracker_project_ref": str(uuid4()),
               "execution_ref": execution, "concrete_agent_ref": agent, "task_revision": 1,
               "lease_ref": str(uuid4()), "lease_version": 1, "fencing_token": 1}
    record = {"id": 1, "task_id": 2, "project_id": 3, "workflow_id": 4,
              "workflow_key": "single-task-v1:developer", "mode_key": "initial", "role_key": "developer",
              "execution_scope": "delivery", "stage_key": "Development", "business_task_ref": root,
              "root_task_ref": root, "assignment_ref": str(uuid4()), "cycle_number": 0, "attempt_number": 1,
              "operation_key": "retained:assignment", "binding_ref": "retained:binding",
              "hermes_run_ref": "retained:run", "concrete_agent_ref": agent,
              "assignment_revision": 1, "bind_operation_key": "retained:bind"}
    payload = {key: value for key, value in record.items() if key not in {
        "id", "task_id", "binding_ref", "hermes_run_ref", "concrete_agent_ref",
        "assignment_revision", "bind_operation_key"}}
    payload["single_task_context"] = context
    request = {key: record[key] for key in (
        "binding_ref", "hermes_run_ref", "assignment_ref", "assignment_revision", "role_key",
        "cycle_number", "attempt_number", "mode_key", "concrete_agent_ref", "bind_operation_key")}
    request["assignment_operation_key"] = record["operation_key"]
    digest = payload_sha256(payload)
    record.update(payload=payload, payload_sha256=digest, bind_request_sha256=payload_sha256(request),
                  single_task_binding={"request": request, "context": deepcopy(context),
                                       "assignment_sha256": digest, "task_ref": root, "root_ref": root})
    session = SimpleNamespace(scalar=lambda _query: None, get=lambda *_args: None)
    return SimpleNamespace(session=session), record


@pytest.mark.parametrize("manifest", sorted(SUPPORTED_MANIFESTS))
def test_known_published_binding_families_remain_readable_without_current_image(manifest):
    uow, record = saved(manifest)
    before = deepcopy(record)
    result = current_binding(uow, record)
    assert result == record["single_task_binding"]
    assert context_hash(uow, record) == payload_sha256(result)
    assert record == before


@pytest.mark.parametrize("corruption", ["payload_hash", "binding_absent", "context", "assignment_hash",
    "task", "root", "foreign_role", "foreign_agent", "request_assignment", "request_hash", "request_run"])
def test_corrupt_saved_custody_is_refused_without_repair(corruption):
    uow, record = saved(sorted(SUPPORTED_MANIFESTS)[0])
    binding = record["single_task_binding"]
    if corruption == "payload_hash":
        record["payload_sha256"] = "0" * 64
    elif corruption == "binding_absent":
        record["single_task_binding"] = None
    elif corruption == "context":
        binding["context"]["task_revision"] += 1
    elif corruption == "assignment_hash":
        binding["assignment_sha256"] = "0" * 64
    elif corruption in {"task", "root"}:
        binding[corruption + "_ref"] = str(uuid4())
    elif corruption == "foreign_role":
        record["role_key"] = "reviewer"
    elif corruption == "foreign_agent":
        record["concrete_agent_ref"] = str(uuid4())
    elif corruption == "request_assignment":
        binding["request"]["assignment_operation_key"] = "foreign:assignment"
    elif corruption == "request_hash":
        record["bind_request_sha256"] = "0" * 64
    else:
        binding["request"]["hermes_run_ref"] = "foreign:run"
        record["bind_request_sha256"] = payload_sha256(binding["request"])
    before = deepcopy(record)
    with pytest.raises(ConflictError):
        current_binding(uow, record)
    assert record == before


def test_retained_pm_snapshot_adds_its_saved_run_without_mutating_the_original_binding():
    uow, record = saved(sorted(SUPPORTED_MANIFESTS)[0])
    execution = SimpleNamespace(session_run_id=str(uuid4()), fence=7)
    run = SimpleNamespace(execution_ref=record["payload"]["single_task_context"]["execution_ref"],
                          session_run_id=execution.session_run_id, binding_ref="saved:binding", run_ref="saved:run")
    uow.session.scalar = lambda _query: execution
    uow.session.get = lambda *_args: run
    before = deepcopy(record)
    value = current_binding(uow, record)
    assert value["pm_run"] == {"session_run_id": run.session_run_id, "binding_ref": run.binding_ref,
                               "hermes_run_ref": run.run_ref, "fence": 7}
    assert "pm_run" not in record["single_task_binding"]
    assert record == before
    run.execution_ref = str(uuid4())
    with pytest.raises(ConflictError, match="run binding mismatch"):
        current_binding(uow, record)
    uow.session.get = lambda *_args: None
    with pytest.raises(ConflictError, match="run binding mismatch"):
        current_binding(uow, record)


@pytest.fixture
def stored_pm():
    import json

    from project_workflow.domain.pm_execution import PMIdentity, RuntimeObservation
    from project_workflow.domain.runtime_assignment import canonical_json
    from project_workflow.infrastructure.db import models as m
    from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog
    from project_workflow.infrastructure.db.uow import SAUnitOfWork

    _, record = saved(sorted(SUPPORTED_MANIFESTS)[0])
    context = record["payload"]["single_task_context"]
    with SAUnitOfWork() as uow:
        installed = ensure_single_task_catalog(uow)
        namespace = next(b for b in installed.bindings if b.role_key == "project_manager")
        mode = namespace.modes[0]
        phase = int(mode.phase_ids[0])
        payload = {**record["payload"], "project_id": int(namespace.namespace_id),
                   "workflow_id": int(namespace.workflow_id), "mode_id": int(mode.mode_id),
                   "role_key": "project_manager", "workflow_key": "single-task-v1:project_manager",
                   "execution_scope": "business", "stage_key": "Draft", "mode_key": "draft",
                   "task_key": "SDLC-9000", "exact_input_refs": []}
        digest = payload_sha256(payload)
        request = {**record["single_task_binding"]["request"], "role_key": "project_manager", "mode_key": "draft"}
        binding = {**record["single_task_binding"], "request": request, "assignment_sha256": digest}
        task_id = uow.tasks.create({"project_id": payload["project_id"], "workflow_id": payload["workflow_id"],
            "mode_id": payload["mode_id"], "task_key": payload["task_key"], "current_phase_id": phase,
            "status": "active", "cycle_number": 0, "assignment_revision": 1,
            "assignment_operation_key": payload["operation_key"]})
        assignment = m.TaskRuntimeAssignment(task_id=task_id, project_id=payload["project_id"],
            workflow_id=payload["workflow_id"], mode_id=payload["mode_id"], workflow_key=payload["workflow_key"],
            operation_key=payload["operation_key"], cycle_number=0, attempt_number=1, assignment_revision=1,
            role_key="project_manager", execution_scope="business", stage_key="Draft",
            business_task_ref=record["business_task_ref"], root_task_ref=record["root_task_ref"],
            assignment_ref=record["assignment_ref"], binding_ref=record["binding_ref"],
            hermes_run_ref=record["hermes_run_ref"], bind_operation_key=record["bind_operation_key"],
            bind_request_sha256=payload_sha256(request), concrete_agent_ref=context["concrete_agent_ref"],
            exact_input_refs="[]", payload=canonical_json(payload), payload_sha256=digest,
            single_task_binding_json=canonical_json(binding))
        uow.session.add(assignment)
        uow.session.flush()
        identity = PMIdentity.model_validate({"task": payload["task_key"], "execution_ref": context["execution_ref"],
            "tracker_instance_ref": context["tracker_instance_ref"],
            "tracker_project_ref": context["tracker_project_ref"],
            "task_ref": record["business_task_ref"], "root_ref": record["root_task_ref"],
            "agent_ref": context["concrete_agent_ref"], "assignment_operation_key": payload["operation_key"],
            "assignment_ref": record["assignment_ref"], "assignment_revision": 1})
        session_id = str(uuid4())
        observation = RuntimeObservation.model_validate({
            **identity.model_dump(), "observation_ref": "saved:observation",
            "status": "running", "binding_ref": record["binding_ref"], "hermes_run_ref": record["hermes_run_ref"],
            "dispatch_operation_key": "saved:dispatch", "fence": 1, "session_run_id": session_id})
        checkpoint = {"checkpoint_id": str(uuid4()), "resume_input": {"text": "Original saved owner input"}}
        uow.session.add(m.PMExecution(execution_ref=identity.execution_ref, task_id=task_id,
            assignment_id=assignment.id, tracker_instance_ref=identity.tracker_instance_ref,
            tracker_project_ref=identity.tracker_project_ref, task_ref=identity.task_ref, root_ref=identity.root_ref,
            agent_ref=identity.agent_ref, identity_json=canonical_json(identity.model_dump()), state="waiting",
            version=1, fence=1, session_run_id=session_id, phase_id=phase, checkpoint_json=canonical_json(checkpoint)))
        uow.session.flush()
        uow.session.add(m.PMRun(session_run_id=session_id, execution_ref=identity.execution_ref,
            run_ref=record["hermes_run_ref"], binding_ref=record["binding_ref"], fence=1,
            observation_json=canonical_json(observation.model_dump())))
        uow.commit()
        # Materialize JSON now; no lazy ORM references escape the transaction.
        return identity, payload["project_id"], json.loads(canonical_json(checkpoint))


def test_saved_single_task_pm_keeps_resume_input_without_requiring_the_old_image(stored_pm):
    from project_workflow.application.pm_execution import PMExecutionService
    from project_workflow.infrastructure.db.uow import SAUnitOfWork
    from tests.test_retained_pm_readers import snapshot

    identity, namespace, checkpoint = stored_pm
    before = snapshot()
    with SAUnitOfWork() as uow:
        result = PMExecutionService(uow).readback(identity, namespace, None)
        assert result["workflow_step_allowed"] is False
        assert result["resume_input"] == checkpoint["resume_input"]
        assert result["checkpoint"] == {"checkpoint_id": checkpoint["checkpoint_id"]}
        assert len(result["single_task_context_sha256"]) == 64
    assert snapshot() == before


@pytest.mark.parametrize("corruption", ["foreign_run", "missing_run", "foreign_context", "draft_context",
    "malformed_review", "wrong_review_scope", "retired_bootstrap"])
def test_retained_pm_rejects_saved_custody_drift_without_modifying_history(stored_pm, corruption):
    import json

    from sqlalchemy import select

    from project_workflow.application.pm_execution import PMExecutionService
    from project_workflow.domain.runtime_assignment import canonical_json
    from project_workflow.infrastructure.db import models as m
    from project_workflow.infrastructure.db.uow import SAUnitOfWork
    from tests.test_retained_pm_readers import snapshot

    identity, namespace, _ = stored_pm
    with SAUnitOfWork() as uow:
        execution = uow.session.get(m.PMExecution, identity.execution_ref)
        if corruption == "foreign_run":
            # Another retained execution exists; altering a current association must not authorize it.
            execution.session_run_id = str(uuid4())
        elif corruption == "missing_run":
            uow.session.delete(uow.session.get(m.PMRun, execution.session_run_id))
        else:
            assignment = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
                m.TaskRuntimeAssignment.id == execution.assignment_id))
            payload = json.loads(assignment.payload)
            if corruption == "foreign_context":
                payload["single_task_context"]["tracker_project_ref"] = str(uuid4())
            elif corruption == "draft_context":
                payload["pm_draft_context"] = {**identity.model_dump(), "agent_ref": str(uuid4())}
            elif corruption == "malformed_review":
                payload["pm_review_context"] = {}
            elif corruption == "wrong_review_scope":
                payload["pm_review_context"] = {
                    "purpose": "critical_business_review", "tracker_assignment_revision": 8,
                    "owner_version": 2, "blocker_id": str(uuid4()), "blocker_sha256": "c" * 64,
                    "blocker_version": 2, "requirements": {"revision": 7, "content_hash": "a" * 64}}
            else:
                payload["pm_bootstrap_context"] = {}
            assignment.payload = canonical_json(payload)
            assignment.payload_sha256 = payload_sha256(payload)
    before = snapshot()
    with pytest.raises((ConflictError, ValueError)), SAUnitOfWork() as uow:
        PMExecutionService(uow).readback(identity, namespace, None)
    assert snapshot() == before
