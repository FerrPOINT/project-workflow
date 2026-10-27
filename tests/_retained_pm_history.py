"""Construct retained PM rows directly; never replay a retired executable API."""

import json

from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.domain.pm_execution import PMIdentity, RuntimeObservation
from project_workflow.domain.runtime_assignment import canonical_json, payload_sha256
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from project_workflow.interfaces.ui.schemas import RuntimeAssignmentRequest
from tests.test_runtime_api import _assignment, _bind_payload, _namespace

PROJECT_REF = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
AGENT_REF = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OLD_RUN = "11111111-1111-4111-8111-111111111111"


def retained_pm(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"project_manager": "a" * 40}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"project_manager": "r" * 40}))
    config.get_settings.cache_clear()
    _namespace("PM", "workflow-project_manager", "PM")
    request = RuntimeAssignmentRequest.model_validate(_assignment("PM-1", "assign:pm:1", "project_manager"))
    with SAUnitOfWork() as uow:
        namespace = uow.projects.get_by_cli_command("workflow-project_manager")
        mode = uow.workflows.get_mode_by_key(namespace.workflow_id, "assigned")
        phase = uow.phases.list(namespace.workflow_id, mode_id=mode.id)[0]
        payload = request.model_dump()
        payload["task_key"] = payload.pop("task")
        payload.update(project_id=namespace.id, workflow_id=namespace.workflow_id, mode_id=mode.id)
        values = {
            **payload,
            "assignment_operation_key": payload["operation_key"],
            "assignment_revision": 1,
            "current_phase_id": phase.id,
        }
        task_id = uow.tasks.create(values)
        bound = {**values, "concrete_agent_ref": AGENT_REF}
        binding = _bind_payload(bound)
        binding["concrete_agent_ref"] = AGENT_REF
        digest = {k: v for k, v in binding.items() if k != "task"}
        digest.update(project_id=namespace.id, task_key="PM-1", role_key="project_manager")
        values.update(
            task_id=task_id,
            binding_ref=binding["binding_ref"],
            hermes_run_ref=binding["hermes_run_ref"],
            bind_operation_key=binding["bind_operation_key"],
            bind_request_sha256=payload_sha256(digest),
            payload=payload,
            payload_sha256=payload_sha256(payload),
        )
        assignment_id = uow.tasks.create_assignment(values)
        row = uow.session.get(m.TaskRuntimeAssignment, assignment_id)
        row.concrete_agent_ref = AGENT_REF
        uow.projects.create_pm_ownership(
            {
                "contract_version": 1,
                "ownership_ref": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                "namespace_id": namespace.id,
                "tracker_instance_ref": "tracker:one",
                "tracker_project_ref": PROJECT_REF,
                "authority_issuer": "http://auth.test",
                "provisioner_subject": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
            }
        )
        identity = PMIdentity.model_validate(
            {
                "task": "PM-1",
                "execution_ref": "execution:pm:1",
                "tracker_instance_ref": "tracker:one",
                "tracker_project_ref": PROJECT_REF,
                "task_ref": request.business_task_ref,
                "root_ref": request.root_task_ref,
                "agent_ref": AGENT_REF,
                "assignment_operation_key": request.operation_key,
                "assignment_ref": request.assignment_ref,
                "assignment_revision": 1,
            }
        )
        observation = RuntimeObservation.model_validate(
            {
                **identity.model_dump(mode="json"),
                "observation_ref": "observation:1",
                "status": "running",
                "binding_ref": binding["binding_ref"],
                "hermes_run_ref": binding["hermes_run_ref"],
                "dispatch_operation_key": "pm-bind:1",
                "fence": 1,
                "session_run_id": OLD_RUN,
            }
        )
        uow.session.add(
            m.PMExecution(
                execution_ref=identity.execution_ref,
                task_id=task_id,
                assignment_id=assignment_id,
                tracker_instance_ref=identity.tracker_instance_ref,
                tracker_project_ref=PROJECT_REF,
                task_ref=identity.task_ref,
                root_ref=identity.root_ref,
                agent_ref=AGENT_REF,
                identity_json=canonical_json(identity.model_dump(mode="json")),
                state="active",
                version=1,
                fence=1,
                session_run_id=OLD_RUN,
                phase_id=phase.id,
            )
        )
        uow.session.flush()
        uow.session.add(
            m.PMRun(
                session_run_id=OLD_RUN,
                run_ref=binding["hermes_run_ref"],
                execution_ref=identity.execution_ref,
                binding_ref=binding["binding_ref"],
                fence=1,
                observation_json=canonical_json(observation.model_dump(mode="json")),
            )
        )
        uow.commit()
    with TestClient(create_app()) as client:
        yield client, identity.model_dump(mode="json"), binding, {}, bound
