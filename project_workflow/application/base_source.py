"""Explicit source-only Base export; never install or advertise runtime readiness."""

import hashlib
from pathlib import Path
from typing import Any

from project_workflow import config
from project_workflow.application.base_admission import CANDIDATE_PATH
from project_workflow.domain.base_admission import BASE_SKILLS_REVISION
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure.base_package import GitPackage, digest, load_pinned_package
from project_workflow.infrastructure.db.managed_catalog import ManagedCatalog, export_runtime_catalog

CANDIDATE_REVISION = "b01fc3c9b017b81a178ef678754d8f23f9943af7"
CANDIDATE_BLOB = "71560ee37de8acfd020630d58a036618f007b94b"
CLI_CANDIDATE_PATH = CANDIDATE_PATH.with_name("base_sdlc_catalog_cli_v4.json")
CLI_CANDIDATE_REVISION = "d4cb918605ce7bc032e8d2d921583714347bc10f"
CLI_CANDIDATE_BLOB = "13594fc383d90ad400e73ee48b6484dcb02b69ee"
CLI_SKILLS_REVISION = "4e5647d3a3015c26be8f5a390c4d5537d1d10d02"


def export_base_source() -> dict[str, Any]:
    """Reuse the native catalog derivative, omitting legacy Business/runtime claims."""
    return load_base_source()[1]


def load_base_source(version: int | None = None) -> tuple[ManagedCatalog, dict[str, Any]]:
    """Return the verified candidate and its matching export from one source read."""
    version = (4 if config.CATALOG_VARIANT == "base-cli" else 3) if version is None else version
    if version not in {3, 4}:
        raise ValueError("Unsupported Base catalog version")
    path, revision, expected_blob, skills_revision = (
        (CLI_CANDIDATE_PATH, CLI_CANDIDATE_REVISION, CLI_CANDIDATE_BLOB, CLI_SKILLS_REVISION)
        if version == 4 else (CANDIDATE_PATH, CANDIDATE_REVISION, CANDIDATE_BLOB, BASE_SKILLS_REVISION)
    )
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
    artifact = "project_workflow/references/" + path.name
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
