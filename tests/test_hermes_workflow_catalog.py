from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_workflow.workflow_contract import (
    ACCEPTED_PHASE_SETS_SHA256,
    ACCEPTED_ROLES_SHA256,
    ACCEPTED_SKILLS_MANIFEST_SHA256,
    ACCEPTED_SKILLS_REVISION,
    BUSINESS_ROUTING_REGISTRY,
    CATALOG_PATH,
    PHASE_SETS_PATH,
    load_role_catalog,
    validate_pinned_contract,
)

EXPECTED_MODES = {
    "project_manager": ["draft"],
    "analyst": ["analysis"],
    "architect": ["decomposition"],
    "developer": ["initial", "rework", "integration", "integration_rework"],
    "reviewer": ["delivery", "integration"],
    "tester": ["delivery", "integration"],
    "devops": ["delivery", "integration"],
}
EXPECTED_PROFILES = {
    "project_manager": "hermes-sdlc-project-manager",
    "analyst": "hermes-sdlc-analyst",
    "architect": "hermes-sdlc-architect",
    "developer": "hermes-sdlc-developer",
    "reviewer": "hermes-sdlc-reviewer",
    "tester": "hermes-sdlc-quality",
    "devops": "hermes-sdlc-operations",
}
EXPECTED_SKILLS = {
    "project_manager": [
        "project-workflow-executor",
        "relevanter-business-operator",
    ],
    "analyst": [
        "domain-modeling",
        "immutable-evidence-reporting",
        "project-workflow-executor",
        "relevanter-business-operator",
        "requirements-analysis",
        "workflow-writing-plans",
    ],
    "architect": [
        "domain-modeling",
        "immutable-evidence-reporting",
        "project-workflow-executor",
        "relevanter-business-operator",
        "solution-architecture",
        "workflow-writing-plans",
    ],
    "developer": [
        "immutable-evidence-reporting",
        "project-workflow-executor",
        "relevanter-business-operator",
        "relevanter-tech-operator",
        "repo-workflow",
        "test-driven-development",
        "workflow-systematic-debugging",
    ],
    "reviewer": [
        "exact-code-review",
        "immutable-evidence-reporting",
        "project-workflow-executor",
        "relevanter-business-operator",
        "relevanter-tech-operator",
    ],
    "tester": [
        "deployed-acceptance",
        "immutable-evidence-reporting",
        "project-workflow-executor",
        "relevanter-business-operator",
        "workflow-systematic-debugging",
    ],
    "devops": [
        "exact-sha-deployment",
        "immutable-evidence-reporting",
        "project-workflow-executor",
        "relevanter-business-operator",
        "relevanter-tech-operator",
        "workflow-systematic-debugging",
    ],
}


def _catalog_copy(tmp_path: Path) -> tuple[dict[str, object], dict[str, object], Path]:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    phases = json.loads(PHASE_SETS_PATH.read_text(encoding="utf-8"))
    target_catalog = tmp_path / CATALOG_PATH.name
    target_phases = tmp_path / PHASE_SETS_PATH.name
    target_catalog.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    target_phases.write_text(json.dumps(phases, ensure_ascii=False), encoding="utf-8")
    return catalog, phases, target_catalog


def test_catalog_matches_business_modes_and_pinned_agent_skills_manifest() -> None:
    catalog = load_role_catalog()

    assert catalog["businessRoutingRegistry"] == BUSINESS_ROUTING_REGISTRY
    assert catalog["skillsCatalogRevision"] == ACCEPTED_SKILLS_REVISION
    assert catalog["skillsManifestSha256"] == ACCEPTED_SKILLS_MANIFEST_SHA256
    assert catalog["rolesSha256"] == ACCEPTED_ROLES_SHA256
    assert catalog["phaseSetsSha256"] == ACCEPTED_PHASE_SETS_SHA256
    assert {
        role: [mode["key"] for mode in config["modes"]] for role, config in catalog["roles"].items()
    } == EXPECTED_MODES
    assert {role: config["profile"] for role, config in catalog["roles"].items()} == EXPECTED_PROFILES
    assert {role: config["skills"] for role, config in catalog["roles"].items()} == EXPECTED_SKILLS
    assert {role: config["workflow"] for role, config in catalog["roles"].items()} == {
        role: f"hermes-sdlc:{role}" for role in EXPECTED_MODES
    }


def test_catalog_contains_distinct_substantive_phase_sets_for_all_modes() -> None:
    catalog = load_role_catalog()
    definitions: list[str] = []

    for role, mode_keys in EXPECTED_MODES.items():
        modes = catalog["roles"][role]["modes"]
        assert [mode["key"] for mode in modes] == mode_keys
        for mode in modes:
            phases = catalog["phase_sets"][mode["phase_set"]]
            assert 8 <= len(phases) <= 12
            assert mode["name"] and mode["description"]
            assert mode["instruction"] and mode["check"] and mode["evidence"]
            assert all(phase["code"] and phase["name"] and phase["description"] for phase in phases)
            definitions.append(
                json.dumps(
                    {"mode": mode, "phases": phases},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

    assert len(definitions) == 13
    assert len(definitions) == len(set(definitions))


@pytest.mark.parametrize(
    ("drift", "error"),
    [
        ("mode", "role profile, mode or skill catalog digest"),
        ("profile", "role profile, mode or skill catalog digest"),
        ("skills", "role profile, mode or skill catalog digest"),
        ("skills-revision", "Skills manifest pin"),
        ("skills-manifest", "Skills manifest pin"),
        ("phase-set", "phase-set digest"),
        ("embedded-phase-sets", "embedded phase-set fallback"),
        ("embedded-role-catalog", "embedded role catalog"),
    ],
)
def test_catalog_fails_closed_on_contract_or_provenance_drift(
    tmp_path: Path,
    drift: str,
    error: str,
) -> None:
    catalog, phases, target_catalog = _catalog_copy(tmp_path)

    if drift == "mode":
        catalog["roles"]["developer"]["modes"][0]["key"] = "caller-selected"
    elif drift == "profile":
        catalog["roles"]["architect"]["profile"] = "caller-profile"
    elif drift == "skills":
        catalog["roles"]["tester"]["skills"].append("foreign-skill")
    elif drift == "skills-revision":
        catalog["skillsCatalogRevision"] = "0" * 40
    elif drift == "skills-manifest":
        catalog["skillsManifestSha256"] = "0" * 64
    elif drift == "phase-set":
        phases["phase_sets"]["analyst"][0]["description"] = "drift"
        (tmp_path / PHASE_SETS_PATH.name).write_text(
            json.dumps(phases, ensure_ascii=False),
            encoding="utf-8",
        )
    elif drift == "embedded-phase-sets":
        catalog["phase_sets"] = phases["phase_sets"]
    else:
        phases["roles"] = catalog["roles"]
        (tmp_path / PHASE_SETS_PATH.name).write_text(
            json.dumps(phases, ensure_ascii=False),
            encoding="utf-8",
        )

    target_catalog.write_text(
        json.dumps(catalog, ensure_ascii=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=error):
        load_role_catalog(target_catalog)


def test_pinned_assignment_validation_has_no_default_or_caller_override() -> None:
    contract = validate_pinned_contract(
        role="developer",
        profile="hermes-sdlc-developer",
        workflow="hermes-sdlc:developer",
        mode="integration_rework",
    )
    assert contract.skills == tuple(EXPECTED_SKILLS["developer"])

    with pytest.raises(ValueError, match="mode"):
        validate_pinned_contract(
            role="developer",
            profile="hermes-sdlc-developer",
            workflow="hermes-sdlc:developer",
            mode="default",
        )
    with pytest.raises(ValueError, match="profile"):
        validate_pinned_contract(
            role="developer",
            profile="caller-profile",
            workflow="hermes-sdlc:developer",
            mode="initial",
        )
    with pytest.raises(ValueError, match="Workflow"):
        validate_pinned_contract(
            role="developer",
            profile="hermes-sdlc-developer",
            workflow="caller-workflow",
            mode="initial",
        )
    with pytest.raises(ValueError, match="Unknown"):
        validate_pinned_contract(
            role="caller-role",
            profile="hermes-sdlc-caller",
            workflow="hermes-sdlc:caller",
            mode="initial",
        )


def test_phase_source_is_phase_only_and_catalog_remains_configuration_only() -> None:
    phase_source = json.loads(PHASE_SETS_PATH.read_text(encoding="utf-8"))
    production = (Path(__file__).parents[1] / "project_workflow" / "workflow_contract.py").read_text(encoding="utf-8")
    catalog = json.dumps(load_role_catalog(), ensure_ascii=False)

    assert set(phase_source) == {"schema", "sourceOfTruth", "phase_sets"}
    assert "roles" not in phase_source
    assert "create_mode" not in production
    assert "resolve_execution_selection" not in production
    assert "RuntimeAssignmentBinding" not in production
    assert "SKILL.md" not in catalog
    assert "private_key" not in catalog
