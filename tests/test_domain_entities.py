"""Tests for domain entities."""

from __future__ import annotations

from project_workflow.domain import (
    Agent,
    Phase,
    PhaseCode,
    Project,
    Task,
    TaskKey,
    TaskStepHistoryEntry,
    Workflow,
)


def test_task_key_str():
    k = TaskKey("A-1", "A", 1)
    assert str(k) == "A-1"


def test_phase_code_str():
    assert str(PhaseCode("1")) == "1"


def test_phase_to_dict():
    p = Phase(id=1, code="p1", name="P1")
    d = p.to_dict()
    assert d["code"] == "p1"
    assert d["name"] == "P1"


def test_agent_to_dict():
    a = Agent(id=2, name="Coder")
    assert a.to_dict() == {"id": 2, "name": "Coder", "description": "", "hermes_profile": None}


def test_workflow_to_dict():
    w = Workflow(id=3, name="W", is_default=True)
    data = w.to_dict()
    assert data["is_default"] is True
    assert "theme_icon" not in data
    assert "theme_color" not in data


def test_project_to_dict():
    p = Project(id=4, code="PRJ", key_prefixes=["PRJ"])
    data = p.to_dict()
    assert data["key_prefixes"] == ["PRJ"]
    assert data["theme_icon"] == "project"
    assert data["theme_color"] == "#5E6AD2"


def test_task_to_dict():
    t = Task(
        id=5,
        task_key="A-1",
        workflow_id=2,
        current_phase_id=3,
        current_phase_code="p1",
        current_phase_name="Первая фаза",
    )
    assert t.to_dict()["task_key"] == "A-1"
    assert t.to_dict()["current_phase_id"] == 3
    assert t.to_dict()["current_phase_code"] == "p1"
    assert t.to_dict()["current_phase_name"] == "Первая фаза"


def test_task_step_history_entry_to_dict():
    r = TaskStepHistoryEntry(id=6, task_id=1, phase_id=2, verdict="pass")
    assert r.to_dict()["verdict"] == "pass"
    assert r.to_dict()["covered_item_ids"] == []
