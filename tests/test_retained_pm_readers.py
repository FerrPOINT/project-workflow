"""Known old formats stay readable after upgrade without gaining execution rights."""

import json
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select

from project_workflow import build_provenance
from project_workflow.application.pm_execution import PMExecutionService
from project_workflow.application.single_task_runtime import retained_context
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.pm_execution import PMIdentity
from project_workflow.domain.runtime_assignment import canonical_json, payload_sha256
from project_workflow.domain.single_task_profile import SUPPORTED_MANIFESTS
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._retained_pm_history import retained_pm


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
