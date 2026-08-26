"""Tests for infrastructure.db.models."""

from __future__ import annotations

from project_workflow.infrastructure.db.models import Task, model_to_dict


def test_model_to_dict():
    # Create a transient instance without DB insertion.
    task = Task(
        task_key="A-1",
        title="T",
        project_id=1,
        workflow_id=2,
        current_phase_id=3,
    )
    d = model_to_dict(task)
    assert d["task_key"] == "A-1"
    assert d["title"] == "T"
    assert d["project_id"] == 1
    assert d["workflow_id"] == 2
    assert d["current_phase_id"] == 3
