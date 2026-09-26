"""Fail-closed validation for the configuration-only Hermes workflow catalog.

Relevanter Business remains the only routing and mode-selection authority. This
module validates exact profile, skill, mode and phase-set configuration pinned by
a backend assignment; it does not create modes, assignments, queues or sessions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("references") / "hermes_role_catalog.v2.json"
PHASE_SETS_PATH = Path(__file__).with_name("references") / "hermes_workflow_phase_sets.v1.json"

CATALOG_SCHEMA = "relevanter-hermes-workflow-catalog/v2"
PHASE_SETS_SCHEMA = "relevanter-hermes-workflow-phase-sets/v1"
CATALOG_SOURCE_OF_TRUTH = (
    "configuration-only; Business taskWorkspaceExecutionRoutingRegistry pins literal mode and profile at runtime"
)
PHASE_SETS_SOURCE_OF_TRUTH = (
    "configuration-only phase definitions; Relevanter Business owns assignment and mode selection"
)
BUSINESS_ROUTING_REGISTRY = "taskWorkspaceExecutionRoutingRegistry"
ACCEPTED_SKILLS_REPOSITORY = "https://gt.wmtgroup.ru/relevanter/agent-skills.git"
ACCEPTED_SKILLS_REVISION = "f52b4b1be04b88a43dbece384dc407e0b3621eaf"
ACCEPTED_SKILLS_MANIFEST_PATH = "manifests/hermes-workflow-role-skills.v1.json"
ACCEPTED_SKILLS_MANIFEST_SCHEMA = "relevanter-hermes-role-skills/v3"
ACCEPTED_SKILLS_MANIFEST_SHA256 = "2ca3740f7c5c1f23551689aa3b86dc217c26a3405dbfc2273fd3b4c80c8a1d1a"
ACCEPTED_ROLES_SHA256 = "f8dac615cfc837ad57fbcde9c91db7e3267aea4711d321a4ecc6323a16a0757e"
ACCEPTED_PHASE_SETS_SHA256 = "579e073e103d979c0080d7a3bddf0a1557035ec4114646d777cd7e562675b4f0"

EXPECTED_ROLES = frozenset(
    {
        "project_manager",
        "analyst",
        "architect",
        "developer",
        "reviewer",
        "tester",
        "devops",
    }
)
CATALOG_FIELDS = frozenset(
    {
        "schema",
        "sourceOfTruth",
        "businessRoutingRegistry",
        "skillsCatalogRepository",
        "skillsCatalogRevision",
        "skillsManifestPath",
        "skillsManifestSchema",
        "skillsManifestSha256",
        "rolesSha256",
        "phaseSetsFrom",
        "phaseSetsSha256",
        "roles",
    }
)
ROLE_FIELDS = frozenset({"profile", "workflow", "modes", "skills"})
MODE_FIELDS = frozenset({"key", "name", "description", "phase_set", "instruction", "check", "evidence"})
PHASE_FIELDS = frozenset({"code", "name", "description"})


@dataclass(frozen=True)
class PinnedWorkflowContract:
    role: str
    profile: str
    workflow: str
    mode: str
    skills: tuple[str, ...]


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _load_json_object(path: Path, description: str) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{description} must be a JSON object")
    return raw


def _load_phase_sets(catalog_path: Path, raw: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    if "phase_sets" in raw:
        raise ValueError("Hermes workflow catalog rejects embedded phase-set fallback")
    phase_sets_from = raw.get("phaseSetsFrom")
    if phase_sets_from != PHASE_SETS_PATH.name:
        raise ValueError("Hermes workflow catalog has no exact external phase-set source")

    phase_source = _load_json_object(catalog_path.parent / phase_sets_from, "Hermes phase-set catalog")
    if phase_source.get("schema") != PHASE_SETS_SCHEMA:
        raise ValueError("Hermes workflow catalog phase-set source schema is invalid")
    if phase_source.get("sourceOfTruth") != PHASE_SETS_SOURCE_OF_TRUTH:
        raise ValueError("Hermes workflow catalog phase-set authority is invalid")
    if set(phase_source) != {"schema", "sourceOfTruth", "phase_sets"}:
        raise ValueError("Hermes workflow catalog phase-set source contains an embedded role catalog")

    phase_sets = phase_source.get("phase_sets")
    if not isinstance(phase_sets, dict) or not phase_sets:
        raise ValueError("Hermes workflow catalog phase-set source is empty")
    if (
        raw.get("phaseSetsSha256") != ACCEPTED_PHASE_SETS_SHA256
        or _canonical_sha256(phase_sets) != ACCEPTED_PHASE_SETS_SHA256
    ):
        raise ValueError("Hermes workflow catalog phase-set digest mismatch")

    validated: dict[str, list[dict[str, str]]] = {}
    for phase_set_key, phases in phase_sets.items():
        if not _non_empty_string(phase_set_key) or not isinstance(phases, list):
            raise ValueError("Hermes phase-set definition is invalid")
        if not 8 <= len(phases) <= 12:
            raise ValueError("Hermes phase-set must contain 8 to 12 substantive phases")
        codes: set[str] = set()
        validated_phases: list[dict[str, str]] = []
        for phase in phases:
            if not isinstance(phase, dict) or set(phase) != PHASE_FIELDS:
                raise ValueError("Hermes phase definition schema is invalid")
            if any(not _non_empty_string(phase.get(field)) for field in PHASE_FIELDS):
                raise ValueError("Hermes phase definition contains an empty field")
            code = phase["code"]
            if code in codes:
                raise ValueError("Hermes phase codes must be unique within a phase set")
            codes.add(code)
            validated_phases.append(phase)
        validated[phase_set_key] = validated_phases
    return validated


def _validate_roles(
    roles: object,
    phase_sets: dict[str, list[dict[str, str]]],
) -> dict[str, dict[str, Any]]:
    if not isinstance(roles, dict) or set(roles) != EXPECTED_ROLES:
        raise ValueError("Hermes workflow catalog must contain exactly seven canonical roles")
    if _canonical_sha256(roles) != ACCEPTED_ROLES_SHA256:
        raise ValueError("Hermes role profile, mode or skill catalog digest mismatch")

    referenced_phase_sets: set[str] = set()
    validated: dict[str, dict[str, Any]] = {}
    for role, config in roles.items():
        if not isinstance(config, dict) or set(config) != ROLE_FIELDS:
            raise ValueError("Hermes role definition schema is invalid")
        if config.get("workflow") != f"hermes-sdlc:{role}":
            raise ValueError("Hermes workflow identity is not canonical")
        if not _non_empty_string(config.get("profile")):
            raise ValueError("Hermes profile is invalid")

        skills = config.get("skills")
        if (
            not isinstance(skills, list)
            or not skills
            or any(not _non_empty_string(skill) for skill in skills)
            or len(skills) != len(set(skills))
            or skills != sorted(skills)
        ):
            raise ValueError("Hermes role skill catalog is invalid")

        modes = config.get("modes")
        if not isinstance(modes, list) or not modes:
            raise ValueError("Hermes role mode catalog is invalid")
        mode_keys: set[str] = set()
        for mode in modes:
            if not isinstance(mode, dict) or set(mode) != MODE_FIELDS:
                raise ValueError("Hermes role mode definition schema is invalid")
            if any(not _non_empty_string(mode.get(field)) for field in MODE_FIELDS):
                raise ValueError("Hermes role mode definition contains an empty field")
            mode_key = mode["key"]
            if mode_key in mode_keys:
                raise ValueError("Hermes workflow mode keys must be unique within a workflow")
            mode_keys.add(mode_key)
            phase_set = mode["phase_set"]
            if phase_set not in phase_sets:
                raise ValueError("Hermes workflow mode references an unknown phase set")
            referenced_phase_sets.add(phase_set)
        validated[role] = config

    if referenced_phase_sets != set(phase_sets):
        raise ValueError("Hermes phase-set catalog contains missing or unused definitions")
    return validated


def load_role_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    """Load the one pinned catalog and reject aliases, fallbacks and drift."""

    raw = _load_json_object(path, "Hermes workflow catalog")
    if raw.get("schema") != CATALOG_SCHEMA:
        raise ValueError("Unsupported or incomplete Hermes workflow catalog schema")
    if "phase_sets" in raw:
        raise ValueError("Hermes workflow catalog rejects embedded phase-set fallback")
    if set(raw) != CATALOG_FIELDS:
        raise ValueError("Unsupported or incomplete Hermes workflow catalog schema")
    if raw.get("sourceOfTruth") != CATALOG_SOURCE_OF_TRUTH:
        raise ValueError("Hermes workflow catalog authority is invalid")
    if raw.get("businessRoutingRegistry") != BUSINESS_ROUTING_REGISTRY:
        raise ValueError("Hermes workflow catalog does not name the Business routing authority")
    if (
        raw.get("skillsCatalogRepository") != ACCEPTED_SKILLS_REPOSITORY
        or raw.get("skillsCatalogRevision") != ACCEPTED_SKILLS_REVISION
        or raw.get("skillsManifestPath") != ACCEPTED_SKILLS_MANIFEST_PATH
        or raw.get("skillsManifestSchema") != ACCEPTED_SKILLS_MANIFEST_SCHEMA
        or raw.get("skillsManifestSha256") != ACCEPTED_SKILLS_MANIFEST_SHA256
    ):
        raise ValueError("Hermes Skills manifest pin is invalid")
    if raw.get("rolesSha256") != ACCEPTED_ROLES_SHA256:
        raise ValueError("Hermes role catalog pin is invalid")

    phase_sets = _load_phase_sets(path, raw)
    roles = _validate_roles(raw.get("roles"), phase_sets)
    return {**raw, "roles": roles, "phase_sets": phase_sets}


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
    if profile != role_config["profile"]:
        raise ValueError("Hermes profile does not match the backend-pinned role")
    if workflow != role_config["workflow"]:
        raise ValueError("Workflow does not match the backend-pinned role")
    mode_keys = {entry["key"] for entry in role_config["modes"]}
    if mode not in mode_keys:
        raise ValueError("Workflow mode is not allowed for the backend-pinned role")
    return PinnedWorkflowContract(
        role=role,
        profile=profile,
        workflow=workflow,
        mode=mode,
        skills=tuple(role_config["skills"]),
    )
