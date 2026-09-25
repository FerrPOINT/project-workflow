from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_workflow.workflow_contract import load_role_catalog, validate_pinned_contract


def test_developer_catalog_has_all_backend_selected_modes_and_canonical_skills() -> None:
    roles = load_role_catalog()["roles"]
    developer = roles["developer"]

    assert [mode["key"] for mode in developer["modes"]] == [
        "initial",
        "rework",
        "integration",
        "integration_rework",
    ]
    assert developer["workflow"] == "hermes-sdlc:developer"
    assert "project-workflow-executor" in developer["skills"]
    assert "relevanter-tech-operator" in developer["skills"]
    assert "using-rtech" not in developer["skills"]
    assert {config["workflow"] for config in roles.values()} == {
        f"hermes-sdlc:{role}" for role in roles
    }
    assert "project_manager" in roles
    assert "project-manager" not in roles


def test_catalog_matches_the_accepted_role_skill_manifest() -> None:
    catalog = load_role_catalog()
    assert catalog["businessRoutingRegistry"] == "taskWorkspaceExecutionRoutingRegistry"
    assert catalog["skillsCatalogRevision"] == "be9839364d5037a28ab791a591cf6eef690c93bc"
    expected = {
        "project_manager": ["project-workflow-executor", "relevanter-business-operator"],
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
    assert {role: config["skills"] for role, config in catalog["roles"].items()} == expected
    assert sum(len(config["modes"]) for config in catalog["roles"].values()) == 13


def test_catalog_has_exact_modes_and_distinct_substantive_mode_contracts() -> None:
    catalog = load_role_catalog()
    expected = {
        "project_manager": ["draft"],
        "analyst": ["analysis"],
        "architect": ["decomposition"],
        "developer": ["initial", "rework", "integration", "integration_rework"],
        "reviewer": ["delivery", "integration"],
        "tester": ["delivery", "integration"],
        "devops": ["delivery", "integration"],
    }
    definitions: list[str] = []
    for role, expected_keys in expected.items():
        modes = catalog["roles"][role]["modes"]
        assert [mode["key"] for mode in modes] == expected_keys
        for mode in modes:
            phases = catalog["phase_sets"][mode["phase_set"]]
            assert 8 <= len(phases) <= 12
            assert mode["name"] and mode["description"]
            assert mode["instruction"] and mode["check"] and mode["evidence"]
            assert all(phase["code"] and phase["name"] and phase["description"] for phase in phases)
            definitions.append(json.dumps({"mode": mode, "phases": phases}, ensure_ascii=False, sort_keys=True))

    assert len(definitions) == len(set(definitions))


@pytest.mark.parametrize(
    ("role", "profile", "workflow", "legacy_mode"),
    [
        ("architect", "hermes-sdlc-architect", "hermes-sdlc:architect", "architecture"),
        ("reviewer", "hermes-sdlc-reviewer", "hermes-sdlc:reviewer", "review"),
        ("reviewer", "hermes-sdlc-reviewer", "hermes-sdlc:reviewer", "aggregate_review"),
        ("tester", "hermes-sdlc-quality", "hermes-sdlc:tester", "testing"),
        ("tester", "hermes-sdlc-quality", "hermes-sdlc:tester", "aggregate_testing"),
        ("devops", "hermes-sdlc-operations", "hermes-sdlc:devops", "deploy"),
        ("devops", "hermes-sdlc-operations", "hermes-sdlc:devops", "aggregate_deploy"),
    ],
)
def test_literal_contract_rejects_every_superseded_mode(
    role: str,
    profile: str,
    workflow: str,
    legacy_mode: str,
) -> None:
    with pytest.raises(ValueError, match="mode"):
        validate_pinned_contract(
            role=role,
            profile=profile,
            workflow=workflow,
            mode=legacy_mode,
        )


def test_pinned_contract_has_no_mode_fallback_or_profile_override() -> None:
    contract = validate_pinned_contract(
        role="developer",
        profile="hermes-sdlc-developer",
        workflow="hermes-sdlc:developer",
        mode="integration_rework",
    )
    assert contract.mode == "integration_rework"

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


def test_contract_module_does_not_define_a_second_runtime_binding_ledger() -> None:
    package_root = Path(__file__).parents[1] / "project_workflow"
    production = "\n".join(
        path.read_text(encoding="utf-8") for path in package_root.rglob("*.py") if "migrations" not in path.parts
    )

    for forbidden in (
        "RuntimeAssignmentBinding",
        "WorkspaceLease",
        "QueueItem",
        "HermesSessionBinding",
        "active_run_id",
    ):
        assert forbidden not in production


def test_role_catalog_is_configuration_not_installed_skill_content() -> None:
    raw = json.dumps(load_role_catalog(), ensure_ascii=False)
    assert "SKILL.md" not in raw
    assert "private_key" not in raw


def test_legacy_project_manager_role_is_migrated_but_ambiguous_keys_fail(tmp_path: Path) -> None:
    base = load_role_catalog()
    legacy = dict(base)
    legacy_roles = dict(base["roles"])
    pm = dict(legacy_roles.pop("project_manager"))
    pm["workflow"] = "hermes-sdlc:project-manager"
    legacy_roles["project-manager"] = pm
    legacy["roles"] = legacy_roles
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")

    migrated = load_role_catalog(path)
    assert "project_manager" in migrated["roles"]
    assert migrated["roles"]["project_manager"]["workflow"] == "hermes-sdlc:project_manager"

    ambiguous = dict(legacy)
    ambiguous["roles"] = {**legacy_roles, "project_manager": pm}
    path.write_text(json.dumps(ambiguous), encoding="utf-8")
    with pytest.raises(ValueError, match="Ambiguous"):
        load_role_catalog(path)
