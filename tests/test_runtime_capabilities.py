"""Current capability discovery: one execution protocol, truthful immutable inputs."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from project_workflow import build_provenance, config
from project_workflow.domain.single_task_profile import CATALOG_SHA256, MANIFEST_SHA256
from project_workflow.infrastructure import namespace_auth
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db import session as db_session
from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app

REVISION = "d9ebcff84068406ba4b09ae037dac53b5b6296ba"
ROLES = ["project_manager", "analyst", "architect", "developer", "reviewer", "tester", "devops"]
ASSIGNMENT, RUNTIME, CATALOG = "sdlc_pat_controller-" + "x" * 40, "runtime-" + "y" * 40, "catalog-" + "z" * 40
CONTROLLER = "99999999-9999-4999-8999-999999999999"


def headers(token):
    return {"Authorization": "Bearer " + token}


def configure(monkeypatch, role="developer", *, subjects=None, catalog=CATALOG):
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_READER_SUBJECTS_JSON", json.dumps(
        {CONTROLLER: role} if subjects is None else subjects))
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", catalog)
    config.get_settings.cache_clear()

    def introspect(authorization, *, require_service_account=False):
        assert require_service_account
        if authorization != headers(ASSIGNMENT)["Authorization"]:
            raise namespace_auth.NamespaceAuthError(401)
        return namespace_auth.NamespacePrincipal("https://auth.test", CONTROLLER), [
            "project-workflow:read", "project-workflow:write"]
    monkeypatch.setattr(namespace_auth, "introspect", introspect)


def manifest():
    return {"schema_version": 1, "source_revision": REVISION,
            "source_archive_sha256": "a" * 64, "runtime_bundle_sha256": "b" * 64}


@pytest.fixture
def discovery(monkeypatch, tmp_path):
    monkeypatch.setattr(db_session, "schema_is_ready", lambda _engine: True)
    path = tmp_path / "runtime-build-manifest.json"
    path.write_text(json.dumps(manifest()), encoding="utf-8")
    monkeypatch.setattr(build_provenance, "DEFAULT_BUILD_MANIFEST_PATH", path)
    configure(monkeypatch)
    with SAUnitOfWork() as uow:
        ensure_single_task_catalog(uow)
    with TestClient(create_app()) as client:
        yield client, path


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("variant", ["base", "single-task-v1"])
def test_current_capabilities_are_role_scoped_in_both_catalog_images(discovery, monkeypatch, role, variant):
    client, _ = discovery
    configure(monkeypatch, role)
    monkeypatch.setattr(config, "CATALOG_VARIANT", variant)
    response = client.get("/internal/runtime/capabilities", headers=headers(ASSIGNMENT))
    assert response.status_code == 200, response.text
    assert response.json() == {
        "ok": True, "role_key": role, "credential_kind": "assignment",
        "interaction_protocol": "configured-cli-v1", "capabilities": ["assign", "history", "terminal-readback"],
        "readiness": {"service": "ready", "schema": "ready", "catalog": "ready"},
        "source_provenance": manifest(), "instruction_profile": "single-task-v1",
        "instruction_manifest_sha256": MANIFEST_SHA256, "workflow_catalog_sha256": CATALOG_SHA256,
    }
    assert ASSIGNMENT not in response.text


@pytest.mark.parametrize("token,status", [("", 401), ("wrong", 401), (RUNTIME, 401), (CATALOG, 403)])
def test_only_the_configured_role_reader_can_discover_execution(discovery, token, status):
    client, _ = discovery
    response = client.get("/internal/runtime/capabilities", headers=headers(token))
    assert response.status_code == status
    assert "capabilities" not in response.json()


@pytest.mark.parametrize("subjects", [{CONTROLLER: "unknown"}, {"not-a-uuid": "developer"}, {}])
def test_invalid_registration_cannot_discover_execution(discovery, monkeypatch, subjects):
    client, _ = discovery
    configure(monkeypatch, subjects=subjects)
    response = client.get("/internal/runtime/capabilities", headers=headers(ASSIGNMENT))
    assert response.status_code == 503
    assert ASSIGNMENT not in response.text


@pytest.mark.parametrize("invalid", [None, {}, {**manifest(), "source_revision": "unknown"},
                                     {**manifest(), "runtime_bundle_sha256": "A" * 64},
                                     {**manifest(), "extra": "not-allowed"}])
def test_invalid_build_provenance_never_advertises_ready(discovery, invalid):
    client, path = discovery
    if invalid is None:
        path.unlink()
    else:
        path.write_text(json.dumps(invalid), encoding="utf-8")
    response = client.get("/internal/runtime/capabilities", headers=headers(ASSIGNMENT))
    assert response.status_code == 503
    assert response.json()["readiness"] == {"service": "not_ready", "schema": "ready", "catalog": "ready"}
    assert "source_provenance" not in response.json()


@pytest.mark.parametrize("failure", ["schema", "exception", "drift"])
def test_unready_schema_or_drifted_catalog_is_not_masked(discovery, monkeypatch, failure):
    client, _ = discovery
    if failure == "drift":
        with SAUnitOfWork() as uow:
            installation = ensure_single_task_catalog(uow)
            phase = int(installation.bindings[0].modes[0].phase_ids[0])
            instruction = uow.phase_instructions.list(phase)[0]
            uow.phase_instructions.update(instruction["id"], {"description": "drift"})
            uow.commit()
    elif failure == "schema":
        monkeypatch.setattr(db_session, "schema_is_ready", lambda _: False)
    else:
        def broken(_):
            raise RuntimeError("private-connection-detail")
        monkeypatch.setattr(db_session, "schema_is_ready", broken)
    response = client.get("/internal/runtime/capabilities", headers=headers(ASSIGNMENT))
    assert response.status_code == 503
    assert response.json()["readiness"]["catalog"] == "not_ready"
    assert "capabilities" not in response.json()
    assert "private-connection-detail" not in response.text


def test_observation_does_not_mutate_catalog_or_tasks(discovery):
    client, _ = discovery
    def snapshot():
        with SAUnitOfWork() as uow:
            return (uow.session.scalar(select(func.count()).select_from(m.Task)),
                    list(uow.session.execute(m.Workflow.__table__.select().order_by(m.Workflow.id)).all()))
    before = snapshot()
    assert client.get("/internal/runtime/capabilities", headers=headers(ASSIGNMENT)).status_code == 200
    assert snapshot() == before


# Shared artifact fixtures for retained catalog/history tests. These never admit
# the retired native execution protocol through the current API.
def _valid_manifest():
    return manifest()


def _valid_compatibility():
    return {"catalogVersion": 2, "catalogRevision": REVISION, "catalogSha256": "b" * 64,
            "skillsRevision": "c" * 40, "skillsManifestSha256": "d" * 64,
            "capabilityRevision": "hermes-sdlc-runtime/v2", "capabilitySha256": "e" * 64}


def _install_manifest(monkeypatch, tmp_path, value=None):
    path = tmp_path / "runtime-build-manifest.json"
    if value is not None:
        path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(build_provenance, "DEFAULT_BUILD_MANIFEST_PATH", path)
    descriptor = tmp_path / "runtime-compatibility.json"
    descriptor.write_text(json.dumps(_valid_compatibility()), encoding="utf-8")
    reader = build_provenance.runtime_compatibility_descriptor
    monkeypatch.setattr(build_provenance, "runtime_compatibility_descriptor",
                        lambda **kwargs: reader(descriptor, **kwargs))
    return path
