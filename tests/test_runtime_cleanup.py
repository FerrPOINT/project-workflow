"""Regression tests for runtime cleanup and seed hygiene."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow import config
from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = REPO_ROOT / "project_workflow" / "references" / "seed.json"
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"

EXPECTED_PHASE_PROFILES = {
    "-1": ("orchestrator", "sdlc-orchestrator"),
    "0.0a": ("ops", "sdlc-ops"),
    "0.01": ("orchestrator", "sdlc-orchestrator"),
    "0.000": ("ops", "sdlc-ops"),
    "0.00": ("ops", "sdlc-ops"),
    "0.7": ("ops", "sdlc-ops"),
    "0.9": ("critic", "sdlc-critic"),
    "0.5": ("orchestrator", "sdlc-orchestrator"),
    "0.6": ("researcher", "sdlc-researcher"),
    "1": ("ops", "sdlc-ops"),
    "1.5": ("researcher", "sdlc-researcher"),
    "2": ("orchestrator", "sdlc-orchestrator"),
    "3": ("orchestrator", "sdlc-orchestrator"),
    "3.5": ("critic", "sdlc-critic"),
    "4": ("coder", "sdlc-coder"),
    "4.5": ("critic", "sdlc-critic"),
    "5": ("reviewer", "sdlc-reviewer"),
    "5.5": ("coder", "sdlc-coder"),
    "6": ("ops", "sdlc-ops"),
    "7": ("ops", "sdlc-ops"),
    "7.5": ("reviewer", "sdlc-reviewer"),
    "7.6": ("reviewer", "sdlc-reviewer"),
    "7.6.R": ("researcher", "sdlc-researcher"),
    "7.7": ("critic", "sdlc-critic"),
    "8": ("ops", "sdlc-ops"),
    "9": ("orchestrator", "sdlc-orchestrator"),
    "10": ("orchestrator", "sdlc-orchestrator"),
}

FORBIDDEN_ACTIVE_CATALOG_TERMS = {
    "github",
    "pull request",
    "glab_token",
    "verify-suite",
    "workflow-jira",
    "info/sprint",
    "origin/develop",
    "project-knowledge",
    "hrflow",
}


def _phase_by_code(code: str) -> dict:
    items = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for item in items:
        if str(item.get("code", item.get("id", ""))).strip() == code:
            return item
    raise AssertionError(f"Phase {code} not found in seed catalog")


def test_default_bootstrap_project_prefixes_are_project_specific(tmp_path):
    uow = SAUnitOfWork(f"sqlite:///{tmp_path / 'workflow.db'}")
    uow.init()

    project = next((p for p in uow.get_projects() if p["code"] == "TASK"), None)
    assert project is not None
    assert project["key_prefixes"] == config.DEFAULT_TASK_KEY_PREFIXES
    assert project["key_prefixes"] == ["TASK"]


def test_compose_passes_openrouter_evaluator_configuration_to_api():
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "OPENAI_BASE_URL: ${OPENAI_BASE_URL:-https://openrouter.ai/api/v1}" in compose
    assert "OPENAI_MODEL: ${OPENAI_MODEL:-z-ai/glm-5.2}" in compose
    assert "OPENAI_API_KEY: ${OPENAI_API_KEY:-}" in compose
    assert "OPENAI_REASONING_EFFORT: ${OPENAI_REASONING_EFFORT:-none}" in compose


def test_seed_catalog_task_intake_and_preflight_have_real_content():
    for code in ("-1", "1"):
        phase = _phase_by_code(code)
        assert phase["instructions"], f"Phase {code} must keep instructions"
        assert phase["checks"], f"Phase {code} must keep checks"
        assert phase["evidence"], f"Phase {code} must keep evidence"

        instruction_descriptions = {item["description"].strip() for item in phase["instructions"]}
        check_descriptions = {item["description"].strip() for item in phase["checks"]}
        evidence_descriptions = {item["description"].strip() for item in phase["evidence"]}

        assert "X" not in instruction_descriptions
        assert "Check 1" not in check_descriptions
        assert "Evidence 1" not in evidence_descriptions


def test_seed_catalog_order_is_self_consistent():
    phases = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    codes = [str(phase.get("code", phase.get("id", ""))).strip() for phase in phases]
    assert len(codes) == len(set(codes)) == 27
    assert [phase.get("phase_order") for phase in phases] == list(range(1, len(phases) + 1))


def test_seed_catalog_has_no_legacy_provider_or_task_system_contracts():
    active_catalog = SEED_PATH.read_text(encoding="utf-8").casefold()

    found = sorted(term for term in FORBIDDEN_ACTIVE_CATALOG_TERMS if term in active_catalog)

    assert found == []


def test_seed_catalog_uses_gitlab_manual_merge_contract():
    phase_7 = _phase_by_code("7")
    phase_77 = _phase_by_code("7.7")
    phase_8 = _phase_by_code("8")

    assert phase_7["name"] == "Merge Request"
    assert "GitLab merge request" in phase_7["description"]
    assert "ручного merge Maintainer" in phase_77["next_recommendation"]
    assert any("Hermes не выполняет merge" in item["description"] for item in phase_77["checks"])
    assert phase_8["name"] == "Delivery Verification"
    assert any("merged commit" in item["description"] for item in phase_8["checks"])


def test_seed_catalog_parallel_links_form_expected_groups():
    phases = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    by_code = {str(phase["code"]): phase for phase in phases}
    expected_groups = [
        {"0.6", "1"},
        {"1.5", "2"},
        {"4.5", "5"},
        {"7.5", "7.6", "7.6.R"},
    ]

    for group in expected_groups:
        assert all(by_code[code]["execution_type"] == "parallel" for code in group)
        assert all(by_code[code].get("parallel_with") in group for code in group)


def test_seed_catalog_rollback_topology_is_stable():
    phases = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    rollback_targets = {
        str(phase["code"]): phase.get("rollback_target")
        for phase in phases
        if phase.get("rollback_target") is not None
    }

    assert rollback_targets == {
        "0.9": "0.0a",
        "3.5": "3",
        "4.5": "4",
        "7.5": "4",
        "7.6": "4",
    }


def test_seed_catalog_names_match_runtime_progress_template():
    phases = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    seed_names = {
        str(phase.get("code", phase.get("id", ""))).strip(): str(phase.get("name", "")).strip() for phase in phases
    }

    from project_workflow.infrastructure.db.uow import SAUnitOfWork

    uow = SAUnitOfWork()
    uow.init()
    schema.ensure_phase_catalog(uow)
    phases_db = uow.get_phases()
    progress_names = {str(phase.get("code", "")).strip(): str(phase.get("name", "")).strip() for phase in phases_db}

    assert seed_names == progress_names


def test_seed_catalog_has_no_blank_instruction_descriptions():
    phases = json.loads(SEED_PATH.read_text(encoding="utf-8"))

    blanks: list[str] = []
    for phase in phases:
        phase_code = str(phase.get("code", phase.get("id", "?"))).strip()
        for instruction in phase.get("instructions", []):
            description = str(instruction.get("description", "")).strip()
            if not description:
                blanks.append(f"{phase_code}#{instruction.get('step_num', '?')}")

    assert blanks == []


def test_seed_catalog_instruction_descriptions_avoid_cross_phase_findings_meta_language():
    phases = json.loads(SEED_PATH.read_text(encoding="utf-8"))

    bad: list[str] = []
    for phase in phases:
        phase_code = str(phase.get("code", phase.get("id", "?"))).strip()
        for instruction in phase.get("instructions", []):
            description = str(instruction.get("description", "")).strip()
            lowered = description.lower()
            if "findings" in lowered or "phase 1" in lowered or "phase 2" in lowered:
                bad.append(f"{phase_code}#{instruction.get('step_num', '?')}: {description}")

    assert bad == []


def test_seed_catalog_instruction_descriptions_do_not_use_or_analog_placeholders():
    phases = json.loads(SEED_PATH.read_text(encoding="utf-8"))

    bad: list[str] = []
    for phase in phases:
        phase_code = str(phase.get("code", phase.get("id", "?"))).strip()
        for instruction in phase.get("instructions", []):
            description = str(instruction.get("description", "")).strip()
            if "или аналог" in description.lower():
                bad.append(f"{phase_code}#{instruction.get('step_num', '?')}: {description}")

    assert bad == []


def test_seed_catalog_parallelism_uses_phase_runs_instead_of_fake_instruction_batches():
    # Genuine parallel pairs/groups in seed.json (have parallel_with partner)
    expected_parallel_phase_codes = {"0.6", "1", "1.5", "2", "4.5", "5", "7.5", "7.6", "7.6.R"}
    for code in expected_parallel_phase_codes:
        phase = _phase_by_code(code)
        assert phase["execution_type"] == "parallel", f"Phase {code} must be marked parallel at phase level"

    # Sequential phases must NOT be falsely marked parallel
    sequential_codes = {
        "-1",
        "0.0a",
        "0.00",
        "0.01",
        "0.000",
        "0.7",
        "0.9",
        "0.5",
        "3",
        "3.5",
        "4",
        "5.5",
        "6",
        "7",
        "7.7",
        "8",
        "9",
        "10",
    }
    for code in sequential_codes:
        phase = _phase_by_code(code)
        assert phase["execution_type"] == "sync", f"Phase {code} must be sequential (sync)"

    for code in ("0.0a", "0.6", "7.5", "7.6", "7.6.R", "9"):
        phase = _phase_by_code(code)
        instruction_types = [item.get("execution_type", "sync") for item in phase.get("instructions", [])]
        assert instruction_types, f"Phase {code} must keep instructions"
        assert all(item == "sync" for item in instruction_types), (
            f"Phase {code} instructions must stay sequential; parallel belongs on the phase run"
        )


def test_seed_catalog_role_bound_phases_are_fully_filled_with_agents_skills_and_checks():
    for code, (agent_name, profile) in EXPECTED_PHASE_PROFILES.items():
        phase = _phase_by_code(code)
        assert phase.get("delegate", {}).get("agent") == agent_name, f"Phase {code} must pick agent {agent_name}"
        assert phase.get("delegate", {}).get("hermes_profile") == profile
        assert phase.get("instructions"), f"Phase {code} must keep instructions"
        assert phase.get("checks"), f"Phase {code} must keep checks"
        assert phase.get("evidence"), f"Phase {code} must keep evidence"

        for instruction in phase["instructions"]:
            skills = instruction.get("skills") or []
            assert isinstance(skills, list)
            assert all(
                isinstance(skill, str)
                and skill
                and skill == skill.strip()
                and all(char.islower() or char.isdigit() or char == "-" for char in skill)
                for skill in skills
            )
        assert phase["instructions"][0]["skills"][0] == "project-workflow-executor"


def test_db_init_assigns_agents_to_role_bound_default_phases(tmp_path):
    uow = SAUnitOfWork(f"sqlite:///{tmp_path / 'workflow.db'}")
    uow.init()
    schema.ensure_phase_catalog(uow)

    agents_by_id = {agent["id"]: agent["name"] for agent in uow.get_agents()}
    profiles_by_agent_id = {agent["id"]: agent["hermes_profile"] for agent in uow.get_agents()}
    for code, (expected_agent_name, expected_profile) in EXPECTED_PHASE_PROFILES.items():
        phase = uow.get_phase_by_code(code)
        assert phase is not None, f"Phase {code} not found"
        assert phase.get("agent_id") is not None, f"Phase {code} must resolve selected agent"
        assert agents_by_id[phase["agent_id"]] == expected_agent_name
        assert profiles_by_agent_id[phase["agent_id"]] == expected_profile
