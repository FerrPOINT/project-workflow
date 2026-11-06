"""Bounded diagnostic projection with normal assignment authority and no provider calls."""

import json
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from project_workflow.application import configured_cli
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure import base_auth, configured_cli_tracker, namespace_auth
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.interfaces.cli.core import cli
from project_workflow.interfaces.ui.routes import configured_cli_api
from tests.test_configured_cli import CONTROLLER, MACHINE, WRITER, enroll
from tests.test_configured_cli import configured as configured
from tests.test_configured_cli_transport import agent_env as agent_env
from tests.test_configured_cli_transport import fake_transport

API = "/internal/runtime/history"
PROJECTION = "evaluator-diagnostics-v1"
PRIVATE = "PRIVATE_REPORT_AND_EVALUATION"


@pytest.fixture(autouse=True)
def renderer(monkeypatch):
    module = ModuleType("project_workflow.supervisor.diagnostics")
    render = Mock(return_value={"availability": "legacy"})
    module.history_diagnostic = render
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(OpenAICompatibleClient, "respond", Mock(side_effect=AssertionError("No provider on reads")))
    return render


def seed(assignment):
    with SAUnitOfWork() as uow:
        task, _, payload = configured_cli._row(uow, assignment["task"], assignment["namespace_id"])
        history_id = uow.step_history.create({
            "task_id": task.id, "phase_id": task.current_phase_id, "verdict": "partial",
            "worker_report": PRIVATE, "covered_item_ids": [], "missing_item_ids": ["required"],
            "blocker_messages": [], "evaluation_snapshot": {"private": PRIVATE, "configured_cli": {
                "execution_ref": payload["execution_ref"], "result_version": 2}},
            "supervisor_response": {"verdict": "PARTIAL", "status": "active", "retryable": False},
        })
        uow.commit()
        return history_id


@pytest.fixture
def history(configured):
    enroll(configured)
    ids = [seed(configured[1]) for _ in range(3)]
    return configured, ids


def read(history, *, authorization=MACHINE["Authorization"], **changes):
    (_, assignment), _ = history
    args = {"task": assignment["task"], "namespace_id": assignment["namespace_id"],
            "authorization": authorization, "n": 1, "execution_ref": None, "operation_key": None,
            "projection": PROJECTION, **changes}
    return configured_cli_api.history(**args)


def test_only_renderer_output_is_exposed_and_cursor_is_exclusive(history, renderer):
    (_, assignment), ids = history
    response = read(history)
    result = response["result"]
    assert result["projection"] == PROJECTION
    assert result["records"] == [{"history_id": ids[-1], "diagnostics": {"availability": "legacy"}}]
    assert result["next_before"] == ids[-1]
    assert PRIVATE not in json.dumps(response)
    assert renderer.call_count == 1
    assert renderer.call_args.args[0] == PRIVATE and renderer.call_args.args[1]["private"] == PRIVATE
    seed(assignment)
    second = read(history, before_history_id=result["next_before"])["result"]
    assert second["records"] == [{"history_id": ids[1], "diagnostics": {"availability": "legacy"}}]
    page = read(history, before_history_id=second["next_before"])["result"]
    assert page["records"] == [{"history_id": ids[0], "diagnostics": {"availability": "legacy"}}]
    assert page["next_before"] is None
    assert read(history, before_history_id=ids[0])["result"]["records"] == []


def test_default_and_fleet_history_are_unchanged(history, renderer):
    (client, assignment), _ = history
    query = {"interaction_protocol": "configured-cli-v1", "namespace_id": assignment["namespace_id"],
             "task": assignment["task"], "n": 2}
    full = client.get(API, headers=MACHINE, params=query)
    summary = client.get(API, headers=WRITER, params={**query, "projection": "fleet-summary-v1"})
    assert full.status_code == summary.status_code == 200
    assert set(full.json()["result"]["records"][0]) == {"history_id", "worker_report", "result"}
    assert PRIVATE in full.text and PRIVATE not in summary.text
    read(history)
    assert client.get(API, headers=MACHINE, params=query).content == full.content
    after = client.get(API, headers=WRITER, params={**query, "projection": "fleet-summary-v1"})
    assert after.content == summary.content
    assert renderer.call_count == 1


def test_old_snapshot_without_trace_is_delegated_as_legacy(history, renderer):
    _, ids = history
    with SAUnitOfWork() as uow:
        row = uow.session.get(m.TaskStepHistoryEntry, ids[0])
        row.evaluation_snapshot = "{}"
        uow.commit()
    response = read(history, before_history_id=ids[1])
    assert response["result"]["records"] == [
        {"history_id": ids[0], "diagnostics": {"availability": "legacy"}},
    ]
    renderer.assert_called_once_with(PRIVATE, {})
    assert PRIVATE not in json.dumps(response)


@pytest.mark.parametrize("changes", [
    {"n": 0}, {"n": 2}, {"n": 200}, {"n": True}, {"operation_key": "saved-operation"},
    {"assignment_operation_key": "enroll-901"}, {"execution_ref": "execution"},
    {"before_history_id": 0}, {"before_history_id": True}, {"before_history_id": 2**63},
])
def test_bounds_and_selectors_are_rejected_before_rendering(history, renderer, changes):
    assert read(history, **changes).status_code == 409
    renderer.assert_not_called()


def test_one_record_is_the_maximum(history):
    assert len(read(history, n=1)["result"]["records"]) == 1


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", WRITER["Authorization"]])
def test_diagnostics_requires_normal_assignment_identity(history, renderer, authorization):
    assert read(history, authorization=authorization).status_code in (401, 403)
    renderer.assert_not_called()


def test_fleet_role_registration_does_not_authorize_diagnostics(history, renderer, monkeypatch):
    monkeypatch.setattr(base_auth, "registered_subjects", lambda: {CONTROLLER: "developer"})
    assert read(history, authorization=WRITER["Authorization"]).status_code == 403
    (_, assignment), _ = history
    with SAUnitOfWork() as uow, pytest.raises(namespace_auth.NamespaceAuthError):
        configured_cli.history(uow, assignment["task"], assignment["namespace_id"], WRITER["Authorization"],
            n=1, execution_ref=None, operation_key=None, trusted="project_manager", projection=PROJECTION)
    renderer.assert_not_called()


def test_foreign_namespace_and_task_are_denied(history, renderer):
    (_, assignment), _ = history
    assert read(history, namespace_id=assignment["namespace_id"] + 100).status_code == 404
    assert read(history, task="SDLC-foreign").status_code == 404
    renderer.assert_not_called()


def test_current_tracker_assignment_is_checked(history, renderer, monkeypatch):
    check = Mock(side_effect=ConflictError("Changed assignment"))
    monkeypatch.setattr(configured_cli_tracker, "assignment", check)
    assert read(history).status_code == 409
    check.assert_called_once()
    renderer.assert_not_called()


def test_renderer_error_cannot_fall_back_to_private_report(history, renderer):
    renderer.side_effect = RuntimeError(PRIVATE)
    response = read(history)
    assert response.status_code == 503
    assert PRIVATE not in response.body.decode()


def test_legacy_cli_surface_cannot_expose_diagnostics(history, renderer):
    (client, assignment), _ = history
    response = client.get("/api/cli/history", headers=MACHINE, params={
        "task": assignment["task"], "namespace_id": assignment["namespace_id"], "projection": PROJECTION})
    assert response.status_code in (404, 405)
    assert PRIVATE not in response.text
    renderer.assert_not_called()


def test_cli_diagnostics_uses_existing_history_transport_and_limit(agent_env, monkeypatch):
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", "history", "--task", "SDLC-31", "--diagnostics",
                                     "--before-history-id", "12"])
    assert result.exit_code == 0, result.output
    args, kwargs = calls[0]
    assert args[0] == "GET" and args[1].endswith("/internal/runtime/history")
    assert kwargs["params"]["projection"] == PROJECTION
    assert kwargs["params"]["n"] == 1 and kwargs["params"]["before_history_id"] == 12


@pytest.mark.parametrize("arguments", [["--n", "2"], ["--operation-key", "op"], ["--execution-ref", "ref"]])
def test_cli_refuses_invalid_diagnostic_selectors_before_http(agent_env, monkeypatch, arguments):
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", "history", "--task", "SDLC-31", "--diagnostics", *arguments])
    assert result.exit_code != 0 and not calls


def test_cli_default_history_stays_unprojected(agent_env, monkeypatch):
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", "history", "--task", "SDLC-31"])
    assert result.exit_code == 0, result.output
    assert calls[0][1]["params"]["n"] == 200
    assert "projection" not in calls[0][1]["params"]
