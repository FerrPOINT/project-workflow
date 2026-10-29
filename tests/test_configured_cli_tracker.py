"""Actual configured authority parsers against controlled Tracker responses."""

import json
from contextlib import contextmanager
from uuid import uuid4

import httpx
import pytest
from httpx import Client as NativeHttpClient

from project_workflow import config
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure import configured_cli_tracker as tracker


@pytest.fixture
def authority(monkeypatch):
    request = {"task": "SDLC-901", "tracker_task_id": str(uuid4()), "owner_subject": str(uuid4()),
               "role_key": "project_manager", "mode_key": "draft",
               "assignment_ref": str(uuid4()),
               "tracker_execution_id": str(uuid4()), "concrete_agent_ref": str(uuid4()),
               "machine_subject": str(uuid4()), "assignment_version": 2}
    assignment = {"assignment_id": request["assignment_ref"],
                  "execution_id": request["tracker_execution_id"],
                  "agent_id": request["concrete_agent_ref"],
                  "machine_subject": request["machine_subject"], "version": 2}
    context = {"contract_version": 1, "interaction_protocol": "configured-cli-v1",
               "task_id": request["tracker_task_id"],
               "stage": "Draft", "status": "InProgress",
               "root_task_id": request["tracker_task_id"], "owner_subject": request["owner_subject"],
               "workflow_task_key": request["task"],
               "assignment": assignment}
    confirmed = {"id": str(uuid4()), "task_id": request["tracker_task_id"], "revision": 4,
                 "content_hash": "a" * 64, "owner_subject": request["owner_subject"], "stage": "Draft"}
    bodies = {"context": context, "requirements": {"revision": 4, "content_hash": "a" * 64},
              "requirements/4/confirmation": confirmed}
    monkeypatch.setenv("PROJECT_WORKFLOW_CONFIGURED_TRACKER_URL", "https://tracker.test")
    monkeypatch.setenv("PROJECT_WORKFLOW_CONFIGURED_TRACKER_READ_TOKEN", "private-read-token")
    config.get_settings.cache_clear()
    calls = []
    class Response:
        status_code = 200
        def __init__(self, body):
            self.body = body
        def iter_bytes(self, **kw):
            yield json.dumps(self.body).encode()
    class Client:
        def __init__(self, **kw):
            assert kw == {"timeout": 5, "follow_redirects": False, "trust_env": False}
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        @contextmanager
        def stream(self, method, url, **kwargs):
            assert method == "GET"
            prefix = f"https://tracker.test/api/v1/issues/{request['tracker_task_id']}/sdlc/"
            assert url.startswith(prefix)
            calls.append(url)
            yield Response(bodies[url.removeprefix(prefix)])
    monkeypatch.setattr(tracker.httpx, "Client", Client)
    return request, bodies, calls


def test_current_assignment_and_actual_latest_confirmation(authority):
    request, bodies, calls = authority
    tracker.assignment(request)
    assert tracker.confirmation(request) == bodies["requirements/4/confirmation"]
    assert len(calls) == 3
    for key in ("SDLC-902", None):
        bodies["context"]["workflow_task_key"] = key
        with pytest.raises(ConflictError):
            tracker.assignment(request)
    del bodies["context"]["workflow_task_key"]
    with pytest.raises(ConflictError):
        tracker.assignment(request)


@pytest.mark.parametrize("field", ["assignment_id", "execution_id", "agent_id", "machine_subject", "version"])
def test_every_current_assignment_component_is_exact(authority, field):
    request, bodies, _ = authority
    bodies["context"]["assignment"][field] = 3 if field == "version" else str(uuid4())
    with pytest.raises(ConflictError):
        tracker.assignment(request)


@pytest.mark.parametrize("role,mode,stage", [
    ("project_manager", "draft", "Draft"), ("analyst", "analysis", "Analysis"),
    ("architect", "decomposition", "Architecture"), ("developer", "initial", "Development"),
    ("developer", "rework", "Rework"), ("reviewer", "delivery", "Review"),
    ("tester", "delivery", "Testing"), ("devops", "delivery", "Deployment"),
])
def test_current_stage_must_match_the_assigned_profession_and_mode(authority, role, mode, stage):
    request, bodies, _ = authority
    request.update(role_key=role, mode_key=mode)
    bodies["context"]["stage"] = stage
    tracker.assignment(request)
    for wrong in (None, "Completed", "Rework" if stage != "Rework" else "Development"):
        bodies["context"]["stage"] = wrong
        with pytest.raises(ConflictError):
            tracker.assignment(request)


def test_settled_pm_read_still_requires_the_exact_current_assignment(authority):
    request, bodies, _ = authority
    bodies["context"].update(stage="Backlog", status="Ready")
    tracker.assignment(request, allow_completed_read=True)
    with pytest.raises(ConflictError):
        tracker.assignment(request)
    bodies["context"]["assignment"]["version"] += 1
    with pytest.raises(ConflictError):
        tracker.assignment(request, allow_completed_read=True)


@pytest.mark.parametrize("stage,status", [("Backlog", "InProgress"), ("Draft", "Completed"), ("Backlog", "Completed")])
def test_completed_read_does_not_admit_other_stage_status_pairs(authority, stage, status):
    request, bodies, _ = authority
    bodies["context"].update(stage=stage, status=status)
    with pytest.raises(ConflictError):
        tracker.assignment(request, allow_completed_read=True)


def test_real_pm_reservation_and_owner_wait_can_read_and_report_before_confirmation(authority):
    request, bodies, _ = authority
    bodies["context"].update(stage="Draft", status="Ready", draft_submode="brainstorming")
    tracker.assignment(request)
    bodies["context"]["draft_submode"] = "awaiting_confirmation"
    tracker.assignment(request)
    # Ready is not a shortcut into technical execution or a missing assignment.
    request.update(role_key="analyst", mode_key="analysis")
    bodies["context"].update(stage="Analysis")
    with pytest.raises(ConflictError):
        tracker.assignment(request)


@pytest.mark.parametrize("field", ["task_id", "root_task_id", "owner_subject"])
def test_task_and_owner_cannot_be_borrowed(authority, field):
    request, bodies, _ = authority
    bodies["context"][field] = str(uuid4())
    with pytest.raises(ConflictError):
        tracker.assignment(request)


@pytest.mark.parametrize("protocol", [None, "native-v1", "configured-cli-v2", True])
def test_retired_or_unknown_execution_contract_is_not_current_authority(authority, protocol):
    request, bodies, _ = authority
    bodies["context"]["interaction_protocol"] = protocol
    with pytest.raises(ConflictError):
        tracker.assignment(request)


@pytest.mark.parametrize("field,value", [("task_id", str(uuid4())), ("owner_subject", str(uuid4())),
    ("revision", 3), ("revision", True), ("content_hash", "b" * 64), ("stage", "Analysis"), ("stage", "Backlog"),
    ("id", None), ("id", "00000000-0000-0000-0000-000000000000")])
def test_confirmation_must_match_latest_document_exact_owner_and_draft(authority, field, value):
    request, bodies, _ = authority
    bodies["requirements/4/confirmation"][field] = value
    with pytest.raises(ConflictError):
        tracker.confirmation(request)


def test_no_caller_supplied_url_or_missing_credential_fallback(authority, monkeypatch):
    request, _, calls = authority
    monkeypatch.setenv("PROJECT_WORKFLOW_CONFIGURED_TRACKER_READ_TOKEN", "")
    config.get_settings.cache_clear()
    with pytest.raises(RuntimeError):
        tracker.assignment(request)
    assert calls == []


@pytest.mark.parametrize("status", [None, "Completed", "Blocked", "in_progress", True])
@pytest.mark.parametrize("stage", ["Draft", "Backlog"])
def test_retained_assignment_does_not_authorize_inactive_or_invalid_business_status(authority, stage, status):
    request, bodies, _ = authority
    bodies["context"].update(stage=stage, status=status)
    with pytest.raises(ConflictError):
        tracker.assignment(request)
@pytest.mark.parametrize("fault", ["redirect", "denied", "malformed", "array", "duplicates", "timeout", "oversized"])
def test_authority_transport_fails_closed_once_without_exposing_private_body(authority, monkeypatch, fault):
    request, _, _ = authority
    calls = []
    native_client = NativeHttpClient

    def reply(incoming):
        calls.append(incoming)
        assert incoming.method == "GET"
        assert incoming.headers["Authorization"] == "Bearer private-read-token"
        if fault == "timeout":
            raise httpx.ReadTimeout("private upstream diagnostic", request=incoming)
        status = 302 if fault == "redirect" else 403 if fault == "denied" else 200
        body = {"malformed": b"private upstream diagnostic", "array": b"[]",
                "duplicates": b'{"assignment":1,"assignment":2}', "oversized": b"x" * 262145}.get(fault, b"{}")
        return httpx.Response(status, content=body, headers={"Location": "https://foreign.test"})

    monkeypatch.setattr(tracker.httpx, "Client", lambda **kw: native_client(
        **kw, transport=httpx.MockTransport(reply)))
    with pytest.raises((RuntimeError, ConflictError)) as rejected:
        tracker.read(request, "context")
    assert "private upstream diagnostic" not in str(rejected.value)
    assert len(calls) == 1


def test_invalid_authority_origin_is_rejected_before_opening_a_client(authority, monkeypatch):
    request, _, _ = authority
    monkeypatch.setenv("PROJECT_WORKFLOW_CONFIGURED_TRACKER_URL", "not-an-origin")
    config.get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="authority unavailable"):
        tracker.read(request, "context")


@pytest.mark.parametrize("revision", [{"revision": True, "content_hash": "a" * 64},
    {"revision": 0, "content_hash": "a" * 64}, {"revision": 3, "content_hash": "not-a-hash"}])
def test_latest_requirement_identity_is_validated_before_confirmation_lookup(authority, revision):
    request, bodies, calls = authority
    bodies["requirements"] = revision
    with pytest.raises(ConflictError, match="Latest requirements identity"):
        tracker.confirmation(request)
    assert len(calls) == 1
