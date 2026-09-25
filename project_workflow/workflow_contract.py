"""Configuration-only Hermes workflow/profile contract.

Runtime assignment, queue, lease and session ownership deliberately stay out of
this package.  Relevanter Business selects and pins a mode; this module only
validates that the referenced catalog entry and role profile are configured.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("references") / "hermes_role_catalog.json"


@dataclass(frozen=True)
class PinnedWorkflowContract:
    role: str
    profile: str
    workflow: str
    mode: str
    skills: tuple[str, ...]


def load_role_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema") != "relevanter-hermes-workflow-catalog/v1":
        raise ValueError("Unsupported Hermes workflow catalog schema")
    roles = raw.get("roles")
    if not isinstance(roles, dict) or not roles:
        raise ValueError("Hermes workflow catalog has no roles")
    legacy = roles.get("project-manager")
    canonical = roles.get("project_manager")
    if legacy is not None and canonical is not None:
        raise ValueError("Ambiguous Project Manager role keys in Hermes catalog")
    if legacy is not None:
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
