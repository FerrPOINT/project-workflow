"""Regression tests for runtime cleanup and seed hygiene."""

from __future__ import annotations

import json
from pathlib import Path

from wartz_workflow import config
from wartz_workflow.db import WorkflowDB


REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = REPO_ROOT / "wartz_workflow" / "references" / "seed.json"


def _phase_by_code(code: str) -> dict:
    items = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for item in items:
        if str(item.get("code", item.get("id", ""))).strip() == code:
            return item
    raise AssertionError(f"Phase {code} not found in seed catalog")


def test_default_bootstrap_project_patterns_are_project_specific(tmp_path):
    db = WorkflowDB(str(tmp_path / "workflow.db"))
    db.init()

    project = db.get_project_by_code("TASKNEIROKLYUCH")
    assert project is not None
    assert project["key_patterns"] == config.DEFAULT_TASK_KEY_PATTERNS
    assert project["key_patterns"] == [r"^(?P<prefix>TASKNEIROKLYUCH)-(?P<number>[0-9]+)$"]


def test_sanitize_runtime_state_removes_known_test_residue_and_dedupes_agents(tmp_path):
    db = WorkflowDB(str(tmp_path / "workflow.db"))
    db.init()

    ui_test_project_id = db.create_project({
        "code": "UITEST",
        "name": "UI Test Project",
        "key_patterns": [r"^(?P<prefix>UITEST)-(?P<number>[0-9]+)$"],
    })
    db.create_task({
        "task_key": "TASKNEIROKLYUCH-247",
        "title": "Добавить E2E тесты для workflow",
        "status": "active",
        "current_phase": "5",
    })
    db.create_task({
        "project_id": ui_test_project_id,
        "task_key": "UITEST-401",
        "title": "Проверка project-aware UI",
        "status": "active",
        "current_phase": "-1",
    })
    db.create_agent({"name": "architect", "description": "Проектирует и уточняет контракты"})
    db.create_agent({"name": "architect", "description": "Проектирует и уточняет контракты"})

    db.sanitize_runtime_state()

    assert db.get_project_by_code("UITEST") is None
    assert db.get_task_by_key("UITEST-401") is None
    assert db.get_task_by_key("TASKNEIROKLYUCH-247") is None
    assert [agent["name"] for agent in db.get_agents()].count("architect") == 1

    default_project = db.get_project_by_code("TASKNEIROKLYUCH")
    assert default_project is not None
    assert default_project["key_patterns"] == [r"^(?P<prefix>TASKNEIROKLYUCH)-(?P<number>[0-9]+)$"]


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
