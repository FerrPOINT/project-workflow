"""Explicit source-only Base export; never install or advertise runtime readiness."""

import hashlib
from pathlib import Path
from typing import Any

from project_workflow import config
from project_workflow.application.base_admission import CANDIDATE_PATH
from project_workflow.domain.base_admission import BASE_SKILLS_REVISION
from project_workflow.domain.base_catalog import (
    BASE_CATALOG_ARTIFACTS,
    BASE_CATALOG_BLOBS,
    BASE_CATALOG_REVISIONS,
    BASE_CATALOG_SKILLS,
    BASE_CATALOG_VERSION,
)
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure.base_package import GitPackage, digest, load_pinned_package
from project_workflow.infrastructure.db.managed_catalog import ManagedCatalog, export_runtime_catalog

CANDIDATE_REVISION = "674aab3f016255cf948b6e6e8b0ea92a8bf92557"
CANDIDATE_BLOB = "5581b929c9e80bfba85684e98109944b2fb898ae"


def export_base_source(catalog_version: int | None = None) -> dict[str, Any]:
    """Reuse the native catalog derivative, omitting legacy Business/runtime claims."""
    return load_base_source(catalog_version)[1]


def load_base_source(catalog_version: int | None = None) -> tuple[ManagedCatalog, dict[str, Any]]:
    """Return one exact generation; installed Base uses v4, historical readers can request v3."""
    version = catalog_version if catalog_version is not None else (
        BASE_CATALOG_VERSION if config.CATALOG_VARIANT == "base" else 3
    )
    if type(version) is not int or version not in BASE_CATALOG_ARTIFACTS:
        raise ValueError("Unsupported Base catalog version")
    path = CANDIDATE_PATH if version == 3 else CANDIDATE_PATH.with_name(BASE_CATALOG_ARTIFACTS[version])
    revision = CANDIDATE_REVISION if version == 3 else BASE_CATALOG_REVISIONS[version]
    expected_blob = CANDIDATE_BLOB if version == 3 else BASE_CATALOG_BLOBS[version]
    skills_revision = BASE_SKILLS_REVISION if version == 3 else BASE_CATALOG_SKILLS[version]
    if path.is_symlink():
        raise ValueError("Candidate must be a regular source artifact")
    content = path.read_bytes().replace(b"\r\n", b"\n")
    blob = hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()
    if blob != expected_blob:
        raise ValueError("Candidate differs from the pinned source Git blob")
    # Parse the verified bytes, not a second potentially changed filesystem read.
    catalog = ManagedCatalog.model_validate_json(content)
    if catalog.catalog_version != version or catalog.skills_source.revision != skills_revision:
        raise ValueError("Base candidate version/package mismatch")
    root = config.get_settings().PROJECT_WORKFLOW_BASE_SKILLS_ROOT
    if not root:
        raise RuntimeError("Base pinned Git package access is not configured")
    manifest = load_pinned_package(Path(root), catalog.skills_source)
    for workflow in catalog.workflows:
        role = manifest["roles"][workflow.role_key]
        if (
            role["namespace"] != workflow.hermes_namespace or role["profile"] != workflow.hermes_profile
            or role["modes"] != [mode.key for mode in workflow.modes]
            or role["physicalSkills"] != workflow.skill_allowlist
        ):
            raise ValueError("Pinned role/mode/allowlist differs from candidate")
    artifact = "project_workflow/references/" + BASE_CATALOG_ARTIFACTS[version]
    derived, phases = export_runtime_catalog(
        catalog, manifest=manifest, workflow_revision=revision,
        skills_revision=skills_revision, source_artifacts={artifact: digest(content)},
    )
    roles = derived["roles"]
    for workflow in catalog.workflows:
        roles[workflow.role_key].update(
            namespace=workflow.hermes_namespace,
            roleInstructionSha256=manifest["roles"][workflow.role_key]["roleInstruction"]["sha256"],
        )
    manifest_sha256 = digest(GitPackage(Path(root).resolve().parent, skills_revision).read("manifest.json"))
    result = {
        "schema": "base-sdlc/workflow-source-catalog/v1", "catalogVersion": version,
        "sourceOnly": True, "runtimeReady": False, "installation": "not-performed-by-export",
        "owners": {"package": "services-base", "assignment": "task-tracker", "execution": "fleet-control",
                   "workflowReceipt": "project-workflow", "deliveryReceipt": "CI-CD"},
        "workflowCatalogRepository": derived["workflowCatalogRepository"],
        "workflowCatalogRevision": revision, "workflowCatalogGitBlob": expected_blob,
        "workflowCatalogSourceArtifacts": derived["workflowCatalogSourceArtifacts"],
        "skillsCatalogRepository": catalog.skills_source.repository, "skillsCatalogRevision": skills_revision,
        "skillsManifestPath": catalog.skills_source.manifest_path,
        "skillsManifestSchema": catalog.skills_source.manifest_schema,
        "skillsManifestSha256": manifest_sha256,
        "skillsSha256": manifest["sources"]["native"]["skills"],
        "roles": roles, "rolesSha256": payload_sha256(roles),
        "phaseSets": phases["phase_sets"], "phaseSetsSha256": derived["phaseSetsSha256"],
    }
    return catalog, {**result, "sourceSha256": payload_sha256(result)}


def source_capability(source: dict[str, Any], *, role_key: str, credential_kind: str) -> dict[str, Any]:
    """Source implementation evidence, not an installed image/build attestation."""
    return {
        "contract": "base-sdlc/workflow-source-capability/v1", "source_only": True, "runtime_ready": False,
        "role_key": role_key, "credential_kind": credential_kind,
        "catalog_version": source["catalogVersion"], "source_sha256": source["sourceSha256"],
        "implementation_build_attested": False,
        "candidate_revision": source["workflowCatalogRevision"], "skills_revision": source["skillsCatalogRevision"],
        "implemented_source": [
            "pinned-source-validation", "registered-reader-auth", "accepted-step-receipt-derivation",
        ],
        "endpoints": {"catalog": "/internal/runtime/base/source-catalog",
                      "terminal_readback": "/internal/runtime/base/terminal-receipt/readback"},
        "terminal_proof": "blocked-until-trusted-owner-binding-and-evidence",
        "unavailable": ["generic-base-checkpoint-ack", "fleet-frozen-assignment-config-binding",
                        "tracker-non-pm-execution-binding", "forge-trusted-evidence-lookup",
                        f"installed-v{source['catalogVersion']}-build-provenance"],
    }
