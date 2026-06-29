"""Tests for WizardMemory model and MemoryStore."""
from __future__ import annotations

import pytest

from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.wizard.memory import MemoryStore


def test_wizard_memory_model_table_exists():
    uow = SAUnitOfWork()
    uow.create_all()
    # If table does not exist this will raise.
    from project_workflow.infrastructure.db.models import WizardMemory

    store = MemoryStore(uow)
    rows = store.list_for_task(0)
    assert rows == []
    uow.close()


def test_memory_store_add_and_list():
    uow = SAUnitOfWork()
    uow.create_all()
    store = MemoryStore(uow)

    project_id = uow.projects.create({"workflow_id": 1, "code": "mem-test", "name": "Mem Test"})
    uow.commit()
    task_id = uow.tasks.create(
        {"project_id": project_id, "task_key": "MEM-1", "title": "T", "current_phase": "-1"}
    )
    uow.commit()

    mem_id = store.add(task_id, "lesson", "Always commit after evaluate.")
    assert isinstance(mem_id, int)
    uow.commit()

    rows = store.list_for_task(task_id)
    assert len(rows) == 1
    assert rows[0]["memory_type"] == "lesson"
    assert rows[0]["content"] == "Always commit after evaluate."
    uow.close()


def test_memory_store_find_by_type():
    uow = SAUnitOfWork()
    uow.create_all()
    store = MemoryStore(uow)

    project_id = uow.projects.create({"workflow_id": 1, "code": "mem-test2", "name": "Mem Test 2"})
    uow.commit()
    task_id = uow.tasks.create(
        {"project_id": project_id, "task_key": "MEM-2", "title": "T", "current_phase": "-1"}
    )
    uow.commit()

    store.add(task_id, "blocker_pattern", "Tests timeout without --forked")
    store.add(task_id, "lesson", "Use commit")
    uow.commit()

    blockers = store.find_by_type(task_id, "blocker_pattern")
    assert len(blockers) == 1
    assert blockers[0]["memory_type"] == "blocker_pattern"

    with pytest.raises(ValueError):
        store.add(task_id, "bad_type", "x")
    with pytest.raises(ValueError):
        store.find_by_type(task_id, "bad_type")
    uow.close()


def test_memory_store_format_for_prompt():
    uow = SAUnitOfWork()
    uow.create_all()
    store = MemoryStore(uow)

    project_id = uow.projects.create({"workflow_id": 1, "code": "mem-test3", "name": "Mem Test 3"})
    uow.commit()
    task_id = uow.tasks.create(
        {"project_id": project_id, "task_key": "MEM-3", "title": "T", "current_phase": "-1"}
    )
    uow.commit()

    store.add(task_id, "preference", "No emojis in output")
    uow.commit()

    bullets = store.format_for_prompt(task_id)
    assert bullets == ["[preference] No emojis in output"]
    uow.close()
