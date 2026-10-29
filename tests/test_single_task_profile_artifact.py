"""Hash/provenance checks for the canonical installed profile artifacts."""

import hashlib
import json

import pytest

from project_workflow import config
from project_workflow.domain.namespace import legacy_code_from_cli_command, normalize_namespace_cli_command
from project_workflow.infrastructure.db.managed_catalog import ManagedCatalog, ManagedMode
from scripts import build_single_task_profile as builder
from scripts.build_single_task_profile import CATALOG_PATH, MANIFEST_PATH, ROOT, encoded, render


def test_profile_matches_actual_source_and_committed_artifact_hashes():
    catalog_bytes, manifest_bytes = render()
    assert (ROOT / CATALOG_PATH).read_bytes() == catalog_bytes
    assert (ROOT / MANIFEST_PATH).read_bytes() == manifest_bytes
    catalog, manifest = json.loads(catalog_bytes), json.loads(manifest_bytes)
    assert manifest["proposal"] is False
    assert manifest["workflow_catalog"]["sha256"] == hashlib.sha256(catalog_bytes).hexdigest()
    assert manifest["instruction_source"] == catalog["instruction_source"]
    assert catalog["catalog_version"] == manifest["workflow_catalog"]["version"] == 1
    assert manifest["task_identity"] == {
        "task_equals_root": True, "children": False, "decomposition_barriers": False,
    }
    for workflow in catalog["workflows"]:
        role = manifest["roles"][workflow["role_key"]]
        expected = hashlib.sha256(encoded(workflow["modes"], canonical=True)).hexdigest()
        assert role["role_instructions_sha256"] == expected
        assert role["profile"] == workflow["namespace"]["launch_profile"]
        assert all(m["key"] not in {"integration", "integration_rework"} for m in workflow["modes"])
        for mode in workflow["modes"]:
            ManagedMode.model_validate(mode)


def test_new_profile_identities_cannot_impersonate_legacy_or_base_metadata():
    catalog_bytes, manifest_bytes = render()
    catalog, manifest = json.loads(catalog_bytes), json.loads(manifest_bytes)
    legacy = json.loads(config.MANAGED_CATALOG_PATH.read_text(encoding="utf-8"))
    assert len(catalog["workflows"]) == len(manifest["roles"]) == 7
    assert sum(len(w["modes"]) for w in catalog["workflows"]) == 8
    assert sum(len(m["phases"]) for w in catalog["workflows"] for m in w["modes"]) == 24
    assert {w["key"] for w in legacy["workflows"]}.isdisjoint(w["key"] for w in catalog["workflows"])
    codes = set()
    for workflow in catalog["workflows"]:
        namespace = workflow["namespace"]
        assert workflow["key"].startswith("single-task-v1:")
        assert namespace["launch_profile"].startswith("single-task-v1-")
        assert normalize_namespace_cli_command(namespace["cli_command"]) == namespace["cli_command"]
        codes.add(legacy_code_from_cli_command(namespace["cli_command"]))
    assert len(codes) == 7
    assert manifest["roles"]["devops"]["fleet_role"] == "dev_ops"
    assert all(r["fleet_role"] == role for role, r in manifest["roles"].items() if role != "devops")
    for forbidden in ("package_commit", "skills_revision", "hermes_namespace", "hermes_profile"):
        assert forbidden not in catalog_bytes.decode() and forbidden not in manifest_bytes.decode()
    # The existing public catalog parser must not silently accept the separate single-task schema.
    with pytest.raises(ValueError):
        ManagedCatalog.model_validate(catalog)


def test_moving_instruction_source_cannot_be_misattributed_to_the_frozen_commit(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    source = tmp_path / builder.SOURCE_PATH
    source.parent.mkdir(parents=True)
    source.write_bytes(b"different instructions")
    with pytest.raises(ValueError, match="differs from declared source commit"):
        builder.render()
