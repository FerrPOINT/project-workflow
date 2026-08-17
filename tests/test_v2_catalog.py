from __future__ import annotations

import hashlib
import json

import pytest

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


def test_jira_board_writes_are_limited_to_c08_and_x01_execution():
    catalog = load_default_catalog()

    write_instructions = [
        (phase_id, instruction["instructionId"])
        for phase_id, phase in catalog.phases.items()
        for instruction in phase["instructions"]
        if "jira-write" in instruction["allowedTools"]
    ]

    assert write_instructions == [("C08", "c08-02-execute"), ("X01", "x01-02-execute")]


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


def test_catalog_without_artifact_contract_is_rejected():
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
    catalog = WorkflowCatalogV2(payload)

    with pytest.raises(CatalogError, match="artifactSchemas"):
        catalog.validate()


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


def test_invalid_profile_route_is_rejected_without_runtime_correction():
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
    with pytest.raises(CatalogError, match="invalid route"):
        catalog.validate()
