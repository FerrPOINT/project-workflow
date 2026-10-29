"""Safe, paged business history through the configured CLI API."""
import json

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests.test_configured_cli import MACHINE, WRITER, enroll
from tests.test_configured_cli import configured as configured

API = "/internal/runtime/history"
FIELDS = {"history_id", "step_operation_key", "phase_code", "verdict", "status", "retryable",
          "next_phase_code", "rollback_phase_code", "created_at"}
PRIVATE = "PRIVATE_REPORT_PROMPT_TOKEN_BINDING"


def seed_history(assignment, verdict, status=None, key=None):
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key(assignment["task"], project_id=assignment["namespace_id"])
        response = {"message": PRIVATE, "prompt": PRIVATE, "token": PRIVATE,
                    "binding": {"private": PRIVATE}, "retryable": verdict == "blocked"}
        if status is not None:
            response["status"] = status
        history_id = uow.step_history.create({
            "task_id": task.id, "phase_id": task.current_phase_id, "verdict": verdict,
            "worker_report": PRIVATE, "covered_item_ids": [PRIVATE], "missing_item_ids": [PRIVATE],
            "blocker_messages": [PRIVATE],
            "evaluation_snapshot": {"prompt": PRIVATE, "configured_cli": {"operation_key": key}},
            "supervisor_response": response,
            "next_phase_id": task.current_phase_id if verdict == "pass" else None,
            "rollback_phase_id": task.current_phase_id if verdict == "rollback" else None,
        })
        uow.commit()
        return history_id


@pytest.fixture
def history(configured):
    enroll(configured)
    _, assignment = configured
    ids = [seed_history(assignment, verdict, status, key) for verdict, status, key in [
        ("pass", None, None), ("partial", "active", "partial"), ("rollback", "active", "rollback"),
        ("blocked", "blocked", "blocked"), ("pass", "done", "pass"),
    ]]
    return configured, ids


def read(history, *, auth=WRITER, **overrides):
    (client, assignment), _ = history
    return client.get(API, headers=auth, params={"interaction_protocol": "configured-cli-v1",
        "namespace_id": assignment["namespace_id"], "task": assignment["task"],
        "projection": "fleet-summary-v1", **overrides})


def test_summary_whitelists_saved_values_without_changing_full_history(history):
    (client, assignment), ids = history
    query = {"interaction_protocol": "configured-cli-v1", "namespace_id": assignment["namespace_id"],
             "task": assignment["task"]}
    full = client.get(API, headers=MACHINE, params=query)
    response = read(history)
    assert response.status_code == 200, response.text
    assert PRIVATE not in response.text
    rows = response.json()["result"]["records"]
    assert [r["history_id"] for r in rows] == [str(i) for i in reversed(ids)]
    assert all(set(row) == FIELDS for row in rows)
    assert rows[-1]["status"] is None
    assert rows[-1]["step_operation_key"] is None
    assert rows[1]["retryable"] is True
    assert rows[2]["rollback_phase_code"] == rows[2]["phase_code"]
    assert rows[0]["next_phase_code"] == rows[0]["phase_code"]
    assert client.get(API, headers=MACHINE, params=query).content == full.content


def test_exclusive_cursor_survives_concurrent_new_history(history):
    (_, assignment), ids = history
    page = read(history, n=2).json()["result"]
    assert page["count"] == 2 and page["next_before"] == str(ids[-2])
    seed_history(assignment, "blocked", "blocked", "later")
    records = page["records"]
    while page["next_before"] is not None:
        cursor = page["next_before"]
        response = read(history, n=2, before_history_id=cursor)
        assert response.status_code == 200, response.text
        page = response.json()["result"]
        assert page["count"] == len(page["records"]) <= 2
        assert all(int(row["history_id"]) < int(cursor) for row in page["records"])
        records.extend(page["records"])
    assert [row["history_id"] for row in records] == [str(i) for i in reversed(ids)]
    empty = read(history, before_history_id=ids[0]).json()["result"]
    assert empty["records"] == [] and empty["count"] == 0 and empty["next_before"] is None


@pytest.mark.parametrize("query", [
    {"projection": "unknown"}, {"n": 0}, {"n": 201}, {"before_history_id": "0"},
    {"before_history_id": "01"}, {"before_history_id": "+1"}, {"before_history_id": "1.0"},
    {"before_history_id": "-1"}, {"before_history_id": " 1"}, {"before_history_id": "1\n"},
    {"before_history_id": "9223372036854775808"}, {"before_history_id": "1" * 20},
])
def test_summary_rejects_unknown_projection_noncanonical_cursor_and_bounds(history, query):
    assert read(history, **query).status_code == 422


@pytest.mark.parametrize("auth", [{}, {"Authorization": "Bearer wrong"},
                                 {"Authorization": "Bearer " + "r" * 40}])
def test_unknown_or_retired_credentials_cannot_read_history(history, auth):
    assert read(history, auth=auth).status_code in (401, 403)


def test_foreign_namespace_and_task_cannot_select_another_history(history):
    (_, assignment), _ = history
    assert read(history, namespace_id=assignment["namespace_id"] + 100).status_code != 200
    assert read(history, task="SDLC-foreign").status_code != 200
    assert read(history, operation_key="pass").status_code == 409


@pytest.mark.parametrize("field,value", [("verdict", PRIVATE), ("status", PRIVATE), ("status", {"raw": PRIVATE})])
def test_invalid_saved_enums_fail_closed_without_echo(history, field, value):
    _, ids = history
    with SAUnitOfWork() as uow:
        row = uow.session.get(m.TaskStepHistoryEntry, ids[-1])
        if field == "verdict":
            row.verdict = value
            with pytest.raises(IntegrityError, match="ck_task_step_history_verdict"):
                uow.commit()
            uow.session.rollback()
        else:
            response = json.loads(row.supervisor_response)
            response[field] = value
            row.supervisor_response = json.dumps(response)
            uow.commit()
    response = read(history)
    assert response.status_code == (200 if field == "verdict" else 409)
    assert PRIVATE not in response.text


@pytest.mark.parametrize("present,value", [(False, None), (True, None), (True, False), (True, True)])
def test_summary_preserves_nullable_actual_boolean(history, present, value):
    _, ids = history
    with SAUnitOfWork() as uow:
        row = uow.session.get(m.TaskStepHistoryEntry, ids[-1])
        response = json.loads(row.supervisor_response)
        response.pop("retryable")
        if present:
            response["retryable"] = value
        row.supervisor_response = json.dumps(response)
        uow.commit()
    response = read(history)
    assert response.status_code == 200, response.text
    record = response.json()["result"]["records"][0]
    assert record["history_id"] == str(ids[-1]) and record["retryable"] is value
    assert PRIVATE not in response.text


@pytest.mark.parametrize("value", [PRIVATE, 0, 1, [], {"raw": PRIVATE}])
def test_invalid_retryable_is_not_coerced(history, value):
    _, ids = history
    with SAUnitOfWork() as uow:
        row = uow.session.get(m.TaskStepHistoryEntry, ids[-1])
        response = json.loads(row.supervisor_response)
        response["retryable"] = value
        row.supervisor_response = json.dumps(response)
        uow.commit()
    response = read(history)
    assert response.status_code == 409 and PRIVATE not in response.text


@pytest.mark.parametrize("value", [None, [], PRIVATE, True, 1])
def test_nonobject_saved_response_fails_closed(history, value):
    _, ids = history
    with SAUnitOfWork() as uow:
        row = uow.session.get(m.TaskStepHistoryEntry, ids[-1])
        row.supervisor_response = json.dumps(value)
        uow.commit()
    response = read(history)
    assert response.status_code == 409 and PRIVATE not in response.text


def test_summary_query_count_is_bounded_for_repeated_phases(history):
    (_, assignment), _ = history
    counts = []
    queries = []
    def count(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)
    event.listen(Engine, "before_cursor_execute", count)
    try:
        assert read(history, n=200).status_code == 200
        counts.append(len(queries))
        for i in range(30):
            seed_history(assignment, "pass", None, f"bulk-{i}")
        queries.clear()
        assert read(history, n=200).status_code == 200
        counts.append(len(queries))
    finally:
        event.remove(Engine, "before_cursor_execute", count)
    assert counts[1] <= counts[0] + 2
