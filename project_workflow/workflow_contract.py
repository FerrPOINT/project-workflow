"""Configuration-only Hermes workflow/profile contract.

Runtime assignment, queue, lease and session ownership deliberately stay out of
this package.  Relevanter Business selects and pins a mode; this module only
validates that the referenced catalog entry and role profile are configured.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("references") / "hermes_role_catalog.v2.json"
ACCEPTED_SKILLS_REVISION = "be9839364d5037a28ab791a591cf6eef690c93bc"
ACCEPTED_SKILLS_MANIFEST_SHA256 = "2ca3740f7c5c1f23551689aa3b86dc217c26a3405dbfc2273fd3b4c80c8a1d1a"
ACCEPTED_PHASE_SETS_SHA256 = "579e073e103d979c0080d7a3bddf0a1557035ec4114646d777cd7e562675b4f0"


@dataclass(frozen=True)
class PinnedWorkflowContract:
    role: str
    profile: str
    workflow: str
    mode: str
    skills: tuple[str, ...]


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_role_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    schema = raw.get("schema")
    if schema not in {
        "relevanter-hermes-workflow-catalog/v1",
        "relevanter-hermes-workflow-catalog/v2",
    }:
        raise ValueError("Unsupported Hermes workflow catalog schema")
    if schema == "relevanter-hermes-workflow-catalog/v2":
        if (
            raw.get("skillsCatalogRevision") != ACCEPTED_SKILLS_REVISION
            or raw.get("skillsManifestSha256") != ACCEPTED_SKILLS_MANIFEST_SHA256
        ):
            raise ValueError("Hermes Skills manifest pin is invalid")
        phase_sets_from = raw.get("phaseSetsFrom")
        if phase_sets_from != "hermes_role_catalog.json" or "phase_sets" in raw:
            raise ValueError("Hermes workflow catalog v2 has no exact external phase-set source")
        phase_source = json.loads((path.parent / phase_sets_from).read_text(encoding="utf-8"))
        if phase_source.get("schema") != "relevanter-hermes-workflow-catalog/v1":
            raise ValueError("Hermes workflow catalog phase-set source is invalid")
        phase_sets = phase_source.get("phase_sets")
        if not isinstance(phase_sets, dict) or not phase_sets:
            raise ValueError("Hermes workflow catalog phase-set source is empty")
        if (
            raw.get("phaseSetsSha256") != ACCEPTED_PHASE_SETS_SHA256
            or _canonical_sha256(phase_sets) != ACCEPTED_PHASE_SETS_SHA256
        ):
            raise ValueError("Hermes workflow catalog phase-set digest mismatch")
        raw = {**raw, "phase_sets": phase_sets}
    roles = raw.get("roles")
    if not isinstance(roles, dict) or not roles:
        raise ValueError("Hermes workflow catalog has no roles")
    legacy = roles.get("project-manager")
    canonical = roles.get("project_manager")
    if schema == "relevanter-hermes-workflow-catalog/v2":
        if legacy is not None:
            raise ValueError("Hermes workflow catalog v2 rejects the legacy role alias")
        for role, config in roles.items():
            if not isinstance(config, dict) or config.get("workflow") != f"hermes-sdlc:{role}":
                raise ValueError("Hermes workflow catalog v2 workflow identity is not canonical")
    if legacy is not None and canonical is not None:
        raise ValueError("Ambiguous Project Manager role keys in Hermes catalog")
    if schema == "relevanter-hermes-workflow-catalog/v1" and legacy is not None:
        if not isinstance(legacy, dict):
            raise ValueError("Legacy Project Manager role config is invalid")
        migrated = dict(legacy)
        if migrated.get("workflow") == "hermes-sdlc:project-manager":
            migrated["workflow"] = "hermes-sdlc:project_manager"
        roles = dict(roles)
        roles.pop("project-manager")
        roles["project_manager"] = migrated
        raw = dict(raw)
        raw["roles"] = roles
    return raw


def _mode_keys(role_config: dict[str, Any]) -> list[str]:
    modes = role_config.get("modes")
    if not isinstance(modes, list):
        raise ValueError("Hermes role mode catalog is invalid")
    keys: list[str] = []
    for mode in modes:
        if not isinstance(mode, dict) or not isinstance(mode.get("key"), str):
            raise ValueError("Hermes role mode definition is invalid")
        keys.append(mode["key"])
    if len(keys) != len(set(keys)):
        raise ValueError("Hermes workflow mode keys must be unique within a workflow")
    return keys


def validate_pinned_contract(
    *,
    role: str,
    profile: str,
    workflow: str,
    mode: str,
) -> PinnedWorkflowContract:
    """Validate immutable values received from the backend assignment.

    There is intentionally no fallback/default and no API for deriving a mode
    from caller text, prompt or local task state.
    """

    role_config = load_role_catalog()["roles"].get(role)
    if not isinstance(role_config, dict):
        raise ValueError(f"Unknown Hermes role: {role}")
    expected_profile = role_config.get("profile")
    if profile != expected_profile:
        raise ValueError("Hermes profile does not match the backend-pinned role")
    expected_workflow = role_config.get("workflow")
    if workflow != expected_workflow:
        raise ValueError("Workflow does not match the backend-pinned role")
    if mode not in _mode_keys(role_config):
        raise ValueError("Workflow mode is not allowed for the backend-pinned role")
    skills = role_config.get("skills")
    if not isinstance(skills, list) or any(not isinstance(item, str) for item in skills):
        raise ValueError("Hermes role skill catalog is invalid")
    return PinnedWorkflowContract(
        role=role,
        profile=profile,
        workflow=workflow,
        mode=mode,
        skills=tuple(skills),
    )
