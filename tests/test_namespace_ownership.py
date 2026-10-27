"""Namespace authority is provisioned, not a caller admission claim."""

import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from project_workflow import config
from project_workflow.application.namespace_ownership import NamespaceOwnershipService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.namespace_ownership import NamespaceOwnershipRequest
from project_workflow.infrastructure import namespace_auth
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.repositories.project import SAProjectRepository
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.namespace_auth import NamespacePrincipal
from project_workflow.interfaces.ui.app import create_app
from tests._retained_pm_history import PROJECT_REF, retained_pm
from tests.test_runtime_api import _namespace

SUBJECT = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
OTHER_SUBJECT = "ffffffff-ffff-4fff-8fff-ffffffffffff"
ISSUER = "http://auth.test"
PAYLOAD = {"contract_version": 1, "tracker_instance_ref": "Tracker:ONE", "tracker_project_ref": PROJECT_REF}
PAT = {"Authorization": "Bearer sdlc_pat_test-secret"}
ADAPTER = {"Authorization": "Bearer " + "a" * 40}
HTTP_CLIENT = httpx.Client


def test_pm_namespace_lock_preserves_generic_fk_key_share_compatibility():
    class CaptureSession:
        statement = None

        def scalar(self, statement):
            self.statement = statement
            return None

    session = CaptureSession()
    assert SAProjectRepository(session).lock_pm_namespace(1) is None
    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert sql.endswith("FOR NO KEY UPDATE")


@pytest.fixture
def pm(monkeypatch):
    yield from retained_pm(monkeypatch)


def install_auth(monkeypatch, namespace_id, *, status=200, value=None, response_headers=None):
    monkeypatch.setenv("AUTH_ISSUER", ISSUER)
    monkeypatch.setenv("AUTH_INTERNAL_BASE_URL", ISSUER)
    monkeypatch.setenv("AUTH_SESSION_SECRET", "x" * 40)
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_PROVISIONER_SUBJECT", SUBJECT)
    config.get_settings.cache_clear()
    calls = []
    identity = value if value is not None else {"sub": SUBJECT, "email": "machine@test", "scopes": [
        "project-workflow:write", "project-workflow:read",
    ]}

    def handle(request):
        calls.append(request)
        return httpx.Response(status, json=identity, headers=response_headers)

    def client(**kwargs):
        assert kwargs == {"timeout": 5, "follow_redirects": False, "trust_env": False}
        return HTTP_CLIENT(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(namespace_auth.httpx, "Client", client)
    return calls, identity


@pytest.fixture
def owned_namespace(monkeypatch):
    _namespace("PM", "workflow-project_manager", "PM")
    with SAUnitOfWork() as uow:
        namespace_id = uow.projects.get_by_cli_command("workflow-project_manager").id
    calls, identity = install_auth(monkeypatch, namespace_id)
    # TestClient itself retains the real constructor; only the introspection client is substituted.
    client = TestClient(create_app())
    yield client, namespace_id, calls, identity
    client.close()


def test_provision_readback_replay_restart_are_immutable(owned_namespace):
    client, namespace_id, calls, _ = owned_namespace
    url = f"/api/pm/namespace-ownership/{namespace_id}"
    first = client.put(url, headers=PAT, json=PAYLOAD)
    assert first.status_code == 201, first.text
    result = first.json()["result"]
    assert set(result) == {"contract_version", "ownership_ref", "namespace_id", "tracker_instance_ref",
                           "tracker_project_ref", "authority_issuer", "provisioner_subject", "created_at"}
    assert result["tracker_instance_ref"] == "Tracker:ONE"
    assert result["provisioner_subject"] == SUBJECT and result["authority_issuer"] == ISSUER
    assert first.headers["cache-control"] == "no-store"
    replay = client.put(url, headers=PAT, json=PAYLOAD)
    assert replay.status_code == 200 and replay.json() == first.json()
    with TestClient(create_app()) as restarted:
        assert restarted.get(url, headers=PAT).json() == first.json()
    for changed in [{**PAYLOAD, "tracker_instance_ref": "tracker:one"},
                    {**PAYLOAD, "tracker_project_ref": str(uuid4())}]:
        assert client.put(url, headers=PAT, json=changed).status_code == 409
    assert client.get(url, headers=PAT).json() == first.json()
    assert len(calls) == 6
    assert all(str(call.url) == ISSUER + "/auth/tokens/introspect" for call in calls)
    assert all(call.headers["accept-encoding"] == "identity" for call in calls)


@pytest.mark.parametrize("field,value", [
    ("tracker_instance_ref", ""), ("tracker_instance_ref", "x" * 129),
    ("tracker_instance_ref", "leading space"), ("tracker_instance_ref", "instance\n"),
    ("tracker_instance_ref", "x\x00"), ("tracker_instance_ref", "x\x85"),
    ("tracker_instance_ref", "x\u00a0"), ("tracker_instance_ref", 12),
    ("tracker_instance_ref", "x" * 125 + "\u0416\u0301"),
    ("tracker_instance_ref", "\u0416" * 65),
    ("tracker_project_ref", "00000000-0000-0000-0000-000000000000"),
    ("tracker_project_ref", PROJECT_REF.upper()), ("tracker_project_ref", " " + PROJECT_REF),
    ("contract_version", True), ("contract_version", "1"), ("contract_version", 2),
    ("authority_issuer", "http://caller.test"), ("provisioner_subject", SUBJECT),
])
def test_strict_wire_does_not_normalize_or_accept_claims(owned_namespace, field, value):
    client, namespace_id, _, _ = owned_namespace
    assert client.put(f"/api/pm/namespace-ownership/{namespace_id}", headers=PAT,
                      json={**PAYLOAD, field: value}).status_code == 422
    with pytest.raises(ValidationError):
        NamespaceOwnershipRequest.model_validate({**PAYLOAD, field: value})


@pytest.mark.parametrize("headers", [{}, {"Cookie": "workflow_sso=ignored"},
                                       {"Authorization": "Bearer local"}, ADAPTER,
                                       {"Authorization": "Bearer sdlc_pat_bad\t"}])
def test_no_cookie_local_or_runtime_fallback(owned_namespace, headers):
    client, namespace_id, calls, _ = owned_namespace
    assert client.put(f"/api/pm/namespace-ownership/{namespace_id}", headers=headers, json=PAYLOAD).status_code == 401
    assert calls == []


@pytest.mark.parametrize("scopes,subject", [
    (["project-workflow:read"], SUBJECT),
    (["project-workflow:namespace-owner:provision:1"], SUBJECT),
    (["project-workflow:write", "project-workflow:namespace-owner:provision:*"], SUBJECT),
    (["project-workflow:write", "project-workflow:namespace-owner:provision:9999"], SUBJECT),
    (["project-workflow:write", "project-workflow:namespace-owner:provision:1"], OTHER_SUBJECT),
    (["project-workflow:write"], OTHER_SUBJECT),
    (["project-workflow:write", "project-workflow:write"], SUBJECT),
])
def test_exact_grants_and_pinned_machine_subject(owned_namespace, scopes, subject):
    client, namespace_id, _, identity = owned_namespace
    identity.update(scopes=scopes, sub=subject)
    assert client.put(f"/api/pm/namespace-ownership/{namespace_id}", headers=PAT, json=PAYLOAD).status_code == 403


def test_read_requires_issuable_read_grant_pinned_subject_and_fresh_introspection(owned_namespace):
    client, namespace_id, calls, identity = owned_namespace
    url = f"/api/pm/namespace-ownership/{namespace_id}"
    assert client.put(url, headers=PAT, json=PAYLOAD).status_code == 201
    identity["scopes"] = ["project-workflow:read"]
    assert client.get(url, headers=PAT).status_code == 200
    identity["scopes"] = [f"project-workflow:namespace-owner:read:{namespace_id}"]
    assert client.get(url, headers=PAT).status_code == 403
    assert len(calls) == 3


@pytest.mark.parametrize("display_name", ["QA machine", ""])
def test_base_profile_metadata_preserves_namespace_authorization(owned_namespace, display_name):
    client, namespace_id, _, identity = owned_namespace
    identity["display_name"] = display_name
    url = f"/api/pm/namespace-ownership/{namespace_id}"
    created = client.put(url, headers=PAT, json=PAYLOAD)
    assert created.status_code == 201, created.text
    assert client.get(url, headers=PAT).status_code == 200
    identity["sub"] = str(uuid4())
    assert client.get(url, headers=PAT).status_code == 403


def test_explicit_machine_role_preserves_registered_subject_and_scope_checks(owned_namespace):
    client, namespace_id, _, identity = owned_namespace
    identity["role"] = "service_account"
    url = f"/api/pm/namespace-ownership/{namespace_id}"
    assert client.put(url, headers=PAT, json=PAYLOAD).status_code == 201
    identity["sub"] = OTHER_SUBJECT
    assert client.get(url, headers=PAT).status_code == 403


@pytest.mark.parametrize("role", ["user", "admin", "member", "operator", None, 7])
def test_human_or_invalid_role_cannot_become_registered_machine(owned_namespace, role):
    client, namespace_id, _, identity = owned_namespace
    identity["role"] = role
    assert client.put(f"/api/pm/namespace-ownership/{namespace_id}", headers=PAT, json=PAYLOAD).status_code == 403


def test_unknown_introspection_claims_do_not_authorize_namespace_access(owned_namespace):
    client, namespace_id, _, identity = owned_namespace
    identity.update(display_name="QA machine", is_admin=True)
    response = client.put(f"/api/pm/namespace-ownership/{namespace_id}", headers=PAT, json=PAYLOAD)
    assert response.status_code == 503


def test_foreign_subject_with_all_correct_grants_cannot_provision(owned_namespace):
    client, namespace_id, _, identity = owned_namespace
    identity["sub"] = OTHER_SUBJECT
    assert client.put(f"/api/pm/namespace-ownership/{namespace_id}", headers=PAT, json=PAYLOAD).status_code == 403


def test_configured_issuer_change_cannot_reown_existing_mapping(owned_namespace, monkeypatch):
    client, namespace_id, _, _ = owned_namespace
    url = f"/api/pm/namespace-ownership/{namespace_id}"
    first = client.put(url, headers=PAT, json=PAYLOAD)
    assert first.status_code == 201
    monkeypatch.setenv("AUTH_ISSUER", "http://another-authority.test")
    config.get_settings.cache_clear()
    assert client.put(url, headers=PAT, json=PAYLOAD).status_code == 409
    assert client.get(url, headers=PAT).status_code == 403
    monkeypatch.setenv("AUTH_ISSUER", ISSUER)
    config.get_settings.cache_clear()
    assert client.get(url, headers=PAT).json() == first.json()


def test_valid_instance_boundary_is_exact_without_normalization(owned_namespace):
    client, namespace_id, _, _ = owned_namespace
    url = f"/api/pm/namespace-ownership/{namespace_id}"
    instance = "X" * 124 + "\u0416\u0301"
    assert len(instance.encode("utf-8")) == 128
    response = client.put(url, headers=PAT, json={**PAYLOAD, "tracker_instance_ref": instance})
    assert response.status_code == 201
    assert response.json()["result"]["tracker_instance_ref"] == instance


def test_invalid_utf8_scalar_is_rejected_without_mutation(owned_namespace):
    client, namespace_id, calls, _ = owned_namespace
    payload = {**PAYLOAD, "tracker_instance_ref": "\ud800"}
    response = client.put(f"/api/pm/namespace-ownership/{namespace_id}",
                          headers={**PAT, "Content-Type": "application/json"},
                          content=json.dumps(payload).encode("ascii"))
    assert response.status_code == 422, response.text
    assert calls == []
    with pytest.raises(ValidationError):
        NamespaceOwnershipRequest.model_validate(payload)
    with SAUnitOfWork() as uow:
        assert uow.projects.get_pm_ownership(namespace_id) is None


def test_timeout_and_compressed_dependency_are_sanitized(owned_namespace, monkeypatch):
    client, namespace_id, _, _ = owned_namespace
    calls = []

    def fail(request):
        calls.append(request)
        raise httpx.ReadTimeout("sdlc_pat_test-secret http://private/error", request=request)

    monkeypatch.setattr(namespace_auth.httpx, "Client", lambda **kwargs: HTTP_CLIENT(
        transport=httpx.MockTransport(fail), **kwargs,
    ))
    response = client.get(f"/api/pm/namespace-ownership/{namespace_id}", headers=PAT)
    assert response.status_code == 503 and "secret" not in response.text and "private" not in response.text
    assert len(calls) == 1
    install_auth(monkeypatch, namespace_id, response_headers={"Content-Encoding": "br"})
    assert client.get(f"/api/pm/namespace-ownership/{namespace_id}", headers=PAT).status_code == 503


def test_total_stream_deadline_and_malformed_json(owned_namespace, monkeypatch):
    client, namespace_id, _, _ = owned_namespace
    times = iter([0, 6])
    monkeypatch.setattr(namespace_auth, "_monotonic", lambda: next(times))
    assert client.get(f"/api/pm/namespace-ownership/{namespace_id}", headers=PAT).status_code == 503
    monkeypatch.setattr(namespace_auth, "_monotonic", lambda: 0)
    monkeypatch.setattr(namespace_auth.httpx, "Client", lambda **kwargs: HTTP_CLIENT(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"not-json")), **kwargs,
    ))
    assert client.get(f"/api/pm/namespace-ownership/{namespace_id}", headers=PAT).status_code == 503


@pytest.mark.parametrize("status", [301, 302, 307, 401, 403, 500])
def test_remote_status_is_sanitized_without_redirects_or_retries(owned_namespace, monkeypatch, status):
    client, namespace_id, _, _ = owned_namespace
    calls, _ = install_auth(monkeypatch, namespace_id, status=status,
                            value={"error": "sdlc_pat_test-secret http://private/error"},
                            response_headers={"Location": "http://private/error"})
    response = client.get(f"/api/pm/namespace-ownership/{namespace_id}", headers=PAT)
    assert response.status_code == (401 if status == 401 else 503)
    assert "secret" not in response.text and "private" not in response.text
    assert len(calls) == 1


@pytest.mark.parametrize("value", [{}, {"sub": SUBJECT, "email": "x", "scopes": "write"},
                                    {"sub": "not-uuid", "email": "x", "scopes": []},
                                    {"sub": SUBJECT, "email": "x" * 17000, "scopes": []}])
def test_invalid_or_oversized_introspection_fails_closed(owned_namespace, monkeypatch, value):
    client, namespace_id, _, _ = owned_namespace
    calls, _ = install_auth(monkeypatch, namespace_id, value=value)
    assert client.get(f"/api/pm/namespace-ownership/{namespace_id}", headers=PAT).status_code == 503
    assert len(calls) == 1


@pytest.mark.parametrize("setting,value", [
    ("AUTH_ISSUER", ""), ("AUTH_INTERNAL_BASE_URL", "http://auth.test/path"),
    ("AUTH_INTERNAL_BASE_URL", "http://user:secret@auth.test"),
    ("AUTH_INTERNAL_BASE_URL", "http://auth.test/?url=elsewhere"),
    ("PROJECT_WORKFLOW_NAMESPACE_PROVISIONER_SUBJECT", ""),
    ("PROJECT_WORKFLOW_NAMESPACE_PROVISIONER_SUBJECT", SUBJECT.upper()),
    ("PROJECT_WORKFLOW_NAMESPACE_PROVISIONER_SUBJECT", "00000000-0000-0000-0000-000000000000"),
])
def test_configuration_never_falls_back_to_open_access(owned_namespace, monkeypatch, setting, value):
    client, namespace_id, calls, _ = owned_namespace
    monkeypatch.setenv(setting, value)
    config.get_settings.cache_clear()
    assert client.get(f"/api/pm/namespace-ownership/{namespace_id}", headers=PAT).status_code == 503
    assert calls == []


def test_repository_reverse_uniqueness_and_namespace_fk(owned_namespace):
    client, namespace_id, _, _ = owned_namespace
    assert client.put(f"/api/pm/namespace-ownership/{namespace_id}", headers=PAT, json=PAYLOAD).status_code == 201
    with SAUnitOfWork() as uow:
        namespace = uow.projects.get_by_id(namespace_id)
        other = uow.projects.create({"code": "OTHER", "name": "OTHER", "workflow_id": namespace.workflow_id,
                                     "cli_command": "other"})
        with pytest.raises(IntegrityError):
            uow.projects.create_pm_ownership({**PAYLOAD, "namespace_id": other, "ownership_ref": str(uuid4()),
                                               "authority_issuer": ISSUER, "provisioner_subject": SUBJECT})
        uow.rollback()
        with pytest.raises(IntegrityError):
            uow.projects.delete(namespace_id)
            uow.session.flush()
        uow.rollback()


def test_missing_and_non_pm_namespaces_cannot_be_provisioned(owned_namespace):
    client, namespace_id, _, identity = owned_namespace
    url = f"/api/pm/namespace-ownership/{namespace_id}"
    assert client.get(url, headers=PAT).status_code == 404
    assert client.get("/api/pm/namespace-ownership/0", headers=PAT).status_code == 422
    assert client.put("/api/pm/namespace-ownership/9999", headers=PAT, json=PAYLOAD).status_code == 404
    with SAUnitOfWork() as uow:
        namespace = uow.projects.get_by_id(namespace_id)
        other = uow.projects.create({"code": "OTHER", "name": "OTHER", "workflow_id": namespace.workflow_id,
                                     "cli_command": "other"})
    assert client.put(f"/api/pm/namespace-ownership/{other}", headers=PAT, json=PAYLOAD).status_code == 409




def test_existing_enrollment_is_not_implicitly_backfilled_or_reowned(pm):
    with SAUnitOfWork() as uow:
        namespace_id = uow.projects.get_by_cli_command("workflow-project_manager").id
        uow.session.execute(delete(m.PMNamespaceOwnership))
    with SAUnitOfWork() as uow:
        with pytest.raises(ConflictError, match="Existing PM enrollment"):
            NamespaceOwnershipService(uow).provision(namespace_id, NamespaceOwnershipRequest.model_validate(PAYLOAD),
                                                      NamespacePrincipal(ISSUER, SUBJECT))
        assert uow.projects.get_pm_ownership(namespace_id) is None
    from project_workflow.application.pm_execution import PMExecutionService
    from project_workflow.domain.pm_execution import PMIdentity

    with SAUnitOfWork() as uow:
        result = PMExecutionService(uow).readback(PMIdentity.model_validate(pm[1]), namespace_id, None)
        assert result["identity"]["execution_ref"] == pm[1]["execution_ref"]
        assert result["workflow_step_allowed"] is False




def test_ownership_wire_is_generated_and_not_dispatch_admission(owned_namespace):
    schema = create_app().openapi()
    path = schema["paths"]["/api/pm/namespace-ownership/{namespace_id}"]
    assert {"get", "put"} <= set(path)
    request = schema["components"]["schemas"]["NamespaceOwnershipRequest"]
    assert set(request["required"]) == set(PAYLOAD)
    assert request["additionalProperties"] is False
    assert request["properties"]["tracker_project_ref"]["not"]["const"].startswith("00000000")
    assert request["properties"]["tracker_instance_ref"]["x-max-utf8-bytes"] == 128
    assert not any("admit" in path or "prepare" in path for path in schema["paths"])
