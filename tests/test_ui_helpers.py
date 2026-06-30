"""Tests for interfaces.ui.helpers."""
from __future__ import annotations

from unittest.mock import MagicMock

from project_workflow.interfaces.ui.helpers import (
    _build_parallel_phase_blocks,
    _group_instructions,
    _parse_key_prefixes,
    _parse_optional_int,
    _resolve_task_phase,
    _resolve_task_phase_local,
    _run_to_dict,
)


def test_parse_optional_int():
    assert _parse_optional_int("5") == 5
    assert _parse_optional_int("0") is None
    assert _parse_optional_int("abc") is None
    assert _parse_optional_int(None) is None
    assert _parse_optional_int("") is None
    assert _parse_optional_int(-3) is None


def test_group_instructions():
    assert _group_instructions([]) == []
    a = {"id": 1, "execution_type": "sync"}
    b = {"id": 2, "execution_type": "parallel"}
    c = {"id": 3, "execution_type": "sync"}
    assert _group_instructions([a, b, c]) == [[a, b], [c]]


def test_parse_key_prefixes():
    assert _parse_key_prefixes(["aa", " bb "]) == ["AA", "BB"]
    assert _parse_key_prefixes("xx\nyy\n") == ["XX", "YY"]
    assert _parse_key_prefixes(None) == []
    assert _parse_key_prefixes(123) == []


def test_run_to_dict():
    assert _run_to_dict({"id": 1}) == {"id": 1}

    class Item:
        def to_dict(self):
            return {"id": 2}

    assert _run_to_dict(Item()) == {"id": 2}
    assert _run_to_dict([(1, "a")]) == {1: "a"}


def test_build_parallel_phase_blocks():
    sync = {"id": 1, "code": "s1", "execution_type": "sync"}
    par = {"id": 2, "code": "p2", "execution_type": "parallel"}
    single = {"id": 3, "code": "s3", "execution_type": "sync"}
    blocks = _build_parallel_phase_blocks([sync, par, single])
    assert len(blocks) == 2
    assert blocks[0]["kind"] == "parallel"
    assert blocks[1]["kind"] == "single"


def test_resolve_task_phase():
    db = MagicMock()
    db.get_phases.return_value = [{"id": 1, "code": "p1"}, {"id": 2, "code": "p2"}]
    db.get_phase.return_value = None
    token, phase = _resolve_task_phase("p2", db)
    assert token == "p2"
    assert phase == {"id": 2, "code": "p2"}


def test_resolve_task_phase_fallback():
    db = MagicMock()
    db.get_phases.return_value = []
    db.get_phase.return_value = {"id": 7, "code": "p7"}
    token, phase = _resolve_task_phase("7", db)
    assert token == "7"
    assert phase == {"id": 7, "code": "p7"}


def test_resolve_task_phase_local():
    phases = [{"id": 1, "code": "p1"}, {"id": 2, "code": "p2"}]
    token, phase = _resolve_task_phase_local("p2", phases)
    assert token == "p2"
    assert phase == {"id": 2, "code": "p2"}

    token, phase = _resolve_task_phase_local("99", phases)
    assert phase is None
