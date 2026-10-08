"""Explicit Base catalog installation never enables the legacy execution bridge."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from project_workflow.build_provenance import BuildProvenanceError, validate_runtime_compatibility
from scripts import build_runtime_image as builder

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def base_input(tmp_path, monkeypatch):
    catalog = json.loads((ROOT / builder.BASE_CATALOG_PATH).read_text(encoding="utf-8"))
    target = tmp_path / builder.BASE_CATALOG_PATH
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(catalog), encoding="utf-8")
    manifest = {"schema": "base-hermes-role-skills/v1", "roles": {
        row["role_key"]: {"physicalSkills": row["skill_allowlist"]} for row in catalog["workflows"]
    }}
    (tmp_path / builder.SKILLS_MANIFEST_PATH).write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "runtime-build-manifest.json").write_text(json.dumps({
        "schema_version": 1, "source_revision": "a" * 40,
        "source_archive_sha256": "b" * 64, "runtime_bundle_sha256": "c" * 64,
    }), encoding="utf-8")
    monkeypatch.setenv("PROJECT_WORKFLOW_CATALOG_VARIANT", "base")
    return tmp_path, manifest


def test_base_descriptor_is_controlplane_not_legacy_execution(base_input):
    root, _ = base_input
    descriptor = builder.derive_compatibility(root)
    assert descriptor["catalogVersion"] == 3
    assert descriptor["capabilityRevision"] == "base-workflow-controlplane/v1"
    assert validate_runtime_compatibility(descriptor) == descriptor
    descriptor["capabilityRevision"] = "hermes-sdlc-runtime/v2"
    with pytest.raises(BuildProvenanceError, match="version"):
        validate_runtime_compatibility(descriptor)


def test_base_allowlist_cannot_expand(base_input):
    root, manifest = base_input
    manifest["roles"]["developer"]["physicalSkills"].append("foreign-skill")
    (root / builder.SKILLS_MANIFEST_PATH).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BuildProvenanceError, match="allowlist"):
        builder.derive_compatibility(root)


def test_unknown_variant_fails_closed(base_input, monkeypatch):
    root, _ = base_input
    monkeypatch.setenv("PROJECT_WORKFLOW_CATALOG_VARIANT", "unknown")
    with pytest.raises((BuildProvenanceError, FileNotFoundError)):
        builder.derive_compatibility(root)


def test_selector_keeps_legacy_default_and_explicit_base(monkeypatch):
    monkeypatch.delenv("PROJECT_WORKFLOW_CATALOG_VARIANT", raising=False)
    command = [sys.executable, "-c",
               "from project_workflow.config import MANAGED_CATALOG_PATH; print(MANAGED_CATALOG_PATH.name)"]
    assert subprocess.check_output(command, cwd=ROOT, text=True).strip() == "hermes_sdlc_catalog_v1.json"
    monkeypatch.setenv("PROJECT_WORKFLOW_CATALOG_VARIANT", "base")
    assert subprocess.check_output(command, cwd=ROOT, text=True).strip() == "base_sdlc_catalog_v1.json"


def test_base_execution_credentials_are_rejected(monkeypatch):
    from project_workflow.interfaces.ui.routes import runtime_api
    monkeypatch.setattr(runtime_api.config, "CATALOG_VARIANT", "base")
    monkeypatch.setattr(runtime_api, "_token_configuration", lambda: ({"developer": "a" * 32}, {}, ""))
    with pytest.raises(RuntimeError, match="not enabled"):
        runtime_api._authorized_service_credential("Bearer " + "a" * 32)
    monkeypatch.setattr(runtime_api, "_token_configuration", lambda: ({}, {}, "b" * 32))
    credential = runtime_api._authorized_service_credential("Bearer " + "b" * 32)
    assert credential is not None and credential.kind == "catalog"
