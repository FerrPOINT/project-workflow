"""Exact-scope and saved-launch checks against controlled owner responses."""
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest

from project_workflow.infrastructure import background_admission as admission
from project_workflow.infrastructure import namespace_auth


@pytest.fixture
def owner(monkeypatch):
    subject, run = str(uuid4()), str(uuid4())
    value = {"run_id": run, "project_id": str(uuid4()), "process_id": str(uuid4()),
             "session_id": str(uuid4()), "agent_id": str(uuid4()), "state": "running",
             "workflow_revision": "a" * 64, "sources": [], "context": {
                 "machine_subject": subject, "namespace_id": "15", "workflow_id": "16", "config_revision": 1,
                 "catalog_version": 2, "profession": "BUG_SEARCHER"}}
    scopes = ["project-workflow:background:read", "project-workflow:background:write"]
    monkeypatch.setattr(namespace_auth, "introspect", lambda _, **kwargs: (
        namespace_auth.NamespacePrincipal("https://auth.fixture.invalid", subject), scopes))
    monkeypatch.setenv("PROJECT_WORKFLOW_BACKGROUND_FLEET_URL", "https://fleet.fixture.invalid")
    monkeypatch.setenv("PROJECT_WORKFLOW_BACKGROUND_READER_TOKEN", "fixture-reader-secret")
    admission.config.get_settings.cache_clear()
    response = [httpx.Response(200, json=value)]
    calls = []
    client = httpx.Client

    def serve(request):
        calls.append(request)
        assert str(request.url) == f"https://fleet.fixture.invalid/internal/background/v1/runs/{run}"
        assert request.headers["Authorization"] == "Bearer fixture-reader-secret"
        return response[0]

    monkeypatch.setattr(admission.httpx, "Client", lambda **kwargs: client(
        transport=httpx.MockTransport(serve), **kwargs))
    return run, value, scopes, response, calls


def test_background_owner_read_keeps_frozen_identity_but_not_runtime_state(owner):
    run, value, _, _, calls = owner
    observed = admission.read(run, "Bearer fixture-agent-secret", write=True, namespace_id=15)
    assert observed.run_id == run and observed.context.catalog_version == 2
    assert observed.identity() == {key: item for key, item in value.items() if key not in {"state", "sources"}}
    assert len(calls) == 1


@pytest.mark.parametrize("scopes", [[], ["project-workflow:read"], ["project-workflow:write"],
    ["project-workflow:background:read"], ["project-workflow:background:write"] * 2,
    ["project-workflow:background:write", "task-tracker:write"]])
def test_wrong_scopes_never_reach_fleet(owner, scopes):
    run, _, grants, _, calls = owner
    grants[:] = scopes
    with pytest.raises(namespace_auth.NamespaceAuthError) as error:
        admission.read(run, "Bearer fixture-agent", write=True, namespace_id=15)
    assert error.value.status == 403 and not calls


@pytest.mark.parametrize("status,expected", [(401,403),(403,403),(404,403),(302,503),(500,503),(503,503)])
def test_owner_failure_does_not_admit_or_echo_credentials(owner, status, expected):
    run, _, _, response, _ = owner
    response[0] = httpx.Response(status, json={"error": "fixture-reader-secret"})
    with pytest.raises(namespace_auth.NamespaceAuthError) as error:
        admission.read(run, "Bearer fixture-agent", write=True, namespace_id=15)
    assert error.value.status == expected and "secret" not in str(error.value)


@pytest.mark.parametrize("field,value", [("run_id",str(uuid4())),("session_id",None),
    ("state","cancelled"),("workflow_revision","not-a-sha256"),
    ("context.machine_subject",str(uuid4())),("context.namespace_id","99"),
    ("context.catalog_version",0),("context.profession","DEVELOPER")])
def test_changed_or_invalid_launch_is_rejected(owner, field, value):
    run, original, _, response, _ = owner
    changed = deepcopy(original)
    if field.startswith("context."):
        changed["context"][field.removeprefix("context.")] = value
    else:
        changed[field] = value
    response[0] = httpx.Response(200, json=changed)
    with pytest.raises(namespace_auth.NamespaceAuthError):
        admission.read(run, "Bearer fixture-agent", write=True, namespace_id=15)


def test_terminal_history_remains_owned_and_readable(owner):
    run, value, _, response, _ = owner
    value["state"] = "completed"
    response[0] = httpx.Response(200, json=value)
    assert admission.read(run, "Bearer fixture-agent", write=False, namespace_id=15, active=False).state == "completed"
