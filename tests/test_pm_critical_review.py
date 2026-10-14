"""A new trusted PM execution of one Tracker task retains its completed predecessor."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text

from project_workflow import config
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.pm_execution import PMIdentity, RuntimeObservation
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.session import ensure_migrated, reset_engine, run_alembic_command
from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from tests import test_single_task_runtime as runtime_fixture
from tests.test_single_task_pm_terminal import CURRENT_RUN, READBACK, complete
from tests.test_single_task_runtime import API, PM, PROFILE, RUNNER, WRITER
from tests.test_single_task_runtime import bridge as bridge

REVIEW_RUN = "22222222-2222-4222-8222-222222222201"


def review_assignment():
    return {**runtime_fixture.assignment_payload(), "task": "SDLC-8", "operation_key": "review:assignment",
            "role_key": "project_manager", "workflow_key": "single-task-v1:project_manager",
            "mode_key": "draft", "stage_key": "Draft", "execution_scope": "business",
            "assignment_ref": "22222222-2222-4222-8222-222222222202",
            "execution_ref": "22222222-2222-4222-8222-222222222203",
            "lease_ref": "22222222-2222-4222-8222-222222222204", "task_revision": 8,
            "exact_input_refs": [{"kind": "critical_blocker", "ref": "22222222-2222-4222-8222-222222222205",
                                  "hash": "c" * 64}]}


def review_bind(client, assignment):
    binding = {**PROFILE, "task": assignment["task"], "bind_operation_key": "review:runtime-bind",
               "assignment_operation_key": assignment["operation_key"], "assignment_revision": 1,
               "assignment_ref": assignment["assignment_ref"], "binding_ref": "binding:review",
               "hermes_run_ref": "run:review", "mode_key": "draft", "cycle_number": 0, "attempt_number": 1,
               "expected_binding_state": "unbound", "concrete_agent_ref": assignment["concrete_agent_ref"],
               "session_run_id": REVIEW_RUN}
    bound = client.post(API + "bind", json=binding, headers=WRITER)
    assert bound.status_code == 200, bound.text
    identity = {key: assignment[key] for key in (
        "task", "execution_ref", "tracker_instance_ref", "tracker_project_ref", "assignment_ref",
    )}
    identity.update(task_ref=assignment["business_task_ref"], root_ref=assignment["root_task_ref"],
                    agent_ref=assignment["concrete_agent_ref"], assignment_operation_key=assignment["operation_key"],
                    assignment_revision=1)
    command = {**PROFILE, **identity, "operation_key": "review:pm-bind", "expected_version": 0,
               "binding_ref": binding["binding_ref"], "hermes_run_ref": binding["hermes_run_ref"],
               "session_run_id": REVIEW_RUN}
    observation = RuntimeObservation.model_validate({
        **identity, "observation_ref": "observed:review", "status": "running",
        "binding_ref": binding["binding_ref"], "hermes_run_ref": binding["hermes_run_ref"],
        "session_run_id": REVIEW_RUN, "fence": 1, "dispatch_operation_key": command["operation_key"],
    })
    return binding, command, observation


@pytest.mark.parametrize("native_status", ["completed", "failed", "cancelled", "stopped"])
def test_new_pm_review_execution_retains_original_terminal_history(
    bridge, monkeypatch, supervisor_llm, native_status,
):
    final, lookup, old_headers, _, _, _ = complete(bridge, monkeypatch, supervisor_llm)
    old_receipt = bridge.post(READBACK, json=lookup, headers=old_headers).json()
    history_params = {**PROFILE, "task": final["task"], "session_run_id": CURRENT_RUN}
    old_history = bridge.get(API + "history", params=history_params, headers=old_headers).json()
    original_observe = pm_readback.observe_run
    terminal = original_observe(CURRENT_RUN).model_copy(update={"status": native_status})
    monkeypatch.setattr(pm_readback, "observe_run",
                        lambda run: terminal if run == CURRENT_RUN else original_observe(run))
    assignment = review_assignment()
    assigned = bridge.post(API + "assign", json=assignment, headers=WRITER)
    assert assigned.status_code == 200, assigned.text
    assert bridge.post(API + "assign", json=assignment, headers=WRITER).json() == assigned.json()
    replacement = {**assignment, "task": final["task"], "operation_key": "review:forbidden-replacement",
                   "expected_revision": 1, "expected_status": "done", "attempt_number": 2}
    assert bridge.post(API + "assign", json=replacement, headers=WRITER).status_code == 409
    assert bridge.post(API + "assign", json=assignment, headers=RUNNER).status_code == 403
    binding, command, observation = review_bind(bridge, assignment)
    monkeypatch.setattr(pm_readback, "observe_run", lambda run: observation if run == REVIEW_RUN
                        else terminal.model_copy(update={"status": "running"}))
    assert bridge.post(PM + "bind", json=command, headers=WRITER).status_code == 409
    with SAUnitOfWork() as uow:
        assert len(list(uow.session.scalars(select(m.PMExecution)))) == 1
    monkeypatch.setattr(pm_readback, "observe_run", lambda run: observation if run == REVIEW_RUN else terminal)
    enrolled = bridge.post(PM + "bind", json=command, headers=WRITER)
    assert enrolled.status_code == 200, enrolled.text
    monkeypatch.setattr(pm_readback, "observe_run", lambda _run: pytest.fail("Original operation replay is read-only"))
    assert bridge.post(PM + "bind", json=command, headers=WRITER).json() == enrolled.json()
    replayed = bridge.post(API + "assign", json=assignment, headers=WRITER).json()["result"]
    assert replayed["assignment_ref"] == assigned.json()["result"]["assignment_ref"]
    assert replayed["binding_state"] == "bound"
    headers = {**RUNNER, "X-Workflow-Execution-Token": enrolled.json()["execution_token"]}
    step = {**binding, "step_operation_key": "review:first-step", "expected_phase_code": "PM-DRAFT-01",
            "expected_status": "active",
            "single_task_context_sha256": enrolled.json()["result"]["single_task_context_sha256"]}
    for key in ("bind_operation_key", "assignment_operation_key", "concrete_agent_ref", "expected_binding_state"):
        step.pop(key)
    first = bridge.post(API + "step", json=step, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["result"]["phase_code"] == "PM-DRAFT-01"
    assert bridge.post(API + "step", json=step, headers=old_headers).status_code == 403
    with TestClient(create_app()) as restarted:
        assert restarted.post(READBACK, json=lookup, headers=old_headers).json() == old_receipt
        assert restarted.get(API + "history", params=history_params, headers=old_headers).json() == old_history
        body = {**PROFILE, **{k: command[k] for k in PMIdentity.model_fields}}
        assert restarted.post(PM + "readback", json=body, headers=headers).status_code == 200
    with SAUnitOfWork() as uow:
        executions = list(uow.session.scalars(select(m.PMExecution)))
        assert len(executions) == 2
        assert len({e.task_id for e in executions}) == len({e.assignment_id for e in executions}) == 2
        assert len({e.task_ref for e in executions}) == len({e.agent_ref for e in executions}) == 1
        old = next(e for e in executions if e.execution_ref != assignment["execution_ref"])
        assert json.loads(old.identity_json)["task"] == final["task"]
        assert old.session_run_id == CURRENT_RUN and old.version == 4 and old.fence == 2


@pytest.mark.parametrize("failure", ["running", "foreign_fence", "unknown", "unsealed", "pending"])
def test_pm_review_refuses_unproven_predecessor_before_assignment(bridge, monkeypatch, supervisor_llm, failure):
    final, _, _, _, _, _ = complete(bridge, monkeypatch, supervisor_llm)
    terminal = pm_readback.observe_run(CURRENT_RUN).model_copy(update={"status": "completed"})
    if failure == "running":
        terminal = terminal.model_copy(update={"status": failure})
    elif failure == "foreign_fence":
        terminal = terminal.model_copy(update={"fence": 9})
    elif failure in {"unsealed", "pending"}:
        with SAUnitOfWork() as uow:
            if failure == "unsealed":
                history = uow.step_history.get_by_step_operation_key(final["step_operation_key"])
                row = uow.session.get(m.TaskStepHistoryEntry, history.id)
                response = json.loads(row.supervisor_response)
                response.pop("workflow_receipt")
                row.supervisor_response = json.dumps(response)
            else:
                execution = uow.session.scalar(select(m.PMExecution))
                execution.state = "resume_pending"
            uow.commit()

    def observe(_run):
        if failure == "unknown":
            raise pm_readback.ReadbackUnavailable("Synthetic unavailable readback")
        return terminal

    monkeypatch.setattr(pm_readback, "observe_run", observe)
    result = bridge.post(API + "assign", json=review_assignment(), headers=WRITER)
    assert result.status_code == 409, result.text
    with SAUnitOfWork() as uow:
        project = uow.projects.get_by_cli_command("workflow-single-task-project-manager")
        assert uow.tasks.get_by_key("SDLC-8", project_id=project.id) is None
        assert uow.tasks.get_assignment_by_operation_key("review:assignment") is None
        assert len(list(uow.session.scalars(select(m.PMExecution)))) == 1


def test_pm_review_keeps_legacy_enrollment_closed(bridge, monkeypatch, supervisor_llm):
    complete(bridge, monkeypatch, supervisor_llm)
    from project_workflow.application.pm_execution import PMExecutionService

    with SAUnitOfWork() as uow:
        execution = uow.session.scalar(select(m.PMExecution))
        with pytest.raises(ConflictError, match="closed single-task"):
            PMExecutionService(uow).assert_previous_terminal(
                tracker_instance_ref=execution.tracker_instance_ref, tracker_project_ref=execution.tracker_project_ref,
                task_ref=execution.task_ref, agent_ref=execution.agent_ref, single_task=False,
            )


def test_pm_review_migration_preserves_populated_execution_and_history(
    bridge, monkeypatch, supervisor_llm, tmp_path,
):
    url = f"sqlite:///{tmp_path / 'retained-pm.db'}"
    engine = create_engine(url)
    try:
        run_alembic_command("upgrade", engine, "0015_single_task_assignments")
        monkeypatch.setenv("DATABASE_URL", url)
        config.get_settings.cache_clear()
        reset_engine()
        with SAUnitOfWork() as uow:
            ensure_single_task_catalog(uow)
        complete(bridge, monkeypatch, supervisor_llm)
        tables = tuple(m.Base.metadata.tables)
        with engine.connect() as connection:
            frozen = {name: connection.execute(select(m.Base.metadata.tables[name])).mappings().all()
                      for name in tables}
        assert "uq_pm_task_agent" in {u["name"] for u in inspect(engine).get_unique_constraints("pm_executions")}
        ensure_migrated(engine)
        ensure_migrated(engine)
        assert "uq_pm_task_agent" not in {u["name"] for u in inspect(engine).get_unique_constraints("pm_executions")}
        assert "ix_pm_task_agent" in {i["name"] for i in inspect(engine).get_indexes("pm_executions")}
        with engine.connect() as connection:
            assert not connection.execute(text("PRAGMA foreign_key_check")).all()
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            for name in tables:
                assert connection.execute(select(m.Base.metadata.tables[name])).mappings().all() == frozen[name], name
        with pytest.raises(RuntimeError, match="preserved"):
            run_alembic_command("downgrade", engine, "0015_single_task_assignments")
    finally:
        engine.dispose()
