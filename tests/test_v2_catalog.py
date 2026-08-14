from __future__ import annotations

import hashlib
import json

import pytest

from project_workflow.v2 import catalog as catalog_module
from project_workflow.v2.catalog import CatalogError, WorkflowCatalogV2, load_default_catalog


def test_agentic_sdlc_v2_catalog_exact_invariants():
    catalog = load_default_catalog()
    phases = catalog.phases

    assert len(phases) == 70
    assert len(catalog.path("feature")) == 60
    assert len(catalog.path("bug")) == 54
    assert sum(len(item["instructions"]) for item in phases.values()) == 318
    assert sum(len(item["checks"]) for item in phases.values()) == 248
    assert sum(len(item["evidenceRequirements"]) for item in phases.values()) == 178
    assert sum(bool(phases[item]["approvalRule"]) for item in catalog.path("feature")) == 5
    assert sum(bool(phases[item]["approvalRule"]) for item in catalog.path("bug")) == 5
    document_requirements = [
        requirement
        for phase in phases.values()
        for requirement in phase["evidenceRequirements"]
        if requirement["type"] == "document"
    ]
    assert document_requirements
    assert all(item["schemaRef"] in catalog.payload["artifactSchemas"] for item in document_requirements)
    assert all(item["policyRef"] in catalog.payload["artifactPolicies"] for item in document_requirements)
    assert phases["C05"]["evidenceRequirements"][0]["policyRef"] == "risk-classification/v1"


def test_phase_contract_contains_only_referenced_catalog_artifact_definitions():
    catalog = load_default_catalog()

    c05 = catalog.phase_contract("feature", "C05")
    c06 = catalog.phase_contract("feature", "C06")
    c08 = catalog.phase_contract("feature", "C08")

    assert set(c05["artifactSchemas"]) == {"agentic-sdlc-artifact/v1"}
    assert set(c05["artifactPolicies"]) == {"risk-classification/v1"}
    assert set(c06["artifactPolicies"]) == {"source-backed-claims/v1"}
    assert c08["artifactSchemas"] == {}
    assert c08["artifactPolicies"] == {}


def test_catalog_checksum_prevents_in_place_change(tmp_path):
    catalog = load_default_catalog()
    payload = json.loads(json.dumps(catalog.payload))
    payload["phases"][0]["purpose"] = "tampered"
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CatalogError, match="checksum mismatch"):
        WorkflowCatalogV2.load(path)


def test_catalog_rejects_document_evidence_without_catalog_owned_policy(tmp_path):
    payload = json.loads(json.dumps(load_default_catalog().payload))
    payload["phases"][4]["evidenceRequirements"][0].pop("policyRef")
    payload["catalogRevision"] = ""
    payload["catalogRevision"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CatalogError, match="requires schemaRef and policyRef"):
        WorkflowCatalogV2.load(path)


def test_pinned_legacy_catalog_without_artifact_contract_remains_loadable(monkeypatch):
    payload = json.loads(json.dumps(load_default_catalog().payload))
    payload.pop("artifactSchemas")
    payload.pop("artifactPolicies")
    for phase in payload["phases"]:
        for requirement in phase["evidenceRequirements"]:
            requirement.pop("schemaRef", None)
            requirement.pop("policyRef", None)
    payload["catalogRevision"] = ""
    payload["catalogRevision"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    monkeypatch.setattr(catalog_module, "LEGACY_CATALOG_REVISIONS", {payload["catalogRevision"]})

    catalog = WorkflowCatalogV2(payload)
    catalog.validate()

    assert catalog.phase_contract("feature", "C05")["artifactSchemas"] == {}


def test_relevanter_dev_pinned_catalog_revisions_are_explicitly_allowlisted():
    assert catalog_module.LEGACY_CATALOG_REVISIONS == {
        "da1530eb4559b75b971c09c82b2961f92e5dbea63a178dc8017d531efd781b03",
        "d84e36608275ad41a961d5a7be2df273bd9c0c00420146f3364dd433ce2ea76b",
    }


def test_common_failure_route_is_profile_specific():
    catalog = load_default_catalog()

    assert catalog.resolve_route("feature", "C01", "change-scope") == "F05"
    assert catalog.resolve_route("bug", "C01", "change-scope") == "B06"
    assert catalog.resolve_route("feature", "D03", "change-scope") == "F05"
    assert catalog.resolve_route("bug", "D03", "change-scope") == "B06"
    assert catalog.resolve_route("feature", "X01", "test-design-defect") == "F15"
    assert catalog.resolve_route("bug", "X01", "test-design-defect") == "B07"
    assert catalog.resolve_route("feature", "D03", "architecture-defect") == "F12"
    assert catalog.resolve_route("bug", "D03", "architecture-defect") == "B08"
    contract = catalog.phase_contract("feature", "C01")
    assert contract["failureRoutes"]["change-scope"] == "F05"
    assert all(isinstance(route, str) for route in contract["failureRoutes"].values())


def test_first_published_catalog_common_routes_remain_compatible():
    payload = json.loads(json.dumps(load_default_catalog().payload))
    routes = payload["phases"][0]["failureRoutes"]
    routes["change-scope"] = "B06"
    routes["architecture-defect"] = "F12"
    routes["threat-model-defect"] = "F13"
    routes["test-design-defect"] = "B07"
    payload["catalogRevision"] = ""
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    payload["catalogRevision"] = hashlib.sha256(canonical).hexdigest()

    catalog = WorkflowCatalogV2(payload)
    catalog.validate()
    assert catalog.phase_contract("feature", "C01")["failureRoutes"]["change-scope"] == "F05"
    assert catalog.phase_contract("feature", "C01")["failureRoutes"]["test-design-defect"] == "F15"
    assert catalog.phase_contract("bug", "C01")["failureRoutes"]["architecture-defect"] == "B08"
    assert catalog.phase_contract("bug", "C01")["failureRoutes"]["threat-model-defect"] == "B05"
