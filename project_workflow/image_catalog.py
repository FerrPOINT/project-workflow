"""Catalog selection embedded by the immutable image builder, never by environment."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from project_workflow.build_provenance import (
    BASE_PENDING_CAPABILITY_REVISION,
    BuildProvenance,
    BuildProvenanceError,
    load_build_provenance,
    runtime_compatibility_descriptor,
)

IMAGE_ROOT = Path("/app")
SELECTION_PATH = "runtime-catalog-selection.json"
CATALOG_PROFILES = {
    "legacy-v2": (2, "hermes_sdlc_catalog_v1.json"),
    "base-v3": (3, "base_sdlc_catalog_v1.json"),
}


def image_catalog_profile(root: Path, provenance: BuildProvenance) -> str:
    path = root / SELECTION_PATH
    if not path.exists() and not path.is_symlink():
        return "legacy-v2"
    if path.is_symlink() or not path.is_file():
        raise BuildProvenanceError("Image catalog selection must be a regular file")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise BuildProvenanceError("Image catalog selection unavailable") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "profile", "source_revision"}
        or type(value["schema_version"]) is not int or value["schema_version"] != 1
        or not isinstance(value["profile"], str) or value["profile"] not in CATALOG_PROFILES
        or value["source_revision"] != provenance.source_revision
    ):
        raise BuildProvenanceError("Image catalog selection does not match immutable source")
    return value["profile"]


def compatibility_for_catalog(catalog: Any, manifest: dict[str, Any], provenance: BuildProvenance,
                              *, catalog_path: Path, guard_path: Path) -> dict[str, Any]:
    from project_workflow.infrastructure.db.managed_catalog import export_runtime_catalog

    if not isinstance(manifest, dict) or manifest.get("schema") != catalog.skills_source.manifest_schema:
        raise BuildProvenanceError("Native skills manifest schema differs from canonical pin")
    try:
        exported, _ = export_runtime_catalog(
            catalog, manifest=manifest, workflow_revision=provenance.source_revision,
            skills_revision=catalog.skills_source.revision, source_artifacts={},
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BuildProvenanceError("Native skills manifest differs from image catalog") from exc
    descriptor = exported["runtimeCompatibility"]
    if catalog.catalog_version == 3:
        from project_workflow.application.base_source import CANDIDATE_BLOB
        from project_workflow.domain.base_admission import BASE_SKILLS_REVISION

        if catalog_path.is_symlink() or not catalog_path.is_file():
            raise BuildProvenanceError("Base image candidate must be a regular file")
        content = catalog_path.read_bytes().replace(b"\r\n", b"\n")
        blob = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if blob != CANDIDATE_BLOB or catalog.skills_source.revision != BASE_SKILLS_REVISION:
            raise BuildProvenanceError("Base image candidate differs from pinned source")
        # This is a build policy pin, not an executor capability or owner ACK.
        policy = {"revision": BASE_PENDING_CAPABILITY_REVISION, "executionAllowed": False,
                  "ownerAdmissionSourceSha256": hashlib.sha256(
                      guard_path.read_bytes().replace(b"\r\n", b"\n")
                  ).hexdigest()}
        descriptor = {**descriptor, "capabilityRevision": BASE_PENDING_CAPABILITY_REVISION,
                      "capabilitySha256": hashlib.sha256(json.dumps(
                          policy, sort_keys=True, separators=(",", ":")
                      ).encode()).hexdigest()}
    return descriptor


def packaged_catalog_path(default: Path) -> Path:
    """Validate image metadata before selecting or initializing a database catalog."""
    root = IMAGE_ROOT
    if not any((root / name).exists() or (root / name).is_symlink()
               for name in (SELECTION_PATH, "runtime-compatibility.json", "runtime-build-manifest.json")):
        return default
    provenance = load_build_provenance(root / "runtime-build-manifest.json")
    profile = image_catalog_profile(root, provenance)
    version, filename = CATALOG_PROFILES[profile]
    descriptor = runtime_compatibility_descriptor(root / "runtime-compatibility.json", provenance)
    if descriptor["catalogVersion"] != version:
        raise BuildProvenanceError("Image catalog selection/compatibility mismatch")
    path = default.with_name(filename)
    # Re-derive from installed bytes rather than trusting a descriptor alone.
    from project_workflow.infrastructure.db.managed_catalog import ManagedCatalog

    catalog = ManagedCatalog.model_validate_json(path.read_bytes())
    manifest = json.loads((root / "runtime-skills-manifest.json").read_bytes())
    if catalog.catalog_version != version or descriptor != compatibility_for_catalog(
        catalog, manifest, provenance, catalog_path=path,
        guard_path=Path(__file__).parent / "application/base_admission.py",
    ):
        raise BuildProvenanceError("Installed catalog differs from immutable image inputs")
    return path
