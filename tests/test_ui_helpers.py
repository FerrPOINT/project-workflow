"""Tests for interfaces.ui.helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from project_workflow.interfaces.ui.helpers import (
    _build_parallel_phase_blocks,
    _resolve_task_phase,
    _resolve_task_phase_local,
    _run_to_dict,
)
from project_workflow.interfaces.ui.templates import _group_instructions


def test_group_instructions():
    assert _group_instructions([]) == []
    a = {"id": 1, "execution_type": "sync"}
    b = {"id": 2, "execution_type": "parallel"}
    c = {"id": 3, "execution_type": "sync"}
    assert _group_instructions([a, b, c]) == [[a, b], [c]]


def test_run_to_dict():
    assert _run_to_dict({"id": 1}) == {"id": 1}

    class Item:
        def to_dict(self):
            return {"id": 2}

    assert _run_to_dict(Item()) == {"id": 2}
    assert _run_to_dict([(1, "a")]) == {1: "a"}


def test_build_parallel_phase_blocks():
    sync = {"id": 1, "code": "s1", "execution_type": "sync"}
    par = {"id": 2, "code": "p2", "execution_type": "parallel", "parallel_with": "p3"}
    partner = {"id": 3, "code": "p3", "execution_type": "parallel"}
    single = {"id": 3, "code": "s3", "execution_type": "sync"}
    blocks = _build_parallel_phase_blocks([sync, par, partner, single])
    assert [block["kind"] for block in blocks] == ["single", "parallel", "single"]
    assert [phase["code"] for phase in blocks[1]["phases"]] == ["p2", "p3"]
    assert blocks[1]["status"] == "wait"


def test_resolve_task_phase():
    db = MagicMock()
    db.get_phases.return_value = [{"id": 1, "code": "p1"}, {"id": 2, "code": "p2"}]
    token, phase = _resolve_task_phase("p2", db, workflow_id=1)
    assert token == "p2"
    assert phase == {"id": 2, "code": "p2"}


def test_resolve_task_phase_prefers_numeric_code_over_db_id():
    db = MagicMock()
    db.get_phases.return_value = [
        {"id": 10, "code": "0.8", "name": "Wrong by id"},
        {"id": 27, "code": "10", "name": "Auto-Improve"},
    ]

    token, phase = _resolve_task_phase("10", db, workflow_id=1)

    assert token == "10"
    assert phase == {"id": 27, "code": "10", "name": "Auto-Improve"}


def test_resolve_task_phase_has_no_global_fallback():
    db = MagicMock()
    token, phase = _resolve_task_phase("7", db)
    assert token == "7"
    assert phase is None
    db.get_phases.assert_not_called()


def test_resolve_task_phase_local():
    phases = [{"id": 1, "code": "p1"}, {"id": 2, "code": "p2"}]
    token, phase = _resolve_task_phase_local("p2", phases)
    assert token == "p2"
    assert phase == {"id": 2, "code": "p2"}

    token, phase = _resolve_task_phase_local("99", phases)
    assert phase is None
