"""Real SQLite bootstrap/readback; no containers or live runtime writes."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select

from project_workflow import config, supervisor
from project_workflow.application.task import TaskService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.single_task_profile import CATALOG_SHA256, MANIFEST_SHA256
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog
from project_workflow.infrastructure.db.session import ensure_migrated
from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog, observe_installation
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from project_workflow.interfaces.ui.routes import runtime_api
from project_workflow.interfaces.ui.schemas import RuntimeAssignmentRequest, SingleTaskAssignmentRequest
from scripts import build_single_task_profile, init_db


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'profile.db'}")
    ensure_migrated(engine)
    yield engine
    engine.dispose()


def rows(uow, table):
    return [dict(row) for row in uow.session.execute(select(table)).mappings()]


def test_real_bootstrap_repeats_with_exact_persisted_ids(database, monkeypatch, capsys):
    monkeypatch.setattr(config, "CATALOG_VARIANT", "single-task-v1")
    monkeypatch.setattr(init_db, "get_engine", lambda _url: database)
    assert init_db.main() == 0
    first = json.loads(next(line for line in capsys.readouterr().out.splitlines() if line.startswith("{")))
    assert init_db.main() == 0
    second = json.loads(next(line for line in capsys.readouterr().out.splitlines() if line.startswith("{")))
    assert first == second
    assert first["instruction_manifest_sha256"] == MANIFEST_SHA256
    assert first["workflow_catalog_sha256"] == CATALOG_SHA256
    assert [first[k] for k in ("namespaces", "workflows", "modes", "phases")] == [7, 7, 8, 24]
    assert first["runtime_ready"] is first["live_activation_allowed"] is False
    with SAUnitOfWork(database) as uow:
        assert observe_installation(uow).model_dump(mode="json", by_alias=True) == first
        assert len(uow.projects.list()) == len(uow.workflows.list()) == 7


def test_config_selector_runs_real_bootstrap_subprocess_twice(tmp_path):
    environment = dict(os.environ, PROJECT_WORKFLOW_CATALOG_VARIANT="single-task-v1",
                       DATABASE_URL=f"sqlite:///{(tmp_path / 'subprocess.db').as_posix()}")
    results = []
    for _ in range(2):
        completed = subprocess.run([sys.executable, "-m", "scripts.init_db"],
                                   cwd=Path(__file__).resolve().parents[1], env=environment,
                                   capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
        result = json.loads(next(line for line in completed.stdout.splitlines() if line.startswith("{")))
        results.append(result)
    assert results[0] == results[1]
    assert results[0]["instruction_profile"] == "single-task-v1"
    assert results[0]["modes"] == 8 and results[0]["phases"] == 24
    assert results[0]["live_activation_allowed"] is False


def test_side_by_side_preserves_every_legacy_row_and_history(database):
    with SAUnitOfWork(database) as uow:
        ensure_managed_catalog(uow)
        project = uow.projects.get_by_cli_command("workflow-developer")
        mode = uow.workflows.get_mode_by_key(project.workflow_id, "initial")
        phase = uow.phases.list(project.workflow_id, mode_id=mode.id)[0]
        task_id = uow.tasks.create({"project_id": project.id, "workflow_id": project.workflow_id, "mode_id": mode.id,
                                    "task_key": "OLD-7", "title": "Historical", "status": "active",
                                    "current_phase_id": phase.id})
        uow.record_step(task_id=task_id, phase_id=phase.id, verdict="pass", worker_report="Historical report",
                        covered_item_ids=[], missing_item_ids=[], blocker_messages=[],
                        evaluation_snapshot={}, supervisor_response={})
        instruction = uow.phase_instructions.list(phase.id)[0]
        uow.phase_instructions.update(instruction["id"], {"description": "Owner edited legacy instruction"})
        uow.commit()
        protected = {name: rows(uow, table) for name, table in m.Base.metadata.tables.items()}
        old_default = uow.workflows.get_default().id
        first = ensure_single_task_catalog(uow)
        uow.commit()
        second = ensure_single_task_catalog(uow)
        assert first == second
        assert len(uow.projects.list()) == len(uow.workflows.list()) == 14
        assert uow.workflows.get_default().id == old_default
        for name, table in m.Base.metadata.tables.items():
            current = rows(uow, table)
            assert all(row in current for row in protected[name]), name


@pytest.mark.parametrize("drift", ["instruction", "mode", "mode_name", "namespace", "missing", "extra"])
def test_repeat_bootstrap_rejects_drift_without_repair(database, drift):
    with SAUnitOfWork(database) as uow:
        installation = ensure_single_task_catalog(uow)
        binding = installation.bindings[0]
        if drift == "instruction":
            row = uow.phase_instructions.list(int(binding.modes[0].phase_ids[0]))[0]
            uow.phase_instructions.update(row["id"], {"description": "tampered"})
        elif drift == "mode":
            row = uow.session.get(m.WorkflowMode, int(binding.modes[0].mode_id))
            row.execution_scopes = ["aggregate"]
        elif drift == "mode_name":
            uow.session.get(m.WorkflowMode, int(binding.modes[0].mode_id)).name = "Foreign mode name"
        elif drift == "namespace":
            uow.projects.update(int(binding.namespace_id), {"launch_profile": "foreign-profile"})
        elif drift == "extra":
            uow.workflows.create({"key": "single-task-v1:foreign", "name": "Foreign"})
        else:
            membership = uow.session.get(m.ProfessionWorkflow, (int(binding.workflow_id), int(binding.namespace_id)))
            uow.session.delete(membership)
        uow.commit()
        before = {name: rows(uow, table) for name, table in m.Base.metadata.tables.items()}
        with pytest.raises(ValueError):
            ensure_single_task_catalog(uow)
        uow.rollback()
        assert {name: rows(uow, table) for name, table in m.Base.metadata.tables.items()} == before


def test_installation_rolls_back_partial_failure(database, monkeypatch):
    from project_workflow.infrastructure.db import single_task_catalog as installer

    original = installer._persist_mode
    calls = 0

    def failing(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ValueError("injected persistence failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(installer, "_persist_mode", failing)
    with pytest.raises(ValueError, match="injected"):
        with SAUnitOfWork(database) as uow:
            ensure_single_task_catalog(uow)
    with SAUnitOfWork(database) as uow:
        assert not uow.projects.list() and not uow.workflows.list()


def test_existing_router_authorizes_readback_and_rejects_drift(database, monkeypatch):
    with SAUnitOfWork(database) as uow:
        installation = ensure_single_task_catalog(uow)
    monkeypatch.setattr(runtime_api, "SAUnitOfWork", lambda: SAUnitOfWork(database))
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", "c" * 32)
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"analyst": "a" * 32}))
    config.get_settings.cache_clear()
    with TestClient(create_app()) as client:
        path = "/internal/runtime/profiles/single-task-v1/installation"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer " + "a" * 32}).status_code == 403
        headers = {"Authorization": "Bearer " + "c" * 32}
        response = client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json()["installation"] == installation.model_dump(mode="json", by_alias=True)
        binding = installation.bindings[0]
        binding_path = "/internal/runtime/profiles/single-task-v1/namespace-bindings/"
        response = client.get(binding_path + binding.namespace_id, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["binding"]["namespace_id"] == binding.namespace_id
        assert client.get(binding_path + "01", headers=headers).status_code == 422
        assert client.get(binding_path + "999999", headers=headers).status_code == 404
        with SAUnitOfWork(database) as uow:
            uow.projects.update(int(binding.namespace_id), {"launch_profile": "foreign"})
        assert client.get(path, headers=headers).status_code == 409


def test_version_one_cannot_bypass_runtime_or_human_step_guard(database):
    with SAUnitOfWork(database) as uow:
        installation = ensure_single_task_catalog(uow)
        binding = installation.bindings[3]
        project_id = int(binding.namespace_id)
        uow.commit()
        with pytest.raises(ConflictError, match="pending parent"):
            TaskService(uow)._reject_single_task_execution(project_id)
        with pytest.raises(ConflictError, match="pending parent"):
            supervisor.SupervisorEngine("RUN-7", uow=uow, project_id=project_id)
        assert not uow.tasks.list()
        uow.tasks.create({"project_id": project_id, "workflow_id": int(binding.workflow_id),
                          "mode_id": int(binding.modes[0].mode_id), "task_key": "RUN-7", "title": "Unbound",
                          "status": "active", "current_phase_id": int(binding.modes[0].phase_ids[0])})
        uow.commit()
        with pytest.raises(ConflictError, match="authenticated assigned"):
            supervisor.SupervisorEngine("RUN-7", uow=uow, project_id=project_id, create_if_missing=False)


def test_actual_catalog_hashes_and_cli_publication_semantics():
    from project_workflow.infrastructure.db.single_task_catalog import REFERENCES, load_profile

    catalog, manifest = load_profile()
    expected_catalog, expected_manifest = build_single_task_profile.render()
    assert (REFERENCES / "single_task_catalog_v1.json").read_bytes() == expected_catalog
    assert (REFERENCES / "single_task_manifest_v1.json").read_bytes() == expected_manifest
    assert manifest["proposal"] is False
    for workflow in catalog["workflows"]:
        role = workflow["role_key"]
        for mode in workflow["modes"]:
            terminal = mode["phases"][-1]["instructions"][-1]["description"]
            if role == "project_manager":
                assert "ONLY AFTER" in terminal and "confirmation receipt readback succeeds" in terminal
            else:
                for required in ("sdlc result propose", "sdlc result operation", "DOES NOT transition",
                                 "actual terminal", "schedulerComplete", "end the run", "lifecycle readback"):
                    assert required in terminal
                assert "fence, workflow_receipt, result, idempotency_key" in terminal


def test_pm_confirmation_precedes_final_report_in_actual_installed_phase(database):
    with SAUnitOfWork(database) as uow:
        installation = ensure_single_task_catalog(uow)
        binding = next(b for b in installation.bindings if b.role_key == "project_manager")
        phases = uow.phases.list(int(binding.workflow_id), mode_id=int(binding.modes[0].mode_id))
        assert len(phases) == 3
        for phase in phases[:2]:
            instructions = [i["description"] for i in uow.phase_instructions.list(phase.id)]
            assert "Stop at the returned next phase" in instructions[-1]
            assert "until an accepted complete=true" not in " ".join(instructions)
        phase = phases[-1]
        instructions = [i["description"] for i in uow.phase_instructions.list(phase.id)]
        assert len(instructions) == 5
        present, checkpoint, feedback, readback, report = instructions
        assert "FULL server-saved requirements document" in present
        assert "exact revision" in present and "content_hash" in present
        assert "PM Workflow NOT completed" in checkpoint
        assert "input_kind answer|feedback|confirmation" in checkpoint
        assert "existing answer-only" in checkpoint
        assert "same execution/assignment/cycle" in checkpoint
        assert "within the SAME execution" in feedback
        assert "Any document change invalidates earlier consent" in feedback
        assert "must not fabricate an answer ID" in feedback
        assert "existing real owner confirmation receipt" in feedback
        assert "sdlc confirmation read --task <task-uuid> --revision <confirmed-revision>" in readback
        assert "direct GET requirements/{revision}/confirmation" in readback
        assert "unavailable to the PM grant" in readback
        assert "until" in checkpoint and "Until" in readback
        assert "--report" not in " ".join(instructions[:-1])
        assert "ONLY AFTER" in report and "--report <report-text>" in report
        assert report.index("confirmation receipt readback succeeds") < report.index("--report")
        assert "Analyst reserve remains blocked" in report and "PM actual completion" in report
        assert "PM does not dispatch Analyst" in report
        assert "sdlc intent --task" not in " ".join(instructions)
        checks = uow.phase_checks.list(phase.id)
        evidence = uow.phase_evidence_requirements.list(phase.id)
        assert any("real authorized readback receipt" in row["description"] for row in checks)
        assert any("dependencies are satisfied" in row["description"] for row in checks)
        assert any("Actual owner confirmation receipt" in row["description"] for row in evidence)


def assignment_payload():
    return {
        "instruction_profile": "single-task-v1", "instruction_manifest_sha256": MANIFEST_SHA256,
        "task": "RUN-7", "role_key": "developer", "workflow_key": "single-task-v1:developer", "mode_key": "initial",
        "execution_scope": "delivery", "stage_key": "Development", "cycle_number": 0, "attempt_number": 1,
        "operation_key": "assignment-7", "business_task_ref": "11111111-1111-4111-8111-111111111111",
        "root_task_ref": "11111111-1111-4111-8111-111111111111",
        "assignment_ref": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "execution_ref": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "concrete_agent_ref": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "tracker_instance_ref": "tracker:one", "tracker_project_ref": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "task_revision": 1, "lease_ref": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        "lease_version": 1, "fencing_token": 1,
        "exact_input_refs": [], "expected_revision": 0, "expected_status": "missing",
    }


def test_profile_assignment_shape_omits_decomposition_and_enforces_task_root():
    payload = assignment_payload()
    request = SingleTaskAssignmentRequest.model_validate(payload)
    assert "decomposition_revision_ref" not in request.model_dump()
    for changes in ({"root_task_ref": "22222222-2222-4222-8222-222222222222"},
                    {"instruction_manifest_sha256": "0" * 64}, {"decomposition_revision_ref": "fake"},
                    {"workflow_key": "hermes-sdlc:developer"}, {"execution_scope": "aggregate"}):
        with pytest.raises(ValidationError):
            SingleTaskAssignmentRequest.model_validate({**payload, **changes})
    legacy = {k: v for k, v in payload.items() if not k.startswith("instruction_")}
    with pytest.raises(ValidationError):
        RuntimeAssignmentRequest.model_validate(legacy)


def test_profile_assign_bind_step_keep_existing_auth_and_fail_closed(database, monkeypatch):
    with SAUnitOfWork(database) as uow:
        ensure_single_task_catalog(uow)
    monkeypatch.setattr(config, "CATALOG_VARIANT", "single-task-v1")
    monkeypatch.setattr(runtime_api, "SAUnitOfWork", lambda: SAUnitOfWork(database))
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"developer": "w" * 32}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"developer": "r" * 32}))
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_SCOPE_SECRET", "s" * 40)
    config.get_settings.cache_clear()
    with TestClient(create_app()) as client:
        assignment = assignment_payload()
        base = "/internal/runtime/"
        writer = {"Authorization": "Bearer " + "w" * 32}
        runner = {"Authorization": "Bearer " + "r" * 32}
        assert client.post(base + "assign", json=assignment).status_code == 401
        assert client.post(base + "assign", json=assignment, headers=runner).status_code == 403
        response = client.post(base + "assign", json=assignment, headers=writer)
        assert response.status_code == 200, response.text
        bind = {"task": "RUN-7", "bind_operation_key": "bind-7", "assignment_operation_key": "assignment-7",
                "assignment_revision": 1, "assignment_ref": assignment["assignment_ref"], "binding_ref": "bind-7",
                "hermes_run_ref": "run-7", "mode_key": "initial", "cycle_number": 0, "attempt_number": 1,
                "expected_binding_state": "unbound", "instruction_profile": "single-task-v1",
                "instruction_manifest_sha256": MANIFEST_SHA256,
                "session_run_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
                "concrete_agent_ref": assignment["concrete_agent_ref"]}
        assert client.post(base + "bind", json=bind, headers=runner).status_code == 403
        response = client.post(base + "bind", json=bind, headers=writer)
        assert response.status_code == 200, response.text
        bound = response.json()
        step = {"task": "RUN-7", "step_operation_key": "step-7", "assignment_revision": 1,
                "assignment_ref": assignment["assignment_ref"], "binding_ref": "bind-7", "hermes_run_ref": "run-7",
                "mode_key": "initial", "cycle_number": 0, "attempt_number": 1,
                "expected_phase_code": "DV-INITIAL-01", "expected_status": "active",
                "instruction_profile": "single-task-v1", "instruction_manifest_sha256": MANIFEST_SHA256,
                "session_run_id": bind["session_run_id"],
                "single_task_context_sha256": bound["result"]["single_task_context_sha256"]}
        assert client.post(base + "step", json=step, headers=writer).status_code == 403
        response = client.post(base + "step", json=step, headers=runner)
        assert response.status_code == 403
        response = client.post(base + "step", json=step,
                               headers={**runner, "X-Workflow-Execution-Token": bound["execution_token"]})
        assert response.status_code == 200, response.text
    with SAUnitOfWork(database) as uow:
        assert len(uow.tasks.list()) == 1
        assignment = uow.tasks.get_assignment_by_operation_key("assignment-7")
        assert assignment.work_item_ref is assignment.queue_item_ref is assignment.decomposition_revision_ref is None
