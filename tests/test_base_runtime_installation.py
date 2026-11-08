"""One configured build path; retained Base artifacts never enable execution."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from project_workflow.build_provenance import BuildProvenanceError, validate_runtime_compatibility
from project_workflow.domain.single_task_profile import CATALOG_SHA256, MANIFEST_SHA256
from scripts import build_runtime_image as builder

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def configured_input(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_CATALOG_VARIANT", "single-task-v1")
    monkeypatch.delenv("PROJECT_WORKFLOW_BUILD_MEMORY_MIB", raising=False)
    monkeypatch.delenv("PROJECT_WORKFLOW_BUILD_CPUS", raising=False)
    references = tmp_path / "project_workflow/references"
    references.mkdir(parents=True)
    for filename in ("single_task_catalog_v1.json", "single_task_manifest_v1.json"):
        (references / filename).write_bytes((ROOT / "project_workflow/references" / filename).read_bytes())
    (tmp_path / "runtime-build-manifest.json").write_text(json.dumps({
        "schema_version": 1, "source_revision": "a" * 40,
        "source_archive_sha256": "b" * 64, "runtime_bundle_sha256": "c" * 64,
    }), encoding="utf-8")
    descriptor = builder.derive_compatibility(tmp_path)
    assert descriptor["catalogVersion"] == 1
    assert descriptor["capabilityRevision"] == "configured-workflow-cli/v1"
    assert descriptor["catalogSha256"] == CATALOG_SHA256
    assert descriptor["instructionManifestSha256"] == MANIFEST_SHA256
    assert validate_runtime_compatibility(descriptor) == descriptor
    return tmp_path, descriptor


def test_current_descriptor_has_no_native_skills_bootstrap(configured_input):
    _, descriptor = configured_input
    assert "skillsRevision" not in descriptor
    assert "skillsManifestSha256" not in descriptor
    invalid = {**descriptor, "capabilityRevision": "base-workflow-controlplane/v1"}
    with pytest.raises(BuildProvenanceError, match="schema"):
        validate_runtime_compatibility(invalid)


@pytest.mark.parametrize("filename", ["single_task_catalog_v1.json", "single_task_manifest_v1.json"])
def test_current_profile_inputs_cannot_change_after_valid_baseline(configured_input, filename):
    root, _ = configured_input
    path = root / "project_workflow/references" / filename
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(BuildProvenanceError, match="immutable inputs"):
        builder.derive_compatibility(root)


def test_retained_base_descriptor_is_read_only_inert_data(configured_input):
    root, current = configured_input
    archived_path = Path("project_workflow/references/base_sdlc_catalog_cli_v4.json")
    archived = json.loads((ROOT / archived_path).read_text(encoding="utf-8"))
    assert archived["catalog_version"] == 4
    descriptor = {
        "catalogVersion": 4, "catalogRevision": current["catalogRevision"],
        "catalogSha256": "b" * 64, "skillsRevision": archived["skills_source"]["revision"],
        "skillsManifestSha256": "d" * 64, "capabilityRevision": "base-workflow-controlplane/v1",
        "capabilitySha256": "e" * 64,
    }
    assert validate_runtime_compatibility(descriptor) == descriptor
    invalid = {**descriptor, "capabilityRevision": "hermes-sdlc-runtime/v2"}
    with pytest.raises(BuildProvenanceError, match="version"):
        validate_runtime_compatibility(invalid)
    archived["workflows"][0]["skill_allowlist"].append("foreign-skill")
    (root / archived_path).write_text(json.dumps(archived), encoding="utf-8")
    (root / builder.COMPATIBILITY_PATH).write_text(json.dumps(descriptor), encoding="utf-8")
    assert builder.derive_compatibility(root) == current


@pytest.mark.parametrize("variant", ["base", "legacy", "unknown"])
def test_removed_build_variants_fail_before_source_or_image_build(configured_input, monkeypatch, variant):
    root, _ = configured_input
    snapshot = Mock()
    process = Mock()
    monkeypatch.setattr(builder, "immutable_git_snapshot", snapshot)
    monkeypatch.setattr(builder.subprocess, "run", process)
    monkeypatch.setenv("PROJECT_WORKFLOW_CATALOG_VARIANT", variant)
    with pytest.raises(BuildProvenanceError, match="Only single-task-v1"):
        builder.derive_compatibility(root)
    with pytest.raises(BuildProvenanceError, match="Only single-task-v1"):
        builder.build_image(root, "workflow:test", "docker", catalog_variant=variant)
    snapshot.assert_not_called()
    process.assert_not_called()


@pytest.mark.parametrize("variant", ["base", "legacy", "unknown"])
def test_removed_cli_variants_are_rejected_without_building(monkeypatch, variant):
    build = Mock()
    process = Mock()
    monkeypatch.setattr(builder, "build_image", build)
    monkeypatch.setattr(builder.subprocess, "run", process)
    with pytest.raises(SystemExit) as error:
        builder.main(["build", "--image", "workflow:test", "--catalog-variant", variant])
    assert error.value.code == 2
    build.assert_not_called()
    process.assert_not_called()


def test_native_skills_input_is_rejected_without_building(configured_input, monkeypatch):
    root, _ = configured_input
    snapshot = Mock()
    process = Mock()
    monkeypatch.setattr(builder, "immutable_git_snapshot", snapshot)
    monkeypatch.setattr(builder.subprocess, "run", process)
    with pytest.raises(BuildProvenanceError, match="no native skills build input"):
        builder.build_image(root, "workflow:test", "docker", skills_root=root)
    snapshot.assert_not_called()
    process.assert_not_called()


@pytest.mark.parametrize("mode", ["platform", "standalone"])
def test_both_explicit_modes_use_only_the_current_catalog(monkeypatch, mode):
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", mode)
    monkeypatch.delenv("PROJECT_WORKFLOW_CATALOG_VARIANT", raising=False)
    command = [sys.executable, "-B", "-c",
               "from project_workflow.config import MANAGED_CATALOG_PATH, get_settings; "
               "print(get_settings().PROJECT_WORKFLOW_MODE, MANAGED_CATALOG_PATH.name)"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True, timeout=20)
    assert result.stdout.strip() == f"{mode} single_task_catalog_v1.json"


@pytest.mark.parametrize("variant", ["base", "legacy", "unknown"])
def test_removed_catalog_selector_is_rejected_not_redirected(monkeypatch, variant):
    monkeypatch.setenv("PROJECT_WORKFLOW_CATALOG_VARIANT", variant)
    command = [sys.executable, "-B", "-c",
               "from project_workflow.config import MANAGED_CATALOG_PATH; print(MANAGED_CATALOG_PATH.name)"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=20)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "Unsupported catalog variant" in result.stderr


def test_unregistered_opaque_execution_credentials_are_rejected(monkeypatch):
    from project_workflow.interfaces.ui.routes import runtime_api

    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "platform")
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", "b" * 32)
    runtime_api.config.get_settings.cache_clear()
    assert runtime_api._authorized_service_credential("Bearer " + "a" * 32) is None
    credential = runtime_api._authorized_service_credential("Bearer " + "b" * 32)
    assert credential is not None and credential.kind == "catalog"
    assert not credential.can_assign
    assert runtime_api._authorized_assignment_role("Bearer " + "b" * 32) is None
