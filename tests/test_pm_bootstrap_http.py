"""Registered endpoints and configured Fleet proof transport; no live services."""

import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from unittest.mock import Mock, patch

import pytest
import requests

from project_workflow import config
from project_workflow.domain.pm_execution import RuntimeObservation
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from scripts.export_pm_openapi import OUTPUT
from tests.test_pm_bootstrap_retry import NEXT, command
from tests.test_pm_bootstrap_retry import pending as pending
from tests.test_single_task_runtime import WRITER
from tests.test_single_task_runtime import bridge as bridge

PREDECESSOR = "/internal/runtime/pm-bootstrap/predecessor"
RETRY = "/internal/runtime/pm-bootstrap/retry"
FLEET_PROOF = "/internal/runtime/v1/pm/bootstrap-retries/"
HTTP_OBSERVE = pm_readback.observe_run


@contextmanager
def fleet_server(fixture, monkeypatch):
    """Synthetic Fleet preserves the distinction between runs and post-renew permits."""
    state = {"proofs": {NEXT: fixture["proof"].model_dump(mode="json")},
             "runs": {fixture["proof"].native.session_run_id: fixture["proof"].native.model_dump(mode="json")},
             "paths": [], "entered": Event(), "release": Event()}
    state["release"].set()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["paths"].append(self.path)
            value = None
            if self.headers.get("Authorization") == "Bearer " + "p" * 40:
                if self.path.startswith(FLEET_PROOF) and self.path.endswith("/workflow-proof"):
                    state["entered"].set()
                    if state.get("barrier") is not None:
                        state["barrier"].wait(timeout=10)
                    if state["release"].wait(timeout=10):
                        ref = self.path.removeprefix(FLEET_PROOF).removesuffix("/workflow-proof")
                        value = state["proofs"].get(ref)
                elif self.path.startswith("/internal/runtime/v1/pm/runs/"):
                    value = state["runs"].get(self.path.rsplit("/", 1)[-1])
            if isinstance(value, RuntimeObservation):
                value = value.model_dump(mode="json")
            body = json.dumps(value).encode()
            self.send_response(200 if value is not None else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_URL",
                       f"http://127.0.0.1:{server.server_port}/internal/runtime/v1/pm/runs")
    config.get_settings.cache_clear()
    monkeypatch.setattr(pm_readback, "observe_run", HTTP_OBSERVE)
    try:
        yield state
    finally:
        state["release"].set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.parametrize("pending", ["bound", "unbound"], indirect=True)
def test_registered_retry_reads_raw_postrenew_permit_and_replays_without_http(pending, monkeypatch):
    client = pending["client"]
    request = command(pending)
    query = {"task": pending["assignment"]["task"],
             "assignment_operation_key": request.predecessor_operation_key, "assignment_revision": 1}
    read = client.get(PREDECESSOR, params=query, headers=WRITER)
    assert read.status_code == 200 and read.json()["result"] == pending["state"]
    assert read.headers["Cache-Control"] == "no-store"
    with SAUnitOfWork() as uow:
        before = uow.tasks.get_assignment_by_operation_key(request.predecessor_operation_key).to_dict()
    with fleet_server(pending, monkeypatch) as fleet:
        response = client.post(RETRY, json=request.model_dump(), headers=WRITER)
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json()["result"]["assignment_revision"] == 2
        assert response.json()["result"]["binding_state"] == "unbound"
        assert "execution_token" not in response.json()
        assert fleet["paths"] == [FLEET_PROOF + NEXT + "/workflow-proof",
                                  "/internal/runtime/v1/pm/runs/" + pending["proof"].native.session_run_id]
        fleet["proofs"].clear()
        replay = client.post(RETRY, json=request.model_dump(), headers=WRITER)
        assert replay.status_code == 200, replay.text
        assert len(fleet["paths"]) == 2
    with SAUnitOfWork() as uow:
        assert uow.tasks.get_assignment_by_operation_key(request.predecessor_operation_key).to_dict() == before
        assert len(uow.tasks.list_assignments(pending["state"]["task_id"])) == 2


@pytest.mark.parametrize("headers,status", [({}, 401), ({"Authorization": "Bearer " + "r" * 40}, 403)])
def test_retry_requires_pm_assignment_credential_before_callback(pending, monkeypatch, headers, status):
    callback = Mock(side_effect=AssertionError("Unauthorized request must not fetch proof"))
    monkeypatch.setattr(pm_readback, "bootstrap_proof", callback)
    response = pending["client"].post(RETRY, json=command(pending).model_dump(), headers=headers)
    assert response.status_code == status and response.headers["Cache-Control"] == "no-store"
    callback.assert_not_called()


def test_retry_body_is_exactly_five_fields_not_caller_proof_or_url(pending, monkeypatch):
    callback = Mock(side_effect=AssertionError("Invalid body must not fetch proof"))
    monkeypatch.setattr(pm_readback, "bootstrap_proof", callback)
    for extra in ({"proof": pending["proof"].model_dump(mode="json")}, {"url": "http://foreign.test"}):
        response = pending["client"].post(RETRY, json={**command(pending).model_dump(), **extra}, headers=WRITER)
        assert response.status_code == 422
    schema = pending["client"].get("/openapi.json").json()
    body = schema["components"]["schemas"]["BootstrapRetry"]
    assert set(body["properties"]) == set(command(pending).model_dump())
    assert set(body["required"]) == set(command(pending).model_dump())
    assert body["additionalProperties"] is False
    published = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert published["components"]["schemas"]["BootstrapRetry"] == body
    for path in (PREDECESSOR, RETRY):
        assert published["paths"][path] == schema["paths"][path]
    callback.assert_not_called()


@pytest.mark.parametrize("failure,status", [
    ("redirect", 503), ("timeout", 503), ("envelope", 503), ("pre-renew", 503),
    ("json", 503), ("hash", 409), ("attempt", 409),
])
def test_configured_proof_transport_fails_closed_and_never_publishes(pending, failure, status):
    with patch.object(pm_readback.requests, "Session") as factory:
        client = factory.return_value.__enter__.return_value
        response = client.get.return_value
        response.status_code = 302 if failure == "redirect" else 200
        value = pending["proof"].model_dump(mode="json")
        if failure == "timeout":
            client.get.side_effect = requests.Timeout("synthetic-secret")
        elif failure == "envelope":
            value = {"ok": True, "result": value}
        elif failure == "pre-renew":
            value = {"contract_version": 1, "terminal_receipt": value["native"], "barrier_id": NEXT}
        elif failure == "json":
            response.json.side_effect = ValueError("synthetic-secret")
        elif failure == "hash":
            value["owner_version"] = 2
        elif failure == "attempt":
            value["bootstrap_attempt_ref"] = "33333333-3333-4333-8333-333333333333"
        response.json.return_value = value
        result = pending["client"].post(RETRY, json=command(pending).model_dump(), headers=WRITER)
        assert result.status_code == status, result.text
        assert "synthetic-secret" not in result.text
        assert client.trust_env is False
        assert client.get.call_args.args[0] == "http://runtime.test" + FLEET_PROOF + NEXT + "/workflow-proof"
        assert client.get.call_args.kwargs == {
            "headers": {"Authorization": "Bearer " + "p" * 40}, "timeout": (3, 10), "allow_redirects": False,
        }
    with SAUnitOfWork() as uow:
        assert len(uow.tasks.list_assignments(pending["state"]["task_id"])) == 1
