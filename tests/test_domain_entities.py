"""Tests for domain entities."""

from __future__ import annotations

from project_workflow.domain import (
    Agent,
    Phase,
    PhaseCode,
    Project,
    SupervisorRun,
    Task,
    TaskKey,
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
    assert a.to_dict() == {"id": 2, "name": "Coder", "description": ""}


def test_workflow_to_dict():
    w = Workflow(id=3, name="W", is_default=True)
    assert w.to_dict()["is_default"] is True


def test_project_to_dict():
    p = Project(id=4, code="PRJ", key_prefixes=["PRJ"])
    assert p.to_dict()["key_prefixes"] == ["PRJ"]


def test_task_to_dict():
    t = Task(id=5, task_key="A-1", current_phase="p1")
    assert t.to_dict()["task_key"] == "A-1"
    assert t.to_dict()["current_phase"] == "p1"


def test_supervisor_run_to_dict():
    r = SupervisorRun(id=6, task_id=1, phase_id=2, verdict="pass")
    assert r.to_dict()["verdict"] == "pass"
    assert r.to_dict()["covered"] == []
