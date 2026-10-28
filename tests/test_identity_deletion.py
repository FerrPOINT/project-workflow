"""Protocol and fresh Auth wire boundaries; PG effects are a separate gate."""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from project_workflow import config
from project_workflow.domain.identity_deletion import DeletionRequest, ReferenceSummary
from project_workflow.infrastructure.db.identity_deletion import OwnerError, execute
from project_workflow.infrastructure.identity_deletion_auth import Authority, authorize
from project_workflow.interfaces.ui.app import create_app

ISSUER = "https://auth.example.test"
COORDINATOR = "00000000-0000-4000-8000-000000000001"


def command():
    return {"schema_version": 1, "operation_id": str(uuid4()), "inventory_revision": str(uuid4()),
            "identity": {"issuer": ISSUER, "subject": str(uuid4())}}


@pytest.mark.parametrize("change", [
    {"schema_version": True}, {"schema_version": "1"}, {"schema_version": 2},
    {"operation_id": str(uuid4()).replace("-", "x")}, {"inventory_revision": str(uuid4()).replace("-", "x")},
    {"operation_id": "00000000-0000-0000-0000-000000000000"}, {"extra": "ignored?"},
    {"identity": {"issuer": ISSUER, "subject": "not-a-central-id"}},
])
def test_strict_protocol(change):
    with pytest.raises(ValidationError):
        DeletionRequest.model_validate(command() | change)


def test_original_proof_never_renews(monkeypatch):
    proof = Authority(ISSUER, time.monotonic() + 2, time.time() - 1, time.time() + 2)
    assert proof.current()
    monkeypatch.setattr(time, "monotonic", lambda: proof.deadline + 0.1)
    assert not proof.current()


def wire(monkeypatch, payload, *, status=200, location=None):
    monkeypatch.setenv("AUTH_ISSUER", ISSUER)
    monkeypatch.setenv("AUTH_INTERNAL_BASE_URL", "http://auth.internal.test")
    monkeypatch.setenv("PROJECT_WORKFLOW_IDENTITY_DELETION_COORDINATOR_SUBJECTS", COORDINATOR)
    config.get_settings.cache_clear()
    original = httpx.AsyncClient
    calls = []

    def respond(request):
        calls.append(request)
        assert str(request.url) == "http://auth.internal.test/auth/tokens/introspect?include_lifetime=true"
        return httpx.Response(status, json=payload, headers={"Location": location} if location else {})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(respond)))
    return calls


def introspection():
    now = datetime.now(timezone.utc)
    return {"sub": COORDINATOR, "email": "fixture@example.test", "display_name": "Fixture coordinator",
            "scopes": ["project-workflow:identity-lifecycle"],
            "role": "service_account", "subject_role": "service_account",
            "observed_at": now.isoformat(), "expires_at": (now + timedelta(minutes=5)).isoformat()}


@pytest.mark.parametrize("change,status", [({}, 200), ({"role": "admin", "subject_role": "admin"}, 403),
    ({"role": "user", "subject_role": "user"}, 403),
    ({"role": "admin"}, 503), ({"subject_role": "admin"}, 503),
    ({"scopes": ["project-workflow:write"]}, 403), ({"sub": str(uuid4())}, 403),
    ({"expires_at": datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()}, 401),
    ({"secretish_extra": "must not pass"}, 503)])
def test_actual_auth_wire_fresh_machine_matrix(monkeypatch, change, status):
    calls = wire(monkeypatch, introspection() | change)
    if status == 200:
        proof = asyncio.run(authorize("Bearer pdlc_pat_fixture", time.monotonic() + 9))
        assert proof.current() and proof.issuer == ISSUER
    else:
        with pytest.raises(OwnerError) as rejected:
            asyncio.run(authorize("Bearer pdlc_pat_fixture", time.monotonic() + 9))
        assert rejected.value.status == status
        assert "must not pass" not in str(rejected.value)
    assert len(calls) == 1


@pytest.mark.parametrize("field", ["role", "subject_role"])
@pytest.mark.parametrize("invalid", [None, True, 1, {}, [], "", "service_account ", "platform_admin"])
def test_canonical_introspection_rejects_malformed_principal_kind(monkeypatch, field, invalid):
    calls = wire(monkeypatch, introspection() | {field: invalid})
    with pytest.raises(OwnerError) as rejected:
        asyncio.run(authorize("Bearer pdlc_pat_fixture", time.monotonic() + 9))
    assert rejected.value.status == 503
    assert len(calls) == 1


@pytest.mark.parametrize("field", ["role", "subject_role"])
def test_canonical_introspection_requires_both_current_role_fields(monkeypatch, field):
    payload = introspection()
    del payload[field]
    calls = wire(monkeypatch, payload)
    with pytest.raises(OwnerError) as rejected:
        asyncio.run(authorize("Bearer pdlc_pat_fixture", time.monotonic() + 9))
    assert rejected.value.status == 503 and len(calls) == 1


def human_introspection(role):
    payload = introspection() | {"role": role, "subject_role": role}
    payload["application_access"] = {
        "schema_version": 1, "issuer": ISSUER, "subject": COORDINATOR, "role": role,
        "applications": ["project-workflow"], "revision": 3, "enforced": True,
        "observed_at": payload["observed_at"],
        "expires_at": (datetime.fromisoformat(payload["observed_at"]) + timedelta(seconds=30)).isoformat(),
    }
    return payload


@pytest.mark.parametrize("role", ["user", "admin"])
def test_actual_human_pat_with_canonical_application_metadata_never_becomes_coordinator(monkeypatch, role):
    calls = wire(monkeypatch, human_introspection(role))
    with pytest.raises(OwnerError) as rejected:
        asyncio.run(authorize("Bearer pdlc_pat_fixture", time.monotonic() + 9))
    assert rejected.value.status == 403 and len(calls) == 1


@pytest.mark.parametrize("change", [
    {"role": "user"}, {"subject": str(uuid4())}, {"issuer": "https://different.example.test"},
    {"secretish_extra": "must not pass"},
])
def test_application_metadata_must_not_contradict_canonical_principal(monkeypatch, change):
    payload = human_introspection("admin")
    payload["application_access"].update(change)
    wire(monkeypatch, payload)
    with pytest.raises(OwnerError) as rejected:
        asyncio.run(authorize("Bearer pdlc_pat_fixture", time.monotonic() + 9))
    assert rejected.value.status == 503


def test_service_principal_cannot_carry_a_forged_human_application_proof(monkeypatch):
    payload = introspection() | {"application_access": human_introspection("admin")["application_access"]}
    wire(monkeypatch, payload)
    with pytest.raises(OwnerError) as rejected:
        asyncio.run(authorize("Bearer pdlc_pat_fixture", time.monotonic() + 9))
    assert rejected.value.status == 503


def test_jwt_never_substitutes_and_redirect_is_not_followed(monkeypatch):
    calls = wire(monkeypatch, {}, status=302, location="http://collector.invalid/credential")
    with pytest.raises(OwnerError) as rejected:
        asyncio.run(authorize("Bearer fake.jwt.value", time.monotonic() + 9))
    assert rejected.value.status == 403 and not calls
    with pytest.raises(OwnerError) as rejected:
        asyncio.run(authorize("Bearer pdlc_pat_fixture", time.monotonic() + 9))
    assert rejected.value.status == 503 and len(calls) == 1


def test_actual_router_private_contract_no_store_and_no_human_sso(monkeypatch):
    from project_workflow.interfaces.ui.routes import identity_deletion_api as route
    wire(monkeypatch, introspection())
    monkeypatch.setenv("AUTH_SESSION_SECRET", "fixture-signing-secret-32-characters-long")
    config.get_settings.cache_clear()
    effects = []

    def effect(action, request, authority):
        assert isinstance(authority, Authority) and authority.current()
        effects.append(action)
        return ReferenceSummary(request=request, revision=1, reference_count=0)

    monkeypatch.setattr(route, "execute", effect)
    body = command()
    url = f"/api/internal/v1/user-deletions/{body['operation_id']}/check"
    with TestClient(create_app()) as client:
        good = client.post(url, json=body, headers={"Authorization": "Bearer pdlc_pat_fixture"})
        assert good.status_code == 200 and good.json()["fencing_supported"] is True
        for response in [client.get(url), client.post(url, content="{"),
                         client.post(url, content="x" * 16385),
                         client.post(url, json=body | {"operation_id": str(uuid4())}),
                         client.post(url, json=body, headers={"Authorization": "Bearer fake.jwt.value"})]:
            assert response.status_code in {401, 403, 405, 413, 422}
            assert response.headers["cache-control"] == "no-store"
        assert good.headers["cache-control"] == "no-store" and effects == ["check"]


def test_sqlite_never_claims_product_fencing(monkeypatch):
    monkeypatch.setenv("AUTH_ISSUER", ISSUER)
    monkeypatch.setenv("PROJECT_WORKFLOW_IDENTITY_LEGACY_ISSUER", ISSUER)
    config.get_settings.cache_clear()
    with pytest.raises(OwnerError) as rejected:
        execute("freeze", DeletionRequest.model_validate(command()),
                Authority(ISSUER, time.monotonic() + 30, time.time() - 1, time.time() + 30))
    assert rejected.value.status == 503


def test_actual_router_overall_timeout_never_reaches_effect(monkeypatch):
    from project_workflow.interfaces.ui.routes import identity_deletion_api as route
    effects = []

    async def delayed_authority(*args):
        await asyncio.sleep(12)
        raise AssertionError("Overall deadline must cancel this wait")

    monkeypatch.setattr(route, "authorize", delayed_authority)
    monkeypatch.setattr(route, "execute", lambda *args: effects.append(args))
    body = command()
    with TestClient(create_app()) as client:
        result = client.post(f"/api/internal/v1/user-deletions/{body['operation_id']}/check", json=body)
    assert result.status_code == 503 and result.headers["cache-control"] == "no-store"
    assert not effects


@pytest.mark.parametrize("issuer", [ISSUER + "/", ISSUER + "/identity-provider/"])
def test_authority_preserves_exact_configured_issuer(monkeypatch, issuer):
    wire(monkeypatch, introspection())
    monkeypatch.setenv("AUTH_ISSUER", issuer)
    config.get_settings.cache_clear()
    proof = asyncio.run(authorize("Bearer pdlc_pat_fixture", time.monotonic() + 9))
    assert proof.issuer == issuer



@pytest.mark.parametrize("predecessor", ["0016_human_project_commit_guard", "0017_human_application_clock"])
def test_supported_human_guard_predecessor_upgrades_without_recreating_history(tmp_path, predecessor):
    from sqlalchemy import create_engine, text

    from project_workflow.infrastructure.db.session import (
        database_revisions,
        ensure_migrated,
        run_alembic_command,
        schema_is_ready,
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'owner-predecessor.db'}")
    try:
        run_alembic_command("upgrade", engine, predecessor)
        subject = str(uuid4())
        with engine.begin() as connection:
            workflow = connection.execute(text("INSERT INTO workflows(key,name,is_default) "
                "VALUES('predecessor','Predecessor history',0) RETURNING id")).scalar_one()
            mode = connection.execute(text("INSERT INTO workflow_modes(workflow_id,key,name,mode_order) "
                "VALUES(:workflow,'mode','Mode',1) RETURNING id"), {"workflow": workflow}).scalar_one()
            connection.execute(text("INSERT INTO resource_execution_contexts("
                "id,operation_id,request,verified_projection,"
                "workflow_id,mode_id,created_by_subject) VALUES(:id,:operation,'{}','{}',:workflow,:mode,:subject)"),
                {"id": str(uuid4()), "operation": str(uuid4()), "workflow": workflow, "mode": mode, "subject": subject})
            before = connection.execute(text("SELECT * FROM resource_execution_contexts")).all()
        ensure_migrated(engine)
        assert database_revisions(engine) == {"0021_profession_task_workflows"}
        assert schema_is_ready(engine)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT * FROM resource_execution_contexts")).all() == before
    finally:
        engine.dispose()


def test_owner_registration_preserves_configuration_administrator_dependencies():
    from fastapi.routing import APIRoute

    from project_workflow.interfaces.ui.sso import require_administrator

    routes = [route for route in create_app().routes if isinstance(route, APIRoute)]
    for path, method in [("/instructions", "GET"), ("/api/workflows", "POST"),
                         ("/api/phases", "POST"), ("/api/namespaces/{namespace_id}", "PUT")]:
        route = next(route for route in routes if route.path == path and method in route.methods)
        assert any(dependency.call is require_administrator for dependency in route.dependant.dependencies)
    owner_route = next(route for route in routes
                       if route.path == "/api/internal/v1/user-deletions/{operation_id}/{action}")
    assert "POST" in owner_route.methods
    # This transport verifies its registered service PAT itself; a human-administration
    # dependency must not accidentally replace that distinct authority boundary.
    assert not any(dependency.call is require_administrator for dependency in owner_route.dependant.dependencies)


def test_transaction_receipt_uses_original_remaining_after_database_anchor_response(monkeypatch):
    from project_workflow.infrastructure.db.identity_deletion import _authorize_transaction

    clocks = {"monotonic": 100.0, "wall": datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp()}
    monkeypatch.setattr(time, "monotonic", lambda: clocks["monotonic"])
    monkeypatch.setattr(time, "time", lambda: clocks["wall"])
    proof = Authority(ISSUER, 110.0, clocks["wall"] - 1, clocks["wall"] + 5)
    anchor = datetime.fromtimestamp(clocks["wall"], timezone.utc)
    writes = []

    class Connection:
        def execute(self, statement, parameters=None):
            if str(statement) == "SELECT clock_timestamp()":
                clocks["monotonic"] += 3
                clocks["wall"] += 3

                class Result:
                    def scalar_one(self):
                        return anchor
                return Result()
            writes.append((str(statement), parameters))

    _authorize_transaction(Connection(), proof)
    assert writes[0][1]["until"] == anchor + timedelta(seconds=2)
    assert writes[0][1]["id"] == writes[1][1]["id"]
    assert proof.deadline == 110.0
    assert proof.remaining() == 2.0


@pytest.mark.parametrize("variant", ["uppercase", "compact", "braces"])
def test_subject_uuid_wire_forms_share_canonical_request_and_operation_identity(variant):
    subject = UUID("abcdefab-cdef-4abc-8def-123456789abc")
    payload = command()
    payload["identity"] = {"issuer": ISSUER + "/exact-issuer/", "subject": str(subject)}
    canonical = DeletionRequest.model_validate(payload)
    forms = {"uppercase": str(subject).upper(), "compact": subject.hex, "braces": "{" + str(subject) + "}"}
    alias = DeletionRequest.model_validate(payload | {
        "identity": payload["identity"] | {"subject": forms[variant]},
    })
    assert alias.identity.subject == str(subject)
    assert alias.identity.issuer == payload["identity"]["issuer"]
    assert alias.operation_id == canonical.operation_id
    assert alias.inventory_revision == canonical.inventory_revision
    assert alias == canonical
    assert alias.model_dump(mode="json") == canonical.model_dump(mode="json")
    assert alias.model_dump_json() == canonical.model_dump_json()


@pytest.mark.parametrize("subject", [str(UUID(int=0)), UUID(int=0).hex, "{" + str(UUID(int=0)) + "}"])
def test_nil_subject_wire_forms_remain_invalid(subject):
    payload = command()
    payload["identity"]["subject"] = subject
    with pytest.raises(ValidationError):
        DeletionRequest.model_validate(payload)
