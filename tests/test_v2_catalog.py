from __future__ import annotations

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

    assert catalog.resolve_route("feature", "D03", "change-scope") == "F05"
    assert catalog.resolve_route("bug", "D03", "change-scope") == "B06"
