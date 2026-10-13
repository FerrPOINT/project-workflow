"""Continuation failures and Supervisor report persistence across run changes."""

import pytest

from tests.test_pm_execution import (
    ADAPTER,
    BASE,
    NEW_RUN,
    OLD_RUN,
    OTHER_AGENT_REF,
    RUNTIME,
    bind_pm,
    prepare_pm,
    waiting_pm,
)
from tests.test_pm_execution import test_wait_resume_new_run_survives_sessions_and_replays as run_continuation
from tests.test_runtime_api import _step_payload


@pytest.fixture
def pm(monkeypatch):
    yield from prepare_pm(monkeypatch)


def test_resumed_supervisor_report_is_persistent_and_replayable(pm, supervisor_llm):
    run_continuation(pm)
    client = pm[0]
    current = client.post(BASE + "/readback", headers=ADAPTER, json=pm[1]).json()
    runtime = {**RUNTIME, "X-Workflow-Execution-Token": current["execution_token"]}
    supervisor_llm("PASS")
    payload = {
        **_step_payload(pm[4]), "report": "Verified work for the resumed assignment",
        "session_run_id": NEW_RUN, "binding_ref": "binding:new", "hermes_run_ref": "run:new",
        "step_operation_key": "step:resumed-report",
    }
    response = client.post("/internal/runtime/step", headers=runtime, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["status"] == "done"
    assert client.post("/internal/runtime/step", headers=runtime, json=payload).json() == response.json()
    read = client.post(BASE + "/readback", headers=ADAPTER, json=pm[1])
    assert read.json()["result"]["workflow_step_allowed"] is False
    assert client.get("/internal/runtime/history", headers=RUNTIME, params={"task": "PM-1"}).status_code == 403
    history = client.get("/internal/runtime/history", headers=runtime,
                         params={"task": "PM-1", "session_run_id": NEW_RUN})
    assert history.status_code == 200
    assert history.json()["result"]["records"][0]["hermes_run_ref"] == "run:new"


@pytest.mark.parametrize("field,value", [
    ("new_session_run_id", OLD_RUN), ("resume_operation_key", "wrong"), ("checkpoint_ref", "wrong"),
    ("expected_version", 2), ("expected_fence", 1),
])
def test_pending_reservation_cannot_change_target_or_cursor(pm, field, value):
    client, _, checkpoint, resume, observations, _ = waiting_pm(pm)
    observations[OLD_RUN]["status"] = "stopped"
    assert client.post(BASE + "/resume", headers=ADAPTER, json=resume).status_code == 200
    rebind = {
        **pm[1], "operation_key": "rebind:negative", "expected_version": 3, "expected_fence": 2,
        "session_run_id": OLD_RUN, "binding_ref": resume["binding_ref"], "hermes_run_ref": resume["hermes_run_ref"],
        "checkpoint_ref": checkpoint["checkpoint_ref"], "resume_operation_key": "resume:1",
        "new_session_run_id": NEW_RUN, "new_binding_ref": "binding:new", "new_hermes_run_ref": "run:new",
    }
    assert client.post(BASE + "/rebind", headers=ADAPTER, json={**rebind, field: value}).status_code == 409
    another_resume = {**resume, "operation_key": "another-resume"}
    assert client.post(BASE + "/resume", headers=ADAPTER, json=another_resume).status_code == 409


def test_lost_rebind_acceptance_keeps_same_reserved_uuid(pm, monkeypatch):
    from project_workflow.infrastructure import pm_readback

    client, _, checkpoint, resume, observations, _ = waiting_pm(pm)
    observations[OLD_RUN]["status"] = "stopped"
    assert client.post(BASE + "/resume", headers=ADAPTER, json=resume).status_code == 200
    rebind = {
        **pm[1], "operation_key": "rebind:unknown", "expected_version": 3, "expected_fence": 2,
        "session_run_id": OLD_RUN, "binding_ref": resume["binding_ref"], "hermes_run_ref": resume["hermes_run_ref"],
        "checkpoint_ref": checkpoint["checkpoint_ref"], "resume_operation_key": "resume:1",
        "new_session_run_id": NEW_RUN, "new_binding_ref": "binding:new", "new_hermes_run_ref": "run:new",
    }

    def unavailable(_run_id):
        raise pm_readback.ReadbackUnavailable("probe failed")

    monkeypatch.setattr(pm_readback, "observe_run", unavailable)
    assert client.post(BASE + "/rebind", headers=ADAPTER, json=rebind).status_code == 503
    assert client.post(BASE + "/rebind", headers=ADAPTER, json={
        **rebind, "new_session_run_id": "33333333-3333-4333-8333-333333333333",
    }).status_code == 409
    read = client.post(BASE + "/readback", headers=ADAPTER, json={**pm[1], "operation_key": "rebind:unknown"})
    assert read.json()["result"]["state"] == "resume_pending"
    assert read.json()["result"]["resume_session_run_id"] == NEW_RUN
    assert read.json()["result"]["operation"] is None


def test_non_ascii_or_missing_execution_token_fails_closed(pm):
    from project_workflow.interfaces.ui.routes.pm_api import scope_matches

    for token in (None, "\u00ff"):
        assert not scope_matches(pm[1], pm[2]["hermes_run_ref"], pm[2]["binding_ref"], 1, OLD_RUN, token)


def test_initial_binding_requires_live_concrete_agent_and_unique_execution(pm):
    client, identity, command, observations, _ = pm
    assert client.post(BASE + "/bind", headers=RUNTIME, json=command).status_code == 403
    assert client.post(BASE + "/bind", headers=ADAPTER,
                       json={**command, "agent_ref": OTHER_AGENT_REF}).status_code == 409
    observations[OLD_RUN]["status"] = "completed"
    assert client.post(BASE + "/bind", headers=ADAPTER, json=command).status_code == 409
    observations[OLD_RUN]["status"] = "running"
    bind_pm(pm)
    assert client.post(BASE + "/bind", headers=ADAPTER,
                       json={**command, "operation_key": "another-bind"}).status_code == 409
    assert client.post(BASE + "/readback", headers=ADAPTER,
                       json={**identity, "tracker_instance_ref": "foreign"}).status_code == 409


@pytest.mark.parametrize("field,value,status", [
    ("task", "PM-404", 404), ("execution_ref", "missing", 404),
    ("tracker_project_ref", "foreign", 409),
])
def test_readback_requires_exact_persisted_identity(pm, field, value, status):
    bind_pm(pm)
    assert pm[0].post(BASE + "/readback", headers=ADAPTER,
                      json={**pm[1], field: value}).status_code == status


def test_runtime_readback_and_history_require_current_run_scope(pm):
    client, runtime, _, _, _ = bind_pm(pm)
    assert client.post(BASE + "/readback", headers=RUNTIME, json=pm[1]).status_code == 403
    assert client.post(BASE + "/readback", headers=runtime, json=pm[1]).status_code == 200
    assert client.get("/internal/runtime/history", headers=runtime,
                      params={"task": "PM-1", "session_run_id": NEW_RUN}).status_code == 409
    assert client.post("/internal/runtime/step", headers=runtime,
                       json={**_step_payload(pm[4]), "session_run_id": NEW_RUN}).status_code == 409


def test_second_wait_cannot_reuse_checkpoint_reference(pm):
    run_continuation(pm)
    client = pm[0]
    current = client.post(BASE + "/readback", headers=ADAPTER, json=pm[1]).json()
    runtime = {**RUNTIME, "X-Workflow-Execution-Token": current["execution_token"]}
    checkpoint = {
        **pm[1], "operation_key": "checkpoint:second", "expected_version": 4, "expected_fence": 2,
        "session_run_id": NEW_RUN, "binding_ref": "binding:new", "hermes_run_ref": "run:new",
        "checkpoint_ref": "checkpoint:one", "clarification_request_ref": "request:second",
        "clarification_version": 2, "requirements_revision": 2,
    }
    assert client.post(BASE + "/checkpoint", headers=runtime, json=checkpoint).status_code == 409
    accepted = client.post(BASE + "/checkpoint", headers=runtime,
                           json={**checkpoint, "checkpoint_ref": "checkpoint:second"})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["result"]["version"] == 5
    assert accepted.json()["result"]["state"] == "waiting"
    assert accepted.json()["result"]["resume_session_run_id"] is None
