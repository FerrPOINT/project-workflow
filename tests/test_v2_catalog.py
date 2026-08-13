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


def test_catalog_checksum_prevents_in_place_change(tmp_path):
    catalog = load_default_catalog()
    payload = json.loads(json.dumps(catalog.payload))
    payload["phases"][0]["purpose"] = "tampered"
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CatalogError, match="checksum mismatch"):
        WorkflowCatalogV2.load(path)


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
