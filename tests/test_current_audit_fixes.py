"""Regression tests for current findings rescued from superseded PR #2."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from project_workflow.application import state as app_state
from project_workflow.application.instruction_service import InstructionService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app

pytestmark = pytest.mark.unit


@pytest.fixture
def uow() -> Iterator[SAUnitOfWork]:
    unit = SAUnitOfWork()
    yield unit
    unit.close()


def _workflow_with_project(unit: SAUnitOfWork, suffix: str) -> tuple[int, int]:
    workflow_id = unit.workflows.create({"name": f"Workflow {suffix}"})
    project_id = unit.projects.create(
        {
            "workflow_id": workflow_id,
            "code": f"PROJECT-{suffix}",
            "name": f"Project {suffix}",
        }
    )
    return workflow_id, project_id


def test_phase_update_preserves_identity_and_coerces_boolean_flags(uow: SAUnitOfWork):
    workflow_id, _ = _workflow_with_project(uow, "phase-a")
    other_workflow_id, _ = _workflow_with_project(uow, "phase-b")
    phase_id = uow.phases.create(
        {
            "workflow_id": workflow_id,
            "code": "phase-a",
            "name": "Original",
            "phase_order": 1,
        }
    )
    uow.commit()

    uow.phases.update(
        phase_id,
        {
            "id": phase_id + 1000,
            "workflow_id": other_workflow_id,
            "name": "Updated",
            "is_seed_managed": True,
            "is_blocker": True,
            "is_delegated": True,
            "is_critic": True,
        },
    )
    uow.commit()

    phase = uow.phases.get_by_id(phase_id)
    assert phase is not None
    assert phase.id == phase_id
    assert phase.workflow_id == workflow_id
    assert phase.name == "Updated"
    assert phase.is_seed_managed is True
    assert phase.is_blocker is True
    assert phase.is_delegated is True
    assert phase.is_critic is True


def test_task_update_preserves_identity_and_ownership(uow: SAUnitOfWork):
    workflow_id, project_id = _workflow_with_project(uow, "task-a")
    _, other_project_id = _workflow_with_project(uow, "task-b")
    uow.phases.create(
        {
            "workflow_id": workflow_id,
            "code": "1.INTAKE",
            "name": "Intake",
            "phase_order": 1,
        }
    )
    task_id = uow.tasks.create(
        {
            "project_id": project_id,
            "task_key": "AUDIT-1",
            "title": "Original",
            "current_phase": "1.INTAKE",
        }
    )
    uow.commit()

    uow.tasks.update(
        task_id,
        {
            "id": task_id + 1000,
            "project_id": other_project_id,
            "title": "Updated",
        },
    )
    uow.commit()

    task = uow.tasks.get_by_id(task_id)
    assert task is not None
    assert task.id == task_id
    assert task.project_id == project_id
    assert task.title == "Updated"


def _phase_with_instructions(
    unit: SAUnitOfWork,
    workflow_id: int,
    code: str,
    descriptions: list[str],
) -> tuple[int, list[int]]:
    phase_id = unit.phases.create(
        {
            "workflow_id": workflow_id,
            "code": code,
            "name": code,
            "phase_order": 1,
        }
    )
    instruction_ids = [
        unit.instructions.create(phase_id, {"description": description, "step_num": index})
        for index, description in enumerate(descriptions, start=1)
    ]
    unit.commit()
    return phase_id, instruction_ids


def test_instruction_service_rejects_duplicates_and_foreign_ids(uow: SAUnitOfWork):
    workflow_id, _ = _workflow_with_project(uow, "instructions")
    first_phase_id, first_ids = _phase_with_instructions(uow, workflow_id, "first", ["one", "two", "three"])
    second_phase_id, second_ids = _phase_with_instructions(uow, workflow_id, "second", ["foreign"])

    with pytest.raises(ValueError, match="unique"):
        InstructionService(uow).reorder_instructions(
            first_phase_id,
            [first_ids[1], second_ids[0], first_ids[0], first_ids[0]],
        )

    reordered = list(uow.instructions.list(first_phase_id))
    assert [row["id"] for row in reordered] == first_ids
    assert [row["step_num"] for row in reordered] == [1, 2, 3]
    assert list(uow.instructions.list(second_phase_id))[0]["step_num"] == 1


def test_instruction_repository_rejects_partial_reorder_without_changes(uow: SAUnitOfWork):
    workflow_id, _ = _workflow_with_project(uow, "partial-order")
    phase_id, instruction_ids = _phase_with_instructions(uow, workflow_id, "partial", ["one", "two", "three"])

    with pytest.raises(ConflictError, match="complete phase order"):
        uow.instructions.reorder(phase_id, [(instruction_ids[1], 1), (instruction_ids[0], 2)])
    uow.rollback()

    rows = list(uow.instructions.list(phase_id))
    assert [row["id"] for row in rows] == instruction_ids
    assert [row["step_num"] for row in rows] == [1, 2, 3]


@contextmanager
def _count_selects(unit: SAUnitOfWork) -> Iterator[list[str]]:
    statements: list[str] = []
    engine = unit.session.get_bind()

    def capture(_conn: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _many: bool) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def test_repository_lists_use_bounded_queries_for_related_data(uow: SAUnitOfWork):
    for index in range(3):
        workflow_id, project_id = _workflow_with_project(uow, f"queries-{index}")
        phase_id = uow.phases.create(
            {
                "workflow_id": workflow_id,
                "code": f"queries-{index}",
                "name": f"Phase {index}",
                "phase_order": 1,
            }
        )
        uow.tasks.create(
            {
                "project_id": project_id,
                "task_key": f"QUERY-{index}",
                "current_phase": str(phase_id),
            }
        )
    uow.commit()
    uow.close()
    fresh = SAUnitOfWork()
    try:
        with _count_selects(fresh) as phase_queries:
            fresh.phases.list()
        with _count_selects(fresh) as project_queries:
            fresh.projects.list()
        with _count_selects(fresh) as task_queries:
            fresh.tasks.list()
    finally:
        fresh.close()

    assert len(phase_queries) == 1
    assert len(project_queries) == 1
    assert len(task_queries) <= 2


class _FakeUoW:
    def __init__(self) -> None:
        self.rollbacks = 0
        self.closes = 0

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closes += 1


def test_request_uow_is_closed_and_rolled_back_on_error(monkeypatch: pytest.MonkeyPatch):
    fake = _FakeUoW()
    monkeypatch.setattr(app_state._AppState, "create_uow", lambda _self: fake)
    application = create_app()

    @application.get("/__test_failure")
    async def fail() -> None:
        raise RuntimeError("boom")

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/__test_failure")

    assert response.status_code == 500
    assert fake.rollbacks == 1
    assert fake.closes == 1
