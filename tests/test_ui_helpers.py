"""Tests for strict UI helpers."""

from __future__ import annotations

import pytest

from project_workflow.interfaces.ui.helpers import (
    _build_parallel_phase_blocks,
    _resolve_task_phase_id,
    _run_to_dict,
)
from project_workflow.interfaces.ui.templates import _group_instructions


def test_group_instructions():
    a = {"id": 1, "execution_type": "sync"}
    b = {"id": 2, "execution_type": "parallel"}
    c = {"id": 3, "execution_type": "sync"}
    assert _group_instructions([]) == []
    assert _group_instructions([a, b, c]) == [[a, b], [c]]


def test_run_to_dict():
    class Item:
        def to_dict(self):
            return {"id": 2}

    assert _run_to_dict({"id": 1}) == {"id": 1}
    assert _run_to_dict(Item()) == {"id": 2}
    assert _run_to_dict([(1, "a")]) == {1: "a"}


def test_build_parallel_phase_blocks_uses_numeric_links():
    sync = {"id": 1, "code": "s1", "execution_type": "sync"}
    parallel = {
        "id": 2,
        "code": "p2",
        "execution_type": "parallel",
        "parallel_with_phase_id": 3,
    }
    partner = {"id": 3, "code": "p3", "execution_type": "parallel"}
    final = {"id": 4, "code": "s4", "execution_type": "sync"}

    blocks = _build_parallel_phase_blocks([sync, parallel, partner, final])

    assert [block["kind"] for block in blocks] == ["single", "parallel", "single"]
    assert [phase["id"] for phase in blocks[1]["phases"]] == [2, 3]


def test_resolve_task_phase_id_is_strict_and_scoped():
    phases = [{"id": 1, "code": "p1"}, {"id": 2, "code": "p2"}]
    assert _resolve_task_phase_id(2, phases) == {"id": 2, "code": "p2"}
    with pytest.raises(ValueError, match="отсутствует"):
        _resolve_task_phase_id(3, phases)
    with pytest.raises(ValueError, match="положительным"):
        _resolve_task_phase_id(True, phases)
