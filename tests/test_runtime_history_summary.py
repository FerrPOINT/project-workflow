"""Opt-in safe projection over real SQLite history and existing HTTP authority."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from project_workflow import config
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from tests.test_pm_execution import NEW_RUN, OLD_RUN, RUNTIME, bind_pm, prepare_pm
from tests.test_runtime_api import _assignment, _bind_assignment, _headers, _namespace, _step_payload
from tests.test_runtime_api import packaged_runtime_api_test_image as packaged_runtime_api_test_image
from tests.test_single_task_runtime import PROFILE, SESSION, prepare
from tests.test_single_task_runtime import bridge as bridge

API = "/internal/runtime/history"
PARAMS = {"task": "DEV-1", "projection": "fleet-summary-v1"}
FIELDS = {"history_id", "step_operation_key", "phase_code", "verdict", "status", "retryable",
          "next_phase_code", "rollback_phase_code", "created_at"}
PRIVATE = "PRIVATE_REPORT_PROMPT_TOKEN_BINDING"


def seed_history(role, task_key, verdict, status=None, key=None):
    with SAUnitOfWork() as uow:
        namespace = uow.projects.get_by_cli_command("workflow-" + role)
        task = uow.tasks.get_by_key(task_key, project_id=namespace.id)
        response = {"message": PRIVATE, "prompt": PRIVATE, "token": PRIVATE,
                    "binding": {"private": PRIVATE}, "retryable": verdict == "blocked"}
        if status is not None:
            response["status"] = status
        runtime = {}
        if key is not None:
            assignment = uow.tasks.get_assignment_by_operation_key(task.assignment_operation_key)
            body = _step_payload({**task.to_dict(), **assignment.to_dict()}, PRIVATE, step_operation_key=key)
            runtime = {name: body[name] for name in (
                "assignment_revision", "assignment_ref", "binding_ref", "hermes_run_ref", "attempt_number",
            )}
            runtime.update(request_sha256=payload_sha256(body),
                           assignment_operation_key=task.assignment_operation_key, role_key=role)
        history_id = uow.step_history.create({
            "task_id": task.id, "phase_id": task.current_phase_id, "verdict": verdict,
            "worker_report": PRIVATE, "covered_item_ids": [PRIVATE], "missing_item_ids": [PRIVATE],
            "blocker_messages": [PRIVATE], "evaluation_snapshot": {"prompt": PRIVATE},
            "supervisor_response": response, "step_operation_key": key,
            "next_phase_id": task.current_phase_id if verdict == "pass" else None,
            "rollback_phase_id": task.current_phase_id if verdict == "rollback" else None,
            **runtime,
        })
        uow.commit()
        return history_id


@pytest.fixture
def history(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"developer": "r" * 40,
                                                                        "analyst": "n" * 40}))
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"developer": "a" * 40,
                                                                           "analyst": "b" * 40}))
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", "c" * 40)
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")
    _namespace("ANALYST", "workflow-analyst", "DEV")
    with TestClient(create_app()) as client:
        for role, task_key, token in [("developer", "DEV-1", "a"), ("developer", "DEV-2", "a"),
                                      ("analyst", "DEV-1", "b")]:
            assigned = client.post("/internal/runtime/assign", headers=_headers(token * 40),
                                   json=_assignment(task_key, "assign:" + role + task_key, role))
            assert assigned.status_code == 200, assigned.text
            _bind_assignment(client, token * 40, assigned.json()["result"])
        ids = [seed_history("developer", "DEV-1", verdict, status, "step:" + verdict if index else None)
               for index, (verdict, status) in enumerate([
                   ("pass", None), ("partial", "active"), ("blocked", "blocked"),
                   ("rollback", "active"), ("delegate", "done"),
               ])]
        foreign = seed_history("analyst", "DEV-1", "pass", "done", "foreign:step")
        seed_history("developer", "DEV-2", "pass", "done", "other:task")
        yield client, ids, foreign


def test_summary_whitelist_real_fields_and_legacy_bytes_unchanged(history):
    client, ids, _ = history
    legacy = client.get(API, headers=_headers("r" * 40), params={"task": "DEV-1"})
    assert legacy.status_code == 200
    assert PRIVATE in legacy.text
    response = client.get(API, headers=_headers("r" * 40), params=PARAMS)
    assert response.status_code == 200, response.text
    assert PRIVATE not in response.text
    body = response.json()
    assert set(body) == {"ok", "exit_code", "output", "result"}
    result = body["result"]
    assert set(result) == {"projection", "task_key", "count", "records", "next_before"}
    assert result["projection"] == "fleet-summary-v1"
    assert result["count"] == 5 and result["next_before"] is None
    assert json.loads(body["output"]) == result["records"]
    assert [row["history_id"] for row in result["records"]] == [str(i) for i in reversed(ids)]
    for row in result["records"]:
        assert set(row) == FIELDS
        assert row["phase_code"] == "assigned"
        assert row["retryable"] == (row["verdict"] == "blocked")
        assert row["next_phase_code"] == ("assigned" if row["verdict"] == "pass" else None)
        assert row["rollback_phase_code"] == ("assigned" if row["verdict"] == "rollback" else None)
        assert row["created_at"]
    assert result["records"][-1]["status"] is None  # PASS never fabricates a saved status.
    assert result["records"][-1]["step_operation_key"] is None
    assert client.get(API, headers=_headers("r" * 40), params={"task": "DEV-1"}).content == legacy.content


def test_summary_cursor_is_exclusive_real_id_and_survives_newer_insert(history):
    client, ids, _ = history
    first = client.get(API, headers=_headers("r" * 40), params={**PARAMS, "n": 2}).json()["result"]
    assert first["count"] == 2 and first["next_before"] == str(ids[-2])
    seed_history("developer", "DEV-1", "blocked", "blocked", "new:step")
    collected = first["records"]
    cursor = first["next_before"]
    while cursor is not None:
        response = client.get(API, headers=_headers("r" * 40),
                              params={**PARAMS, "n": 2, "before_history_id": cursor})
        assert response.status_code == 200, response.text
        page = response.json()["result"]
        assert page["count"] == len(page["records"]) <= 2
        assert all(int(row["history_id"]) < int(cursor) for row in page["records"])
        collected.extend(page["records"])
        cursor = page["next_before"]
    assert [row["history_id"] for row in collected] == [str(i) for i in reversed(ids)]
    empty = client.get(API, headers=_headers("r" * 40),
                       params={**PARAMS, "before_history_id": str(ids[0])}).json()["result"]
    assert empty["records"] == [] and empty["count"] == 0 and empty["next_before"] is None


@pytest.mark.parametrize("query", [
    {"projection": "unknown"}, {"n": 0}, {"n": 201}, {"before_history_id": "0"},
    {"before_history_id": "01"}, {"before_history_id": "+1"}, {"before_history_id": "1.0"},
    {"before_history_id": "-1"}, {"before_history_id": " 1"}, {"before_history_id": "1\n"},
    {"before_history_id": "9223372036854775808"}, {"before_history_id": "1" * 20},
])
def test_summary_rejects_unknown_projection_noncanonical_cursor_and_bounds(history, query):
    response = history[0].get(API, headers=_headers("r" * 40), params={**PARAMS, **query})
    assert response.status_code == 422


def test_summary_cursor_requires_opt_in_and_role_namespace_scope_is_unchanged(history):
    client, _, foreign = history
    assert client.get(API, headers=_headers("r" * 40),
                      params={"task": "DEV-1", "before_history_id": "1"}).status_code == 422
    for token, status in [(None, 401), ("wrong" * 10, 401), ("a" * 40, 403), ("c" * 40, 403)]:
        assert client.get(API, headers=_headers(token) if token else {}, params=PARAMS).status_code == status
    analyst = client.get(API, headers=_headers("n" * 40), params=PARAMS)
    assert analyst.status_code == 200, analyst.text
    assert [row["history_id"] for row in analyst.json()["result"]["records"]] == [str(foreign)]
    assert client.get(API, headers=_headers("r" * 40), params={**PARAMS, "task": "OTHER-1"}).status_code == 409


@pytest.mark.parametrize("field,value", [("verdict", PRIVATE), ("status", PRIVATE), ("status", {"raw": PRIVATE})])
def test_summary_invalid_saved_enums_fail_closed_without_echo(history, field, value):
    client, ids, _ = history
    with SAUnitOfWork() as uow:
        row = uow.session.get(m.TaskStepHistoryEntry, ids[-1])
        if field == "verdict":
            row.verdict = value
        else:
            response = json.loads(row.supervisor_response)
            response["status"] = value
            row.supervisor_response = json.dumps(response)
        if field == "verdict":
            with pytest.raises(IntegrityError, match="ck_task_step_history_verdict"):
                uow.commit()
            uow.session.rollback()
        else:
            uow.commit()
    response = client.get(API, headers=_headers("r" * 40), params=PARAMS)
    assert response.status_code == (200 if field == "verdict" else 409)
    assert PRIVATE not in response.text


def test_summary_keeps_pm_execution_token_and_session_fences(monkeypatch):
    prepared = prepare_pm(monkeypatch)
    pm = next(prepared)
    try:
        client, runtime, _, _, _ = bind_pm(pm)
        params = {"task": "PM-1", "projection": "fleet-summary-v1", "session_run_id": OLD_RUN}
        assert client.get(API, headers=RUNTIME, params=params).status_code == 403
        assert client.get(API, headers=runtime, params={**params, "session_run_id": NEW_RUN}).status_code == 409
        response = client.get(API, headers=runtime, params=params)
        assert response.status_code == 200, response.text
        assert response.json()["result"]["records"] == []
    finally:
        prepared.close()


@pytest.mark.parametrize("role,mode,stage", [
    ("analyst", "analysis", "Analysis"), ("architect", "decomposition", "Architecture"),
    ("developer", "initial", "Development"), ("reviewer", "delivery", "Review"),
    ("tester", "delivery", "Testing"), ("devops", "delivery", "Deployment"),
])
def test_summary_keeps_single_task_profile_and_run_fences(bridge, monkeypatch, role, mode, stage):
    assignment, _, _, headers = prepare(bridge, monkeypatch, role=role, mode=mode, stage=stage)
    params = {"task": assignment["task"], "projection": "fleet-summary-v1", "session_run_id": SESSION, **PROFILE}
    good = bridge.get(API, headers=headers, params=params)
    assert good.status_code == 200, good.text
    assert good.json()["result"]["records"] == []
    assert bridge.get(API, headers={"Authorization": headers["Authorization"]}, params=params).status_code == 403
    assert bridge.get(API, headers=headers, params={**params, "session_run_id": OLD_RUN}).status_code == 409
    assert bridge.get(API, headers=headers,
                      params={**params, "instruction_manifest_sha256": "0" * 64}).status_code == 409


def test_summary_openapi_has_only_additive_query_parameters():
    operation = create_app().openapi()["paths"][API]["get"]
    parameters = {item["name"]: item for item in operation["parameters"]}
    assert parameters["n"]["schema"]["minimum"] == 1
    assert parameters["n"]["schema"]["maximum"] == 200
    assert parameters["projection"]["schema"]["anyOf"][0]["const"] == "fleet-summary-v1"
    cursor = parameters["before_history_id"]["schema"]["anyOf"][0]
    assert cursor["type"] == "string" and cursor["maxLength"] == 19
    assert cursor["pattern"] == "^[1-9][0-9]*$"
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {}


@pytest.mark.parametrize("present,value", [(False, None), (True, None), (True, False), (True, True)])
def test_summary_retryable_preserves_nullable_actual_boolean(history, present, value):
    client, ids, _ = history
    with SAUnitOfWork() as uow:
        row = uow.session.get(m.TaskStepHistoryEntry, ids[-1])
        response = json.loads(row.supervisor_response)
        response.pop("retryable")
        if present:
            response["retryable"] = value
        row.supervisor_response = json.dumps(response)
        uow.commit()
    response = client.get(API, headers=_headers("r" * 40), params=PARAMS)
    assert response.status_code == 200, response.text
    record = response.json()["result"]["records"][0]
    assert record["history_id"] == str(ids[-1])
    assert record["retryable"] is value
    assert PRIVATE not in response.text


@pytest.mark.parametrize("value", [PRIVATE, 0, 1, [], {"raw": PRIVATE}])
def test_summary_invalid_retryable_fails_closed_without_echo(history, value):
    client, ids, _ = history
    with SAUnitOfWork() as uow:
        row = uow.session.get(m.TaskStepHistoryEntry, ids[-1])
        response = json.loads(row.supervisor_response)
        response["retryable"] = value
        row.supervisor_response = json.dumps(response)
        uow.commit()
    response = client.get(API, headers=_headers("r" * 40), params=PARAMS)
    assert response.status_code == 409
    assert PRIVATE not in response.text


@pytest.mark.parametrize("value", [None, [PRIVATE], PRIVATE, 1, False])
def test_summary_nonobject_saved_response_fails_closed_without_echo(history, value):
    client, ids, _ = history
    with SAUnitOfWork() as uow:
        row = uow.session.get(m.TaskStepHistoryEntry, ids[-1])
        row.supervisor_response = json.dumps(value)
        uow.commit()
    response = client.get(API, headers=_headers("r" * 40), params=PARAMS)
    assert response.status_code == 409
    assert PRIVATE not in response.text
