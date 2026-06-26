"""Regression tests for runtime cleanup and seed hygiene."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow import config
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.db import schema



REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = REPO_ROOT / "project_workflow" / "references" / "seed.json"

VALID_WORKFLOW_SKILLS = {
    "agent-workflow-patterns",
    "llm-wiki",
    "repo-workflow",
    "test-driven-development",
    "workflow-code-intelligence",
    "workflow-systematic-debugging",
    "workflow-writing-plans",
}

EXPECTED_ROLE_AGENTS = {
    "0.6": "researcher",
    "0.9": "critic",
    "1.5": "researcher",
    "3.5": "critic",
    "4.5": "critic",
    "7.5": "reviewer",
    "7.6": "reviewer",
    "7.6.R": "researcher",
    "7.7": "critic",
    "8": "ops",
    "9": "coder",
}


def _phase_by_code(code: str) -> dict:
    items = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for item in items:
        if str(item.get("code", item.get("id", ""))).strip() == code:
            return item
    raise AssertionError(f"Phase {code} not found in seed catalog")


def test_default_bootstrap_project_prefixes_are_project_specific(tmp_path):
    uow = SAUnitOfWork(str(tmp_path / "workflow.db"))
    uow.init()

    project = uow.get_project_by_code("TASK")
    assert project is not None
    assert project["key_prefixes"] == config.DEFAULT_TASK_KEY_PREFIXES
    assert project["key_prefixes"] == ["TASK"]


def test_sanitize_runtime_state_removes_known_test_residue_and_dedupes_agents(tmp_path):
    uow = SAUnitOfWork(str(tmp_path / "workflow.db"))
    uow.init()

    ui_test_project_id = uow.create_project({
        "code": "UITEST",
        "name": "UI Test Project",
        "key_prefixes": ["UITEST"],
    })
    uow.create_task({
        "project_id": ui_test_project_id,
        "task_key": "UITEST-401",
        "title": "Проверка project-aware UI",
        "status": "active",
        "current_phase": "-1",
    })
    uow.create_agent({"name": "architect", "description": "Проектирует и уточняет контракты"})
    uow.create_agent({"name": "architect", "description": "Проектирует и уточняет контракты"})

    uow.sanitize_runtime_state()

    assert uow.get_project_by_code("UITEST") is None
    assert uow.get_task_by_key("UITEST-401") is None
    assert [agent["name"] for agent in uow.get_agents()].count("architect") == 1

    default_project = uow.get_project_by_code("TASK")
    assert default_project is not None
    assert default_project["key_prefixes"] == ["TASK"]


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


def test_seed_catalog_order_matches_config_phase_order():
    phases = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    codes = [str(phase.get("code", phase.get("id", ""))).strip() for phase in phases]
    assert codes == config.PHASE_ORDER



def test_seed_catalog_names_match_runtime_progress_template():
    phases = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    seed_names = {
        str(phase.get("code", phase.get("id", ""))).strip(): str(phase.get("name", "")).strip()
        for phase in phases
    }

    from project_workflow.infrastructure.db.uow import SAUnitOfWork
    uow = SAUnitOfWork()
    uow.init()
    schema.ensure_phase_catalog(uow)
    phases_db = uow.get_phases()
    progress_names = {
        str(phase.get("code", "")).strip(): str(phase.get("name", "")).strip()
        for phase in phases_db
    }

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
    # Genuine parallel pairs in seed.json (have parallel_with partner)
    expected_parallel_phase_codes = {"5", "7.6", "7.6.R"}
    for code in expected_parallel_phase_codes:
        phase = _phase_by_code(code)
        assert phase["execution_type"] == "parallel", f"Phase {code} must be marked parallel at phase level"

    # Sequential phases must NOT be falsely marked parallel
    sequential_codes = {"-1", "0.0a", "0.00", "1", "2", "0.01", "0.000", "0.7", "0.9", "0.5", "0.6", "3", "3.5", "4", "4.5"}
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
    for code, agent_name in EXPECTED_ROLE_AGENTS.items():
        phase = _phase_by_code(code)
        assert phase.get("selected_agent") == agent_name, f"Phase {code} must pick agent {agent_name}"
        assert phase.get("instructions"), f"Phase {code} must keep instructions"
        assert phase.get("checks"), f"Phase {code} must keep checks"
        assert phase.get("evidence"), f"Phase {code} must keep evidence"

        for instruction in phase["instructions"]:
            skills = instruction.get("skills")
            assert isinstance(skills, list) and skills, f"Phase {code} instruction {instruction.get('step_num')} must declare skills"
            assert set(skills).issubset(VALID_WORKFLOW_SKILLS), (
                f"Phase {code} instruction {instruction.get('step_num')} uses unknown skills: {skills}"
            )


def test_db_init_assigns_selected_agents_to_role_bound_default_phases(tmp_path):
    uow = SAUnitOfWork(str(tmp_path / "workflow.db"))
    uow.init()
    schema.ensure_phase_catalog(uow)

    agents_by_id = {agent["id"]: agent["name"] for agent in uow.get_agents()}
    for code, expected_agent_name in EXPECTED_ROLE_AGENTS.items():
        phase = uow.get_phase_by_code(code)
        assert phase is not None, f"Phase {code} not found"
        assert phase.get("agent_id") is not None, f"Phase {code} must resolve selected agent"
        assert agents_by_id[phase["agent_id"]] == expected_agent_name
