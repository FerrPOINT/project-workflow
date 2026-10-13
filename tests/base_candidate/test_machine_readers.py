"""Base issuer/registered-subject boundary, not privileged-human authentication."""

import json

import httpx
import pytest

from project_workflow import config
from project_workflow.infrastructure import base_auth, namespace_auth

DEVELOPER_SUBJECT = "11111111-1111-4111-8111-111111111111"
PM_SUBJECT = "22222222-2222-4222-8222-222222222222"
TESTER_SUBJECT = "33333333-3333-4333-8333-333333333333"
CATALOG_SUBJECT = "44444444-4444-4444-8444-444444444444"
READER = {"Authorization": "Bearer sdlc_pat_" + "d" * 64}
PM_READER = {"Authorization": "Bearer sdlc_pat_" + "p" * 64}
TESTER_READER = {"Authorization": "Bearer sdlc_pat_" + "t" * 64}
CATALOG_READER = {"Authorization": "Bearer sdlc_pat_" + "c" * 64}
REAL_CLIENT = httpx.Client


@pytest.fixture
def registered_readers(monkeypatch):
    subjects = {
        DEVELOPER_SUBJECT: "developer", PM_SUBJECT: "project_manager",
        TESTER_SUBJECT: "tester", CATALOG_SUBJECT: "catalog",
    }
    tokens = {headers["Authorization"]: subject for headers, subject in (
        (READER, DEVELOPER_SUBJECT), (PM_READER, PM_SUBJECT),
        (TESTER_READER, TESTER_SUBJECT), (CATALOG_READER, CATALOG_SUBJECT),
    )}
    state = {"calls": [], "value": None, "status": 200, "body": None, "headers": {}}
    monkeypatch.setenv("AUTH_ISSUER", "https://central.test")
    monkeypatch.setenv("AUTH_INTERNAL_BASE_URL", "http://central.test")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-only-reader-session-secret-" + "x" * 32)
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_READER_SUBJECTS_JSON", json.dumps(subjects))
    config.get_settings.cache_clear()

    def respond(request):
        assert str(request.url) == "http://central.test/auth/tokens/introspect"
        assert request.headers["cache-control"] == "no-cache, no-store"
        state["calls"].append(request)
        value = state["value"] or {
            "sub": tokens.get(request.headers["authorization"], DEVELOPER_SUBJECT),
            "email": "registered-reader@example.test", "scopes": ["project-workflow:read"],
        }
        body = state["body"] if state["body"] is not None else json.dumps(value).encode()
        return httpx.Response(state["status"], content=body, headers=state["headers"])

    monkeypatch.setattr(namespace_auth.httpx, "Client", lambda **kwargs: REAL_CLIENT(
        **kwargs, transport=httpx.MockTransport(respond),
    ))
    yield state
    config.get_settings.cache_clear()


def test_registered_read_principal_is_fresh_and_service_scope_only(registered_readers):
    for _ in range(2):
        principal = base_auth.authorize_read(READER["Authorization"])
        assert principal.subject == DEVELOPER_SUBJECT and principal.role_key == "developer"
    assert len(registered_readers["calls"]) == 2


@pytest.mark.parametrize("scopes", [
    [], ["project-workflow:write"], ["project-workflow:*"],
    ["project-workflow:read", "project-workflow:write"],
    ["project-workflow:read", "project-workflow:read"], ["fleet-control:read"],
    ["project-workflow:read", "project-workflow:terminal:read:DEV-1"],
])
def test_unissuable_wildcard_extra_duplicate_and_wrong_scopes_denied(registered_readers, scopes):
    registered_readers["value"] = {"sub": DEVELOPER_SUBJECT, "email": "admin@test", "scopes": scopes}
    with pytest.raises(namespace_auth.NamespaceAuthError) as error:
        base_auth.authorize_read(READER["Authorization"])
    assert error.value.status == 403


def test_human_pat_with_correct_scope_and_email_is_not_a_registered_machine(registered_readers):
    registered_readers["value"] = {
        "sub": "55555555-5555-4555-8555-555555555555", "email": "registered-reader@example.test",
        "scopes": ["project-workflow:read"],
    }
    with pytest.raises(namespace_auth.NamespaceAuthError) as error:
        base_auth.authorize_read(READER["Authorization"])
    assert error.value.status == 403


@pytest.mark.parametrize("authorization", [None, "Bearer admin", "Bearer base-owner-" + "o" * 32])
def test_legacy_human_or_shared_token_is_not_base_read_authority(registered_readers, authorization):
    with pytest.raises(namespace_auth.NamespaceAuthError) as error:
        base_auth.authorize_read(authorization)
    assert error.value.status == 401 and not registered_readers["calls"]


@pytest.mark.parametrize("registry", [
    "", "{}", "[]", '{"not-a-uuid":"developer"}',
    json.dumps({DEVELOPER_SUBJECT: "admin"}),
    '{"' + DEVELOPER_SUBJECT + '":"developer","' + DEVELOPER_SUBJECT + '":"tester"}',
    " " * 8193,
])
def test_registry_cannot_be_disabled_or_ambiguous(registered_readers, monkeypatch, registry):
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_READER_SUBJECTS_JSON", registry)
    config.get_settings.cache_clear()
    with pytest.raises(namespace_auth.NamespaceAuthError) as error:
        base_auth.authorize_read(READER["Authorization"])
    assert error.value.status == 503 and not registered_readers["calls"]


@pytest.mark.parametrize("status,body,headers,expected", [
    (401, b"", {}, 401), (302, b"", {"Location": "http://other.test"}, 503),
    (200, b"x" * 16385, {}, 503), (200, b"{}", {}, 503),
    (200, b'{"sub":"a","sub":"b","email":"admin","scopes":[]}', {}, 503),
    (200, b"{}", {"Content-Encoding": "gzip"}, 503),
])
def test_failed_or_malformed_introspection_never_authorizes(registered_readers, status, body, headers, expected):
    registered_readers.update(status=status, body=body, headers=headers)
    with pytest.raises(namespace_auth.NamespaceAuthError) as error:
        base_auth.authorize_read(READER["Authorization"])
    assert error.value.status == expected
