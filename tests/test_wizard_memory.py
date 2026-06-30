"""Tests for wizard.memory.MemoryStore."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from project_workflow.wizard.memory import MemoryStore


def _make_uow(rows=None):
    uow = MagicMock()
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.all.return_value = rows or []
    uow.session.query.return_value = query
    return uow, query


def test_add_memory():
    uow, _ = _make_uow()
    uow.session.flush = MagicMock()
    store = MemoryStore(uow)
    # mem.id is None until flush assigns it; mock the created object.
    def _add(obj):
        obj.id = 42
    uow.session.add.side_effect = _add
    mem_id = store.add(1, "lesson", "remember this")
    assert mem_id == 42
    uow.session.add.assert_called_once()
    uow.session.flush.assert_called_once()


def test_add_invalid_type():
    store = MemoryStore(MagicMock())
    with pytest.raises(ValueError, match="Invalid memory_type"):
        store.add(1, "bad", "x")


def test_list_for_task():
    row = MagicMock()
    row.id = 1
    row.task_id = 2
    row.memory_type = "lesson"
    row.content = "c"
    row.created_at = "2024-01-01"
    uow, _ = _make_uow(rows=[row])
    store = MemoryStore(uow)
    result = store.list_for_task(2)
    assert len(result) == 1
    assert result[0]["memory_type"] == "lesson"


def test_find_by_type():
    row = MagicMock()
    row.id = 1
    row.task_id = 2
    row.memory_type = "correction"
    row.content = "fix"
    row.created_at = "2024-01-01"
    uow, _ = _make_uow(rows=[row])
    store = MemoryStore(uow)
    result = store.find_by_type(2, "correction")
    assert len(result) == 1


def test_find_by_type_invalid():
    store = MemoryStore(MagicMock())
    with pytest.raises(ValueError, match="Invalid memory_type"):
        store.find_by_type(1, "bad")


def test_format_for_prompt():
    row = MagicMock()
    row.id = 1
    row.task_id = 2
    row.memory_type = "lesson"
    row.content = "do X"
    row.created_at = "2024-01-01"
    uow, _ = _make_uow(rows=[row])
    store = MemoryStore(uow)
    bullets = store.format_for_prompt(2)
    assert bullets == ["[lesson] do X"]
