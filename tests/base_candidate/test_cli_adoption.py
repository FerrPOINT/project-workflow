"""Append-only CLI catalog adoption through the existing machine execution protocol."""

import copy
import hashlib
import json
import os

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from project_workflow import config, supervisor
from project_workflow.application import base_binding, base_source
from project_workflow.application.task import TaskService
from project_workflow.build_provenance import BuildProvenanceError, validate_runtime_compatibility
from project_workflow.domain.base_binding import BaseNamespaceBinding
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog, load_managed_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from scripts.build_runtime_image import derive_compatibility
from tests.base_candidate.test_source import source as source
from tests.test_managed_catalog import _project_manager_request
from tests.test_pm_draft_assignment import (
    prepare_pm_draft,
)
from tests.test_pm_draft_assignment import (
    test_pm_draft_assign_uses_real_input_without_future_resources as assert_draft_assignment,
)
from tests.test_pm_execution import (
    prepare_pm,
)
from tests.test_pm_execution import (
    test_wait_resume_new_run_survives_sessions_and_replays as assert_checkpoint_rebind,
)
from tests.test_runtime_api import TEST_RUNTIME_COMPATIBILITY, _assignment, _bind_payload, _step_payload


@pytest.fixture
def cli(source, monkeypatch):
    from project_workflow.infrastructure import base_package

    monkeypatch.setattr(base_package, "load_pinned_package", lambda *_: source)
    monkeypatch.setattr(config, "CATALOG_VARIANT", "base-cli")
    monkeypatch.setattr(config, "MANAGED_CATALOG_PATH", base_source.CLI_CANDIDATE_PATH)
    return {**TEST_RUNTIME_COMPATIBILITY, "catalogVersion": 4, "skillsRevision": base_source.CLI_SKILLS_REVISION}


def rows(uow, model):
    return [dict(row) for row in uow.session.execute(select(model.__table__)).mappings()]


def test_adoption_retains_v3_modes_tasks_and_history_and_is_idempotent(cli):
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow, base_source.CANDIDATE_PATH)
        namespace = uow.projects.get_by_cli_command("workflow-project_manager")
        old_mode = uow.workflows.get_mode_by_key(namespace.workflow_id, "draft")
        phase = uow.phases.list(namespace.workflow_id, mode_id=old_mode.id)[0]
        for number, status in enumerate(("active", "done")):
            task_id = uow.tasks.create({
                "task_key": f"PM-OLD-{number}", "project_id": namespace.id, "workflow_id": namespace.workflow_id,
                "mode_id": old_mode.id, "current_phase_id": phase.id, "status": status,
            })
            assignment = _project_manager_request(namespace.id)
            assignment.update(
                operation_key=f"old:{number}", task_id=task_id, workflow_id=namespace.workflow_id,
                mode_id=old_mode.id, binding_ref=f"old-binding:{number}", hermes_run_ref=f"old-run:{number}",
                assignment_revision=1, payload_sha256="a" * 64,
                payload={"catalog_version": 3, "original_operation_key": f"old:{number}"},
            )
            uow.tasks.create_assignment(assignment)
            uow.session.add(m.TaskStepHistoryEntry(
                task_id=task_id, workflow_id=namespace.workflow_id, mode_id=old_mode.id,
                phase_id=phase.id, verdict="pass", worker_report="historical report",
            ))
        uow.session.flush()
        before = {model: rows(uow, model) for model in (
            m.WorkflowMode, m.Phase, m.Task, m.TaskRuntimeAssignment, m.TaskStepHistoryEntry,
        )}
        workflow_ids = {item.key: item.id for item in uow.workflows.list()}
        ensure_managed_catalog(uow, base_source.CLI_CANDIDATE_PATH)
        assert {item.key: item.id for item in uow.workflows.list()} == workflow_ids
        assert all(item.active_catalog_version == 4 for item in uow.workflows.list()
                   if item.key.startswith("hermes-sdlc:"))
        for model, original in before.items():
            current = rows(uow, model)
            assert [row for row in current if row["id"] in {old["id"] for old in original}] == original
        assert uow.workflows.get_mode_by_key(namespace.workflow_id, "draft").id != old_mode.id
        after = {model: rows(uow, model) for model in before}
        ensure_managed_catalog(uow, base_source.CLI_CANDIDATE_PATH)
        assert {model: rows(uow, model) for model in after} == after
        binding = base_binding.observe_base_namespace_binding(uow, namespace.id)
        assert binding.catalog_version == 4 and binding.skills_revision == base_source.CLI_SKILLS_REVISION
        assert binding.runtime_ready is False
        with pytest.raises(ValidationError, match="version/package"):
            BaseNamespaceBinding.model_validate({**binding.model_dump(by_alias=True), "catalog_version": 3})


def test_adoption_rejects_changed_v3_instructions_without_switch(cli):
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow, base_source.CANDIDATE_PATH)
        instruction = uow.session.scalar(select(m.PhaseInstruction).join(m.Phase).join(m.WorkflowMode).where(
            m.WorkflowMode.catalog_version == 3,
        ))
        instruction.description = "foreign instruction"
        uow.session.flush()
        with pytest.raises(ValueError, match="different instructions"):
            ensure_managed_catalog(uow, base_source.CLI_CANDIDATE_PATH)
        assert all(item.active_catalog_version == 3 for item in uow.workflows.list()
                   if item.key.startswith("hermes-sdlc:"))


def test_adoption_rejects_partial_switch_before_appending_any_modes(cli):
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow, base_source.CANDIDATE_PATH)
        workflow = uow.workflows.get_by_id(uow.projects.get_by_cli_command("workflow-project_manager").workflow_id)
        uow.workflows.update(workflow.id, {"active_catalog_version": 4})
        before = rows(uow, m.WorkflowMode)
        with pytest.raises(ValueError, match="partial CLI"):
            ensure_managed_catalog(uow, base_source.CLI_CANDIDATE_PATH)
        assert rows(uow, m.WorkflowMode) == before


def test_adoption_rejects_partial_target_rows_before_switching_any_workflow(cli):
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow, base_source.CANDIDATE_PATH)
        workflow = uow.workflows.get_by_id(uow.projects.get_by_cli_command("workflow-devops").workflow_id)
        uow.workflows.create_mode({
            "workflow_id": workflow.id, "key": "delivery", "name": "Partial", "mode_order": 1,
            "catalog_version": 4, "role_key": "devops", "execution_scopes": ["delivery"],
            "tech_workspace_policy": "required",
        })
        before = rows(uow, m.WorkflowMode)
        with pytest.raises(ValueError, match="target rows already exist"):
            ensure_managed_catalog(uow, base_source.CLI_CANDIDATE_PATH)
        assert rows(uow, m.WorkflowMode) == before
        assert all(item.active_catalog_version == 3 for item in uow.workflows.list()
                   if item.key.startswith("hermes-sdlc:"))


def test_adoption_rejects_changed_v4_source_before_writes(cli):
    with SAUnitOfWork() as uow:
        candidate = load_managed_catalog(base_source.CLI_CANDIDATE_PATH)
        candidate.workflows[0].modes[0].phases[0].instructions[0].description = "foreign instruction"
        before = rows(uow, m.Workflow)
        # A validated but different caller catalog is not an adoption authority.
        from unittest.mock import patch

        with patch("project_workflow.infrastructure.db.managed_catalog.load_managed_catalog", return_value=candidate):
            with pytest.raises(ValueError, match="exact frozen v4"):
                ensure_managed_catalog(uow, base_source.CLI_CANDIDATE_PATH)
        assert rows(uow, m.Workflow) == before


def test_adoption_requires_real_base_pin_without_filesystem_fallback(cli, monkeypatch):
    from project_workflow.infrastructure import base_package

    def unavailable(*_):
        raise ValueError("Pinned Base Git source is unavailable")

    monkeypatch.setattr(base_package, "load_pinned_package", unavailable)
    with SAUnitOfWork() as uow:
        before = rows(uow, m.Workflow)
        with pytest.raises(ValueError, match="Pinned Base Git source"):
            ensure_managed_catalog(uow, base_source.CLI_CANDIDATE_PATH)
        assert rows(uow, m.Workflow) == before


@pytest.mark.skipif(
    not os.environ.get("WORKFLOW_BASE_PACKAGE_TEST_ROOT"), reason="Explicit authorized Base Git package required",
)
def test_real_pinned_base_package_adopts_v3_to_v4_without_relabeling_history(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_SKILLS_ROOT", os.environ["WORKFLOW_BASE_PACKAGE_TEST_ROOT"])
    monkeypatch.setattr(config, "CATALOG_VARIANT", "base-cli")
    config.get_settings.cache_clear()
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow, base_source.CANDIDATE_PATH)
        old_modes = rows(uow, m.WorkflowMode)
        ensure_managed_catalog(uow, base_source.CLI_CANDIDATE_PATH)
        assert [row for row in rows(uow, m.WorkflowMode) if row["catalog_version"] == 3] == [
            row for row in old_modes if row["catalog_version"] == 3
        ]
        namespace = uow.projects.get_by_cli_command("workflow-project_manager")
        binding = base_binding.observe_base_namespace_binding(uow, namespace.id)
        assert binding.skills_revision == base_source.CLI_SKILLS_REVISION and binding.catalog_version == 4


def test_cli_source_export_is_versioned_and_v3_bytes_remain_frozen(cli):
    _, current = base_source.load_base_source()
    _, historical = base_source.load_base_source(3)
    assert current["catalogVersion"] == 4
    assert current["workflowCatalogGitBlob"] == base_source.CLI_CANDIDATE_BLOB
    assert current["skillsCatalogRevision"] == base_source.CLI_SKILLS_REVISION
    assert historical["catalogVersion"] == 3
    assert historical["workflowCatalogGitBlob"] == base_source.CANDIDATE_BLOB
    content = base_source.CANDIDATE_PATH.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(content).hexdigest() == "a778e18d5d02a58caef0a12ccabdd9eaeb61efed1e71f2a9f3e402358458a7ed"
    assert current["runtimeReady"] is False and current["sourceOnly"] is True


@pytest.mark.parametrize("field,value", [
    ("skillsRevision", "4b9b4c9297a13fb28a6ba2039af2f7cb719f2f58"),
    ("capabilityRevision", "base-workflow-controlplane/v1"),
    ("catalogVersion", True),
])
def test_cli_compatibility_rejects_cross_version_tuple(cli, field, value):
    assert validate_runtime_compatibility(cli) == cli
    with pytest.raises(BuildProvenanceError):
        validate_runtime_compatibility({**cli, field: value})


def test_cli_pm_draft_uses_existing_authorized_assignment_api(cli, monkeypatch):
    setup = prepare_pm_draft(monkeypatch, catalog_path=base_source.CLI_CANDIDATE_PATH, compatibility=cli)
    try:
        draft = next(setup)
        assert_draft_assignment(draft)
    finally:
        setup.close()


def test_cli_pm_checkpoint_rebind_and_token_rotation_use_existing_contract(cli, monkeypatch):
    setup = prepare_pm(monkeypatch, catalog_path=base_source.CLI_CANDIDATE_PATH, compatibility=cli)
    try:
        pm = next(setup)
        assert_checkpoint_rebind(pm)
    finally:
        setup.close()


def test_cli_runtime_first_step_is_reportless_and_has_no_legacy_bypass(cli, monkeypatch):
    from tests.test_pm_execution import bind_pm
    from tests.test_runtime_api import _step_payload

    setup = prepare_pm(monkeypatch, catalog_path=base_source.CLI_CANDIDATE_PATH, compatibility=cli)
    try:
        pm = next(setup)
        client, runtime, checkpoint, _, bound = bind_pm(pm)
        step = {**_step_payload(bound), "session_run_id": checkpoint["session_run_id"]}
        response = client.post("/internal/runtime/step", headers=runtime, json=step)
        assert response.status_code == 200, response.text
        assert "project-workflow" in response.text and "--runtime-request" in response.text
        assert "workflow_step" not in response.text
        assert client.post("/internal/runtime/step", headers=runtime, json=step).json() == response.json()
        foreign = copy.deepcopy(step)
        foreign["mode_key"] = "analysis"
        assert client.post("/internal/runtime/step", headers=runtime, json=foreign).status_code == 409
        with SAUnitOfWork() as uow:
            namespace = uow.projects.get_by_cli_command("workflow-project_manager")
            task = uow.tasks.get_by_key("PM-1", project_id=namespace.id)
            assert task.current_phase_id is not None
            assert rows(uow, m.TaskStepHistoryEntry) == []
            with pytest.raises(ConflictError, match="owner-bound runtime"):
                supervisor.SupervisorEngine("PM-1", uow=uow, project_id=namespace.id, create_if_missing=False)
            with pytest.raises(ConflictError, match="owner-issued assignment"):
                TaskService(uow).create_task({"project_id": namespace.id, "task_key": "PM-2"})
    finally:
        setup.close()


@pytest.mark.parametrize("role,mode_key", [
    ("analyst", "analysis"), ("architect", "decomposition"), ("developer", "initial"),
    ("developer", "rework"), ("reviewer", "delivery"), ("reviewer", "integration"),
    ("tester", "delivery"), ("tester", "integration"), ("devops", "delivery"), ("devops", "integration"),
])
def test_cli_role_mode_first_step_requires_assignment_and_renders_frozen_instructions(cli, monkeypatch, role, mode_key):
    from project_workflow import build_provenance
    from project_workflow.interfaces.ui.routes import runtime_api

    monkeypatch.setattr(build_provenance, "runtime_compatibility_descriptor", lambda **_: cli)
    monkeypatch.setattr(runtime_api, "runtime_compatibility_descriptor", lambda **_: cli)
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({role: "a" * 40}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({role: "r" * 40}))
    config.get_settings.cache_clear()
    with SAUnitOfWork() as uow:
        catalog = ensure_managed_catalog(uow, base_source.CLI_CANDIDATE_PATH)
    definition = next(workflow for workflow in catalog.workflows if workflow.role_key == role)
    mode = next(mode for mode in definition.modes if mode.key == mode_key)
    request = _assignment("ROLE-1", "assign:role:1", role)
    request.update(runtime_compatibility=cli, mode_key=mode_key, execution_scope=mode.execution_scopes[0])
    if request["execution_scope"] != "business":
        request.update(tech_execution_workspace_ref="workspace:one", tech_execution_attempt_ref="attempt:one")
    with TestClient(create_app()) as client:
        adapter = {"Authorization": "Bearer " + "a" * 40}
        runtime = {"Authorization": "Bearer " + "r" * 40}
        assert client.post("/internal/runtime/assign", headers=runtime, json=request).status_code == 403
        assigned = client.post("/internal/runtime/assign", headers=adapter, json=request)
        assert assigned.status_code == 200, assigned.text
        bound = client.post("/internal/runtime/bind", headers=adapter, json=_bind_payload(assigned.json()["result"]))
        assert bound.status_code == 200, bound.text
        step = _step_payload(bound.json()["result"])
        response = client.post("/internal/runtime/step", headers=runtime, json=step)
        assert response.status_code == 200, response.text
        assert "--runtime-request" in response.text and "workflow_step" not in response.text
        assert response.json()["result"]["phase_code"] == mode.phases[0].code
        with SAUnitOfWork() as uow:
            assert rows(uow, m.TaskStepHistoryEntry) == []


def test_cli_image_descriptor_uses_existing_seven_field_machine_contract(cli, source, tmp_path, monkeypatch):
    root = tmp_path / "image"
    references = root / "project_workflow/references"
    references.mkdir(parents=True)
    references.joinpath(base_source.CLI_CANDIDATE_PATH.name).write_bytes(base_source.CLI_CANDIDATE_PATH.read_bytes())
    catalog = load_managed_catalog(base_source.CLI_CANDIDATE_PATH)
    manifest = {**source, "schema": catalog.skills_source.manifest_schema}
    root.joinpath("runtime-skills-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    root.joinpath("runtime-build-manifest.json").write_text(json.dumps({
        "schema_version": 1, "source_revision": "a" * 40,
        "source_archive_sha256": "b" * 64, "runtime_bundle_sha256": "c" * 64,
    }), encoding="utf-8")
    monkeypatch.setenv("PROJECT_WORKFLOW_CATALOG_VARIANT", "base-cli")
    descriptor = derive_compatibility(root)
    assert set(descriptor) == set(cli)
    assert descriptor["catalogVersion"] == 4
    assert descriptor["skillsRevision"] == base_source.CLI_SKILLS_REVISION
    assert descriptor["capabilityRevision"] == "hermes-sdlc-runtime/v2"
    assert validate_runtime_compatibility(descriptor) == descriptor
