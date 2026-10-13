"""Explicit source-only export, including private pin validation without copying it."""

import copy
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.application import base_source
from project_workflow.application.state import _app_state
from project_workflow.domain.base_admission import BASE_SKILLS_REVISION
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog, load_managed_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from tests.base_candidate.test_machine_readers import CATALOG_READER, READER
from tests.base_candidate.test_machine_readers import registered_readers as registered_readers

CATALOG = "/internal/runtime/base/source-catalog"
CAPABILITY = "/internal/runtime/base/source-capabilities"
TOKEN = "source-catalog-" + "c" * 32
RUNTIME_TOKEN = "source-runtime-" + "r" * 32


@pytest.fixture
def source(monkeypatch, tmp_path):
    catalog = load_managed_catalog(base_source.CANDIDATE_PATH)
    manifest = {"roles": {
        workflow.role_key: {
            "namespace": workflow.hermes_namespace, "profile": workflow.hermes_profile,
            "modes": [mode.key for mode in workflow.modes], "physicalSkills": workflow.skill_allowlist,
            "roleInstruction": {"sha256": "d" * 64},
        }
        for workflow in catalog.workflows
    }}
    manifest["sources"] = {"native": {"skills": {
        skill: "e" * 64 for workflow in catalog.workflows for skill in workflow.skill_allowlist
    }}}
    monkeypatch.setattr(base_source, "load_pinned_package", lambda *_: manifest)
    monkeypatch.setattr(base_source.GitPackage, "read", lambda *_: b"synthetic manifest")
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_SKILLS_ROOT", str(tmp_path / "agent-skills"))
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", TOKEN)
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"developer": RUNTIME_TOKEN}))
    config.get_settings.cache_clear()
    return manifest


def test_export_preserves_exact_7_11_33_source_without_legacy_runtime_claims(source):
    exported = base_source.export_base_source()
    assert exported["sourceOnly"] is True and exported["runtimeReady"] is False
    assert exported["catalogVersion"] == 3
    assert exported["workflowCatalogRevision"] == base_source.CANDIDATE_REVISION
    assert exported["workflowCatalogGitBlob"] == base_source.CANDIDATE_BLOB
    assert exported["skillsCatalogRevision"] == BASE_SKILLS_REVISION
    assert len(exported["skillsSha256"]) == 14
    assert len(exported["roles"]) == 7
    assert sum(len(role["modes"]) for role in exported["roles"].values()) == 11
    assert sum(len(phases) for phases in exported["phaseSets"].values()) == 33
    assert [mode["key"] for mode in exported["roles"]["developer"]["modes"]] == ["initial", "rework"]
    assert exported["roles"]["developer"]["modes"][0]["execution_scopes"] == ["delivery", "aggregate"]
    assert exported["rolesSha256"] == payload_sha256(exported["roles"])
    assert exported["phaseSetsSha256"] == payload_sha256(exported["phaseSets"])
    assert exported["sourceSha256"] == payload_sha256({k: v for k, v in exported.items() if k != "sourceSha256"})
    assert exported["owners"]["assignment"] == "task-tracker"
    forbidden = {"runtimeCapabilities", "runtimeCompatibility", "businessRoutingRegistry", "phaseSetsFrom"}
    assert not forbidden & exported.keys()
    assert "roleInstruction" not in json.dumps(exported["roles"]["developer"]).replace("roleInstructionSha256", "")
    assert load_managed_catalog().catalog_version == 2


def test_installed_directory_ids_are_not_base_namespace_symbols(source):
    # Isolated pytest SQLite only; no candidate adoption or runtime DB install.
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow)
        uow.commit()
    with TestClient(create_app()) as client:
        response = client.get("/internal/runtime/catalog", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200, response.text
    directory = response.json()
    workflow = next(item for item in directory["workflows"] if item["key"] == "hermes-sdlc:developer")
    namespace = next(item for item in directory["namespaces"] if item["cli_command"] == "workflow-developer")
    role = base_source.export_base_source()["roles"]["developer"]
    assert type(namespace["id"]) is int and namespace["id"] > 0
    assert namespace["namespace_id"] == namespace["id"]
    assert namespace["name"] == namespace["namespace_name"] == role["namespace"] == "hermes-developer"
    assert namespace["namespace_id"] != role["namespace"]
    assert namespace["workflow_id"] == workflow["id"]
    assert workflow["key"] == role["workflow"]
    assert role["profile"] == "hermes-sdlc-developer"
    assert "hermes_profile" not in namespace and "hermes_profile" not in workflow
    assert load_managed_catalog().catalog_version == 2


def test_source_http_endpoints_require_scopes_and_do_not_open_database(source, registered_readers, monkeypatch):
    client = TestClient(create_app())
    database = Mock(side_effect=AssertionError("Source route opened a database"))
    monkeypatch.setattr(type(_app_state), "create_uow", database)
    for path in (CATALOG, CAPABILITY):
        assert client.get(path).status_code == 401
    runtime = {"Authorization": f"Bearer {RUNTIME_TOKEN}"}
    assert client.get(CATALOG, headers=runtime).status_code == 401
    assert client.get(CATALOG, headers=READER).status_code == 403
    response = client.get(CATALOG, headers=CATALOG_READER)
    assert response.status_code == 200, response.text
    capability = client.get(CAPABILITY, headers=READER)
    assert capability.status_code == 200, capability.text
    value = capability.json()["capability"]
    assert value["runtime_ready"] is False and value["source_only"] is True
    assert value["source_sha256"] == response.json()["catalog"]["sourceSha256"]
    assert "generic-base-checkpoint-ack" in value["unavailable"]
    database.assert_not_called()
    client.close()


@pytest.mark.parametrize("field,value", [
    ("modes", ["delivery"]), ("physicalSkills", []), ("profile", "foreign"), ("namespace", "foreign"),
])
def test_export_refuses_mismatched_private_role_metadata(source, field, value):
    source["roles"]["developer"][field] = value
    with pytest.raises(ValueError, match="Pinned role/mode/allowlist"):
        base_source.export_base_source()


def test_export_refuses_changed_source_blob(source, monkeypatch, tmp_path):
    candidate = json.loads(base_source.CANDIDATE_PATH.read_text(encoding="utf-8"))
    changed = copy.deepcopy(candidate)
    changed["workflows"][0]["description"] = "Changed candidate"
    path = tmp_path / "candidate.json"
    # Test data only; the application never rewrites the source or default catalog.
    path.write_text(json.dumps(changed), encoding="utf-8")
    monkeypatch.setattr(base_source, "CANDIDATE_PATH", path)
    with pytest.raises(ValueError, match="pinned source Git blob"):
        base_source.export_base_source()


def test_unconfigured_package_returns_not_ready_not_legacy_fallback(source, registered_readers, monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_SKILLS_ROOT", "")
    config.get_settings.cache_clear()
    with TestClient(create_app()) as client:
        response = client.get(CATALOG, headers=CATALOG_READER)
        assert response.status_code == 503, response.text
        assert "catalog" not in response.json()


@pytest.mark.skipif(not os.environ.get("WORKFLOW_BASE_PACKAGE_TEST_ROOT"), reason="Private package is explicit opt-in")
def test_real_private_git_package_source_export_without_install(monkeypatch):
    root = Path(os.environ["WORKFLOW_BASE_PACKAGE_TEST_ROOT"])
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_SKILLS_ROOT", str(root))
    config.get_settings.cache_clear()
    result = base_source.export_base_source()
    assert result["skillsCatalogRevision"] == BASE_SKILLS_REVISION
    assert result["sourceOnly"] is True and result["runtimeReady"] is False
    assert load_managed_catalog().catalog_version == 2
    catalog = load_managed_catalog(base_source.CANDIDATE_PATH)
    manifest = base_source.load_pinned_package(root, catalog.skills_source)
    raw = base_source.GitPackage(root.resolve().parent, BASE_SKILLS_REVISION).read("manifest.json")
    assert manifest == json.loads(raw)
