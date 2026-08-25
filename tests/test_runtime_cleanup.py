"""Canonical Business + Tech catalog and runtime configuration tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_workflow import config
from project_workflow.domain.phase_grouping import group_parallel_phases
from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._db_helpers import prepare_sqlite_uow

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = REPO_ROOT / "project_workflow" / "references" / "seed.json"
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"

EXPECTED_CODES = [
    "1.INTAKE",
    "2.REQUIREMENTS",
    "3.DOR_GATE",
    "4.START",
    "5.RESEARCH",
    "5.PREFLIGHT",
    "6.SOLUTION",
    "6.TEST_PLAN",
    "7.PLAN_GATE",
    "8.IMPLEMENT",
    "9.PR",
    "10.REVIEW",
    "10.QA",
    "10.DATAFLOW",
    "11.RUNTIME",
    "12.RELEASE_GATE",
    "13.DELIVERY",
    "14.CLOSE",
    "15.RETRO",
]

EXPECTED_PROFILES = {
    "1.INTAKE": "sdlc-orchestrator",
    "2.REQUIREMENTS": "sdlc-orchestrator",
    "3.DOR_GATE": None,
    "4.START": "sdlc-ops",
    "5.RESEARCH": "sdlc-researcher",
    "5.PREFLIGHT": "sdlc-ops",
    "6.SOLUTION": "sdlc-orchestrator",
    "6.TEST_PLAN": "sdlc-critic",
    "7.PLAN_GATE": None,
    "8.IMPLEMENT": "sdlc-coder",
    "9.PR": "sdlc-ops",
    "10.REVIEW": "sdlc-reviewer",
    "10.QA": "sdlc-reviewer",
    "10.DATAFLOW": "sdlc-researcher",
    "11.RUNTIME": "sdlc-ops",
    "12.RELEASE_GATE": None,
    "13.DELIVERY": "sdlc-ops",
    "14.CLOSE": "sdlc-orchestrator",
    "15.RETRO": "sdlc-critic",
}


def _items() -> list[dict]:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def test_default_bootstrap_uses_run_prefix(tmp_path):
    uow = SAUnitOfWork(f"sqlite:///{tmp_path / 'workflow.db'}")
    prepare_sqlite_uow(uow)

    assert [workflow["name"] for workflow in uow.get_workflows()] == [config.DEFAULT_WORKFLOW_NAME]
    project = next(project for project in uow.get_projects() if project["code"] == "RUN")
    assert project["key_prefixes"] == ["RUN"]
    assert all(project["code"] != "TASK" for project in uow.get_projects())


def test_compose_passes_openrouter_evaluator_configuration_to_api():
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    assert "OPENAI_BASE_URL: ${OPENAI_BASE_URL:-https://openrouter.ai/api/v1}" in compose
    assert "OPENAI_MODEL: ${OPENAI_MODEL:-z-ai/glm-5.2}" in compose
    assert "OPENAI_API_KEY: ${OPENAI_API_KEY:-}" in compose
    assert "OPENAI_REASONING_EFFORT: ${OPENAI_REASONING_EFFORT:-none}" in compose


def test_seed_catalog_has_exact_codes_and_order():
    phases = _items()
    assert [phase["code"] for phase in phases] == EXPECTED_CODES
    assert [phase["phase_order"] for phase in phases] == list(range(1, 20))


def test_seed_catalog_has_exact_assignment_groups():
    groups = group_parallel_phases(
        _items(),
        code_of=lambda phase: phase["code"],
        execution_type_of=lambda phase: phase.get("execution_type", "sync"),
        parallel_with_of=lambda phase: phase.get("parallel_with"),
    )
    codes = [[phase["code"] for phase in group] for group in groups]
    assert len(codes) == 15
    assert [group for group in codes if len(group) > 1] == [
        ["5.RESEARCH", "5.PREFLIGHT"],
        ["6.SOLUTION", "6.TEST_PLAN"],
        ["10.REVIEW", "10.QA", "10.DATAFLOW"],
    ]


def test_seed_catalog_actor_and_profile_bindings_are_complete():
    for phase in _items():
        delegate = phase.get("delegate") or {}
        expected_profile = EXPECTED_PROFILES[phase["code"]]
        assert delegate.get("hermes_profile") == expected_profile
        assert delegate.get("agent") == ("codex-operator" if expected_profile is None else delegate.get("agent"))
        assert phase.get("instructions")
        assert phase.get("checks")
        assert phase.get("evidence")
        for instruction in phase["instructions"]:
            assert str(instruction.get("description") or "").strip()
            assert all(
                skill == skill.strip()
                and skill
                and all(char.islower() or char.isdigit() or char == "-" for char in skill)
                for skill in instruction.get("skills") or []
            )


def test_due_date_and_retired_external_runtime_are_absent_from_active_contract():
    catalog = SEED_PATH.read_text(encoding="utf-8").casefold()
    assert "duedate" in catalog
    assert "не передавая duedate" in catalog
    assert "jira" not in catalog
    assert "gitlab" not in catalog
    assert "merge request" not in catalog


def test_business_status_contract_matches_default_project_catalog():
    catalog = SEED_PATH.read_text(encoding="utf-8")
    assert "Статус Business-задачи равен In Progress" in catalog
    assert "Статус Business-задачи равен In Review" not in catalog


def test_tech_phases_reference_the_canonical_using_rtech_skill():
    phases = _items()
    skill_phases = {
        phase["code"]
        for phase in phases
        if any(
            "using-rtech" in (instruction.get("skills") or [])
            for instruction in phase["instructions"]
        )
    }

    assert skill_phases == {"4.START", "9.PR", "11.RUNTIME", "12.RELEASE_GATE", "13.DELIVERY"}
    assert all(
        "rtech" not in (instruction.get("skills") or [])
        for phase in phases
        for instruction in phase["instructions"]
    )


def test_post_merge_phases_have_no_workflow_rollback_target():
    by_code = {phase["code"]: phase for phase in _items()}
    assert by_code["12.RELEASE_GATE"]["rollback_target"] == "8.IMPLEMENT"
    for code in ("13.DELIVERY", "14.CLOSE", "15.RETRO"):
        assert by_code[code].get("rollback_target") is None


def test_sqlite_bootstrap_preserves_operator_without_fake_hermes_profile(tmp_path):
    uow = SAUnitOfWork(f"sqlite:///{tmp_path / 'workflow.db'}")
    prepare_sqlite_uow(uow)

    phases = schema.load_phases_from_db(uow)
    assert len(phases) == 19
    by_code = {phase.code: phase for phase in phases}
    for code, profile in EXPECTED_PROFILES.items():
        phase = by_code[code]
        assert phase.delegate is not None
        assert phase.delegate.hermes_profile == profile
        if profile is None:
            assert phase.delegate.agent == "codex-operator"
