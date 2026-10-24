"""Isolated real PM ledgers and authenticated routes; synthetic native readback."""

import importlib
import json

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import select

from project_workflow.domain.pm_execution import PMResumeRetryResponse
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from tests.test_single_task_runtime import API, PM, PROFILE, RUNNER, SESSION, WRITER, enroll_pm
from tests.test_single_task_runtime import bridge as bridge

FAILED = "11111111-1111-4111-8111-111111111901"
TARGET = "11111111-1111-4111-8111-111111111902"
LATER = "11111111-1111-4111-8111-111111111903"
CHECKPOINT = "11111111-1111-4111-8111-111111111904"


def stored():
    with SAUnitOfWork() as uow:
        return {model.__tablename__: [
            {column.name: getattr(row, column.name) for column in model.__table__.columns}
            for row in uow.session.scalars(select(model).order_by(*model.__table__.primary_key.columns))
        ] for model in (m.Task, m.TaskRuntimeAssignment, m.TaskStepHistoryEntry,
                        m.PMExecution, m.PMRun, m.PMOperation)}


@pytest.fixture
def pending(bridge, monkeypatch):
    identity, observations, headers, step = enroll_pm(bridge, monkeypatch)
    first = bridge.post(API + "step", json=step, headers=headers)
    assert first.status_code == 200, first.text
    checkpoint = {**PROFILE, **identity, "operation_key": "checkpoint:source", "expected_version": 1,
                  "expected_fence": 1, "session_run_id": SESSION, "binding_ref": step["binding_ref"],
                  "hermes_run_ref": step["hermes_run_ref"], "checkpoint_ref": CHECKPOINT,
                  "requirements_revision": None, "requirements_sha256": None}
    assert bridge.post(PM + "checkpoint", json=checkpoint, headers=headers).status_code == 200
    observations[SESSION].update(status="completed", checkpoint_ref=CHECKPOINT)
    saved_input = {"input": {"input_kind": "feedback", "input_id": FAILED},
                   "input_receipt": {"reference": "https://tracker.fixture.test/feedback/" + FAILED,
                                     "sha256": "b" * 64}}
    resume = {**checkpoint, **saved_input, "operation_key": "resume:original", "expected_version": 2,
              "new_session_run_id": FAILED}
    response = bridge.post(PM + "resume", json=resume, headers=WRITER)
    assert response.status_code == 200, response.text
    observations[FAILED] = {**identity, "observation_ref": "observed:failed", "status": "completed",
                            "session_run_id": FAILED, "binding_ref": "binding:failed",
                            "hermes_run_ref": "run:failed", "fence": 2,
                            "dispatch_operation_key": resume["operation_key"], "checkpoint_ref": None}
    command = {**PROFILE, **identity, **saved_input, "contract_version": 1,
               "operation_key": "resume-retry:1", "expected_version": 3, "expected_fence": 2,
               "session_run_id": SESSION, "binding_ref": step["binding_ref"],
               "hermes_run_ref": step["hermes_run_ref"], "checkpoint_ref": CHECKPOINT,
               "prior_resume_operation_key": resume["operation_key"], "failed_session_run_id": FAILED,
               "failed_hermes_run_ref": "run:failed", "failed_binding_ref": "binding:failed",
               "new_session_run_id": TARGET, "new_binding_ref": "binding:target"}
    return bridge, command, observations, step, response.json()


def test_retry_keeps_source_fence_and_checkpoint_with_exact_replay_and_readback(pending, monkeypatch):
    client, command, observations, _, original_resume = pending
    before = stored()
    response = client.post(PM + "resume-retry", json=command, headers=WRITER)
    assert response.status_code == 200, response.text
    wire = response.json()
    PMResumeRetryResponse.model_validate(wire)
    assert set(wire) == {"ok", "result"} and "execution_token" not in wire
    result = wire["result"]
    assert result["request_sha256"] == payload_sha256(command)
    assert result["input"] == command["input"] and result["input_receipt"] == command["input_receipt"]
    assert result["source"] == {"session_run_id": SESSION, "binding_ref": command["binding_ref"],
                                "hermes_run_ref": command["hermes_run_ref"], "fence": 1,
                                "checkpoint_ref": CHECKPOINT}
    assert result["failed_terminal"] == observations[FAILED]
    snapshot = result["pending"]
    assert (snapshot["state"], snapshot["version"], snapshot["fence"]) == ("resume_pending", 4, 3)
    assert snapshot["session_run_id"] == SESSION and snapshot["resume_session_run_id"] == TARGET
    assert snapshot["terminal_readback"] == observations[SESSION]
    assert not snapshot["workflow_step_allowed"] and not snapshot["resume_delivered"]
    assert snapshot["single_task_context_sha256"] != original_resume["result"]["single_task_context_sha256"]
    changed = {"version", "fence", "resume_operation_key", "resume_session_run_id", "single_task_context_sha256"}
    assert {k: v for k, v in snapshot.items() if k not in changed} == {
        k: v for k, v in original_resume["result"].items() if k not in changed
    }
    after = stored()
    for name in ["tasks", "task_runtime_assignments", "task_step_history"]:
        assert before[name] == after[name]
    assert all(row in after["pm_runs"] for row in before["pm_runs"])
    assert all(row in after["pm_operations"] for row in before["pm_operations"])
    assert len(after["pm_runs"]) == len(before["pm_runs"]) + 1
    assert len(after["pm_operations"]) == len(before["pm_operations"]) + 1
    failed = next(row for row in after["pm_runs"] if row["session_run_id"] == FAILED)
    assert json.loads(failed["observation_json"]) == json.loads(failed["terminal_json"]) == observations[FAILED]
    monkeypatch.setattr(pm_readback, "observe_run", lambda *_: pytest.fail("No native probe on retained replay"))
    with TestClient(create_app()) as restarted:
        assert restarted.post(PM + "resume-retry", json=command, headers=WRITER).json() == wire
        readback = restarted.post(PM + "readback", headers=WRITER, json={
            **PROFILE, **snapshot["identity"], "operation_key": command["operation_key"],
        })
        assert readback.status_code == 200, readback.text
        assert readback.json()["result"]["operation"] == {
            "kind": "resume_retry", "operation_key": command["operation_key"],
            "request_sha256": result["request_sha256"], "result": result,
        }
        old = restarted.post(PM + "readback", headers=WRITER, json={
            **PROFILE, **snapshot["identity"], "operation_key": command["prior_resume_operation_key"],
        }).json()
        assert old["result"]["operation"]["result"] == original_resume["result"]
    assert stored() == after


@pytest.mark.parametrize("field,value", [
    ("expected_version", 2), ("expected_fence", 1), ("prior_resume_operation_key", "foreign"),
    ("checkpoint_ref", "foreign"), ("hermes_run_ref", "foreign"), ("binding_ref", "foreign"),
    ("failed_session_run_id", LATER), ("failed_hermes_run_ref", "foreign"), ("failed_binding_ref", "foreign"),
    ("agent_ref", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"), ("assignment_revision", 2),
    ("input", {"input_kind": "feedback", "input_id": LATER}),
    ("input_receipt", {"reference": "foreign", "sha256": "c" * 64}),
    ("instruction_manifest_sha256", "d" * 64),
])
def test_retry_rejects_changed_custody_without_writes(pending, field, value):
    client, command, _, _, _ = pending
    before = stored()
    response = client.post(PM + "resume-retry", json={**command, field: value}, headers=WRITER)
    assert response.status_code in {409, 503}, response.text
    assert stored() == before


@pytest.mark.parametrize("field,value", [
    ("status", "running"), ("fence", 1), ("checkpoint_ref", CHECKPOINT),
    ("dispatch_operation_key", "foreign"), ("execution_ref", "foreign"),
])
def test_retry_rejects_nonterminal_or_foreign_trusted_readback(pending, field, value):
    client, command, observations, _, _ = pending
    observations[FAILED][field] = value
    before = stored()
    response = client.post(PM + "resume-retry", json=command, headers=WRITER)
    assert response.status_code == 409, response.text
    assert stored() == before


def test_retry_unknown_callback_and_missing_capability_do_not_write(pending, monkeypatch):
    from project_workflow import config

    client, command, _, _, _ = pending
    before = stored()

    def unknown(*_):
        raise pm_readback.ReadbackUnavailable("unknown")

    monkeypatch.setattr(pm_readback, "observe_run", unknown)
    assert client.post(PM + "resume-retry", json=command, headers=WRITER).status_code == 503
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_TOKEN", "")
    config.get_settings.cache_clear()
    assert client.post(PM + "resume-retry", json=command, headers=WRITER).status_code == 503
    assert stored() == before


@pytest.mark.parametrize("headers,status", [({}, 401), (RUNNER, 403),
                                            ({"Authorization": "Bearer human"}, 401)])
def test_retry_requires_assignment_credential(pending, headers, status):
    client, command, _, _, _ = pending
    before = stored()
    assert client.post(PM + "resume-retry", json=command, headers=headers).status_code == status
    assert stored() == before


def test_retry_rejects_unknown_fields_and_duplicate_run_ids(pending):
    client, command, _, _, _ = pending
    before = stored()
    for change in [{"prompt": "not allowed"}, {"contract_version": 2},
                   {"new_session_run_id": FAILED}, {"new_binding_ref": command["binding_ref"]}]:
        assert client.post(PM + "resume-retry", json={**command, **change}, headers=WRITER).status_code == 422
    assert stored() == before


def test_retry_does_not_replace_a_rebound_or_already_retried_target(pending):
    client, command, observations, _, _ = pending
    accepted = client.post(PM + "resume-retry", json=command, headers=WRITER)
    assert accepted.status_code == 200, accepted.text
    before = stored()
    assert client.post(PM + "resume-retry", json={**command, "new_session_run_id": LATER},
                       headers=WRITER).status_code == 409
    assert client.post(PM + "resume-retry", json={**command, "operation_key": "other-key"},
                       headers=WRITER).status_code == 409
    assert stored() == before
    observations[TARGET] = {**observations[FAILED], "observation_ref": "observed:target", "status": "running",
                            "session_run_id": TARGET, "binding_ref": command["new_binding_ref"],
                            "hermes_run_ref": "run:target", "fence": 3,
                            "dispatch_operation_key": command["operation_key"], "checkpoint_ref": CHECKPOINT}
    rebind = {key: value for key, value in command.items() if key in {
        *command_identity(command), "instruction_profile", "instruction_manifest_sha256",
        "binding_ref", "hermes_run_ref", "session_run_id", "checkpoint_ref", "new_binding_ref", "new_session_run_id",
    }}
    rebind.update(operation_key="rebind:target", expected_version=4, expected_fence=3,
                  resume_operation_key=command["operation_key"], new_hermes_run_ref="run:target")
    bound = client.post(PM + "rebind", json=rebind, headers=WRITER)
    assert bound.status_code == 200, bound.text
    assert bound.json()["result"]["state"] == "active" and bound.json()["result"]["fence"] == 3
    assert client.post(PM + "resume-retry", json={**command, "operation_key": "after-rebind"},
                       headers=WRITER).status_code == 409


def command_identity(command):
    from project_workflow.domain.pm_execution import PMIdentity

    return {key: command[key] for key in PMIdentity.model_fields}


def test_second_terminal_retry_still_uses_original_source_fence_one(pending):
    client, command, observations, _, _ = pending
    assert client.post(PM + "resume-retry", json=command, headers=WRITER).status_code == 200
    observations[TARGET] = {**observations[FAILED], "session_run_id": TARGET, "hermes_run_ref": "run:target",
                            "binding_ref": command["new_binding_ref"], "fence": 3,
                            "dispatch_operation_key": command["operation_key"]}
    next_command = {**command, "operation_key": "resume-retry:2", "expected_version": 4, "expected_fence": 3,
                    "prior_resume_operation_key": command["operation_key"], "failed_session_run_id": TARGET,
                    "failed_hermes_run_ref": "run:target", "failed_binding_ref": command["new_binding_ref"],
                    "new_session_run_id": LATER, "new_binding_ref": "binding:later"}
    result = client.post(PM + "resume-retry", json=next_command, headers=WRITER)
    assert result.status_code == 200, result.text
    assert result.json()["result"]["source"]["fence"] == 1
    assert result.json()["result"]["failed_terminal"]["fence"] == 3
    assert result.json()["result"]["pending"]["fence"] == 4


def test_bootstrap_canonical_identity_survives_terminal_resume_retry(bridge, monkeypatch):
    from project_workflow.domain.pm_execution import RuntimeObservation
    from tests.test_pm_bootstrap_retry import NEXT, enroll_retry, prepare_pending

    bootstrap = prepare_pending(bridge, monkeypatch)
    identity, native, _, step, headers = enroll_retry(bootstrap, monkeypatch)
    checkpoint = {**PROFILE, **identity, "operation_key": "checkpoint:bootstrap-source", "expected_version": 1,
                  "expected_fence": 1, "session_run_id": NEXT, "binding_ref": step["binding_ref"],
                  "hermes_run_ref": step["hermes_run_ref"], "checkpoint_ref": CHECKPOINT,
                  "requirements_revision": None, "requirements_sha256": None}
    assert bridge.post(PM + "checkpoint", json=checkpoint, headers=headers).status_code == 200
    source = native.model_copy(update={"status": "completed", "checkpoint_ref": CHECKPOINT})
    observations = {NEXT: source}
    monkeypatch.setattr(pm_readback, "observe_run", lambda run: observations[run])
    saved_input = {"input": {"input_kind": "feedback", "input_id": FAILED},
                   "input_receipt": {"reference": "tracker:bootstrap-feedback", "sha256": "b" * 64}}
    resumed = bridge.post(PM + "resume", headers=WRITER, json={
        **checkpoint, **saved_input, "operation_key": "resume:bootstrap", "expected_version": 2,
        "new_session_run_id": FAILED,
    })
    assert resumed.status_code == 200, resumed.text
    observations[FAILED] = RuntimeObservation.model_validate({
        **identity, "observation_ref": "observed:failed", "status": "completed", "session_run_id": FAILED,
        "binding_ref": "binding:failed", "hermes_run_ref": "run:failed", "fence": 2,
        "dispatch_operation_key": "resume:bootstrap", "checkpoint_ref": None,
    })
    command = {**PROFILE, **identity, **saved_input, "contract_version": 1,
               "operation_key": "resume-retry:bootstrap", "expected_version": 3, "expected_fence": 2,
               "session_run_id": NEXT, "binding_ref": step["binding_ref"], "hermes_run_ref": step["hermes_run_ref"],
               "checkpoint_ref": CHECKPOINT, "prior_resume_operation_key": "resume:bootstrap",
               "failed_session_run_id": FAILED, "failed_binding_ref": "binding:failed",
               "failed_hermes_run_ref": "run:failed", "new_session_run_id": TARGET,
               "new_binding_ref": "binding:target"}
    before = stored()
    response = bridge.post(PM + "resume-retry", headers=WRITER, json=command)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert identity["assignment_revision"] == 1
    assert result["pending"]["identity"] == identity
    assert result["source"]["session_run_id"] == NEXT and result["source"]["fence"] == 1
    assert result["failed_terminal"]["checkpoint_ref"] is None
    assert result["pending"]["fence"] == 3
    after = stored()
    assert before["task_runtime_assignments"] == after["task_runtime_assignments"]
    assert all(row in after["pm_runs"] for row in before["pm_runs"])


@pytest.mark.parametrize("headers,advertised", [(WRITER, True), (RUNNER, False)])
def test_retry_capability_is_only_for_configured_single_task_assignment(pending, monkeypatch, tmp_path,
                                                                     headers, advertised):
    from project_workflow import config
    from project_workflow.infrastructure.db import session as db_session
    from tests.test_runtime_capabilities import _install_manifest, _valid_manifest

    client, _, _, _, _ = pending
    _install_manifest(monkeypatch, tmp_path, _valid_manifest())
    monkeypatch.setattr(db_session, "schema_is_ready", lambda _: True)
    response = client.get(API + "capabilities", params={"instruction_profile": "single-task-v1"}, headers=headers)
    assert response.status_code == 200, response.text
    assert ("resume-retry" in response.json()["pm_continuation"]["commands"]) == advertised
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_TOKEN", "")
    config.get_settings.cache_clear()
    response = client.get(API + "capabilities", params={"instruction_profile": "single-task-v1"}, headers=headers)
    assert response.status_code == 200, response.text
    assert "pm_continuation" not in response.json()


def test_migration_only_extends_kind_and_refuses_to_drop_retained_retry(tmp_path, monkeypatch):
    migration = importlib.import_module(
        "project_workflow.infrastructure.db.migrations.versions.0019_pm_terminal_resume_retry"
    )
    engine = sa.create_engine("sqlite:///" + str(tmp_path / "kind-test.db"))
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE pm_operations (operation_key TEXT PRIMARY KEY, kind TEXT NOT NULL, "
            "CONSTRAINT ck_pm_operation_kind CHECK(kind IN ('bind','checkpoint','resume','rebind')))"
        )
        connection.exec_driver_sql("INSERT INTO pm_operations VALUES ('old:resume','resume')")
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        assert connection.exec_driver_sql("SELECT * FROM pm_operations").all() == [("old:resume", "resume")]
        connection.exec_driver_sql("INSERT INTO pm_operations VALUES ('new:retry','resume_retry')")
        with pytest.raises(RuntimeError, match="prevent downgrade"):
            migration.downgrade()
        assert connection.exec_driver_sql("SELECT count(*) FROM pm_operations").scalar() == 2
    engine.dispose()
