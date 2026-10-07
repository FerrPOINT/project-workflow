"""Immutable image selection installs a catalog, never an owner execution ACK."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from project_workflow import image_catalog
from project_workflow.application.base_admission import require_owner_execution_evidence
from project_workflow.build_provenance import (
    BASE_PENDING_CAPABILITY_REVISION,
    BuildProvenance,
    BuildProvenanceError,
    validate_runtime_compatibility,
)
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db.managed_catalog import load_managed_catalog
from tests.test_build_provenance import (
    _builder_module,
    _extract_regular_context,
    _run_git,
)
from tests.test_build_provenance import compatible_sources as compatible_sources
from tests.test_build_provenance import git_source as git_source

PROVENANCE = BuildProvenance(1, "a" * 40, "b" * 64, "c" * 64)


def test_source_without_image_metadata_keeps_v2(tmp_path, monkeypatch):
    monkeypatch.setattr(image_catalog, "IMAGE_ROOT", tmp_path)
    monkeypatch.setenv("WORKFLOW_CATALOG_PROFILE", "base-v3")
    assert load_managed_catalog().catalog_version == 2


def test_invalid_image_is_rejected_before_database_initialization(tmp_path, monkeypatch, capsys):
    from scripts import init_db

    (tmp_path / "runtime-build-manifest.json").write_text(json.dumps(PROVENANCE.to_dict()), encoding="utf-8")
    (tmp_path / image_catalog.SELECTION_PATH).write_text(json.dumps({
        "schema_version": 1, "profile": "base-v3", "source_revision": "f" * 40,
    }), encoding="utf-8")
    monkeypatch.setattr(image_catalog, "IMAGE_ROOT", tmp_path)
    monkeypatch.setattr(init_db, "get_engine", lambda *_args: pytest.fail("Invalid image touched database"))
    assert init_db.main() == 1
    assert "immutable source" in capsys.readouterr().err


@pytest.mark.parametrize("selection", [
    {}, {"schema_version": True, "profile": "base-v3", "source_revision": "a" * 40},
    {"schema_version": 1, "profile": "../../foreign", "source_revision": "a" * 40},
    {"schema_version": 1, "profile": "base-v3", "source_revision": "f" * 40},
    {"schema_version": 1, "profile": [], "source_revision": "a" * 40},
    {"schema_version": 1, "profile": "base-v3", "source_revision": "a" * 40, "ready": True},
])
def test_selection_rejects_unknown_or_wrong_revision_before_runtime(tmp_path, selection):
    (tmp_path / image_catalog.SELECTION_PATH).write_text(json.dumps(selection), encoding="utf-8")
    with pytest.raises(BuildProvenanceError, match="immutable source"):
        image_catalog.image_catalog_profile(tmp_path, PROVENANCE)


@pytest.mark.parametrize("profile", ["legacy-v2", "base-v3"])
def test_known_selection_is_revision_bound(tmp_path, profile):
    path = tmp_path / image_catalog.SELECTION_PATH
    path.write_text(json.dumps({"schema_version": 1, "profile": profile,
                                "source_revision": PROVENANCE.source_revision}), encoding="utf-8")
    assert image_catalog.image_catalog_profile(tmp_path, PROVENANCE) == profile
    path.write_text("broken JSON", encoding="utf-8")
    with pytest.raises(BuildProvenanceError, match="unavailable"):
        image_catalog.image_catalog_profile(tmp_path, PROVENANCE)


def test_legacy_compatible_image_context_selects_installed_v2(compatible_sources, tmp_path, monkeypatch):
    source, skills, _, _ = compatible_sources
    builder = _builder_module()
    snapshot = builder.immutable_git_snapshot(source, "HEAD")
    context = builder.compatible_build_context(snapshot, skills)
    root = tmp_path / "installed"
    root.mkdir()
    _extract_regular_context(context, root)
    monkeypatch.setattr(image_catalog, "IMAGE_ROOT", root)
    default = root / builder.CATALOG_PATH
    assert image_catalog.packaged_catalog_path(default) == default
    assert load_managed_catalog(default).catalog_version == 2
    descriptor_path = root / builder.COMPATIBILITY_PATH
    descriptor = json.loads(descriptor_path.read_bytes())
    descriptor_path.chmod(0o644)
    descriptor_path.write_text(json.dumps({**descriptor, "catalogVersion": 3,
                                         "capabilityRevision": BASE_PENDING_CAPABILITY_REVISION}), encoding="utf-8")
    with pytest.raises(BuildProvenanceError, match="selection/compatibility mismatch"):
        image_catalog.packaged_catalog_path(default)


@pytest.mark.parametrize("revision", [None, [], "hermes-sdlc-runtime/v2"])
def test_v3_never_claims_legacy_executor_capability(revision):
    descriptor = {"catalogVersion": 3, "catalogRevision": "a" * 40, "catalogSha256": "b" * 64,
                  "skillsRevision": "c" * 40, "skillsManifestSha256": "d" * 64,
                  "capabilityRevision": revision, "capabilitySha256": "e" * 64}
    with pytest.raises(BuildProvenanceError, match="version invalid"):
        validate_runtime_compatibility(descriptor)
    descriptor["capabilityRevision"] = BASE_PENDING_CAPABILITY_REVISION
    assert validate_runtime_compatibility(descriptor) == descriptor


@pytest.mark.skipif(not os.environ.get("WORKFLOW_BASE_PACKAGE_TEST_ROOT"), reason="Private package is explicit opt-in")
def test_base_image_uses_archived_source_and_pinned_private_git(git_source, tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    shutil.copytree(root / "project_workflow", git_source / "project_workflow", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(root / "scripts", git_source / "scripts", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    _run_git(git_source, "add", ".")
    _run_git(git_source, "commit", "-m", "Base image source fixture")
    builder = _builder_module()
    snapshot = builder.immutable_git_snapshot(git_source, "HEAD")
    skills = Path(os.environ["WORKFLOW_BASE_PACKAGE_TEST_ROOT"])
    context = builder.compatible_build_context(snapshot, skills, catalog_profile="base-v3")
    (git_source / "project_workflow/references/base_sdlc_catalog_v1.json").write_text("dirty", encoding="utf-8")
    assert builder.compatible_build_context(snapshot, skills, catalog_profile="base-v3") == context
    installed = tmp_path / "installed"
    installed.mkdir()
    _extract_regular_context(context, installed)
    monkeypatch.setattr(image_catalog, "IMAGE_ROOT", installed)
    monkeypatch.setattr(image_catalog, "__file__", str(installed / "project_workflow/image_catalog.py"))
    default = installed / builder.CATALOG_PATH
    chosen = image_catalog.packaged_catalog_path(default)
    assert chosen.name == "base_sdlc_catalog_v1.json"
    assert load_managed_catalog(chosen).catalog_version == 3
    descriptor = json.loads((installed / builder.COMPATIBILITY_PATH).read_bytes())
    assert descriptor["catalogVersion"] == 3
    assert descriptor["capabilityRevision"] == BASE_PENDING_CAPABILITY_REVISION
    result = subprocess.run([os.sys.executable, "-m", "scripts.build_runtime_image", "verify-compatibility",
                             "--root", str(installed)], cwd=installed, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with pytest.raises(ConflictError, match="trusted owner"):
        require_owner_execution_evidence()
    candidate = chosen.read_text(encoding="utf-8")
    chosen.chmod(0o644)
    chosen.write_text(candidate.replace('"catalog_version": 3', '"catalog_version": 4'), encoding="utf-8")
    with pytest.raises((BuildProvenanceError, ValueError)):
        image_catalog.packaged_catalog_path(default)
