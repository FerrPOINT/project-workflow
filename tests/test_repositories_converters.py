"""Tests for repository row-to-domain converters edge cases."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from project_workflow.infrastructure.db.repositories.converters import (
    _row_to_project,
    _row_to_supervisor_run,
    _row_to_task,
)
from project_workflow.infrastructure.db.repositories.project import SAProjectRepository


def _row(**kwargs):
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


def test_row_to_project_bad_json_key_prefixes():
    row = _row(
        id=1,
        workflow_id=2,
        code="c",
        name="n",
        key_prefixes="not json",
        workflow=None,
    )
    with pytest.raises(ValueError, match="некорректный JSON"):
        _row_to_project(row)


def test_row_to_project_non_string_key_prefixes():
    row = _row(
        id=1,
        workflow_id=2,
        code="c",
        name="n",
        key_prefixes=[1, 2, 3],
        workflow=None,
    )
    with pytest.raises(ValueError, match="JSON-массивом строк"):
        _row_to_project(row)


def test_row_to_task_missing_workflow_fails_closed():
    row = _row(
        id=1,
        project_id=2,
        workflow_id=3,
        task_key="T-1",
        title="t",
        description="d",
        current_phase="1.INTAKE",
        status="active",
        created_at=None,
        updated_at=None,
        workflow=None,
    )
    with pytest.raises(ValueError, match="не найден связанный воркфлоу"):
        _row_to_task(row)


def test_row_to_task_unknown_phase_preserves_code_for_fail_closed_diagnostic():
    row = _row(
        id=1,
        project_id=2,
        workflow_id=3,
        task_key="T-1",
        title="t",
        description="d",
        current_phase="missing",
        status="active",
        created_at=None,
        updated_at=None,
        workflow=SimpleNamespace(phases=[SimpleNamespace(code="1.INTAKE", name="Входящий запрос")]),
    )
    task = _row_to_task(row)
    assert task.current_phase_name == "missing"


@pytest.mark.parametrize("prefixes", [None, [], "RUN", ["RUN", 1]])
def test_project_repository_rejects_non_string_prefix_collections(prefixes):
    repository = SAProjectRepository(MagicMock())
    with pytest.raises(TypeError, match="непустым массивом строк"):
        repository.create(
            {
                "workflow_id": 1,
                "code": "RUN",
                "name": "RUN",
                "key_prefixes": prefixes,
            }
        )


def test_row_to_supervisor_run_bad_json_fields():
    row = _row(
        id=1,
        task_id=2,
        phase_id=3,
        verdict="pass",
        report="r",
        covered="not list",
        missing="{}",
        blockers="[",
        next_phase_id=None,
        rollback_phase_id=None,
        context_snapshot="not object",
        response="42",
        created_at=None,
    )
    with pytest.raises(ValueError):
        _row_to_supervisor_run(row)


def test_row_to_supervisor_run_non_collection_json():
    row = _row(
        id=1,
        task_id=2,
        phase_id=3,
        verdict="pass",
        report="r",
        covered='"string"',
        missing="42",
        blockers="{}",
        next_phase_id=None,
        rollback_phase_id=None,
        context_snapshot="[]",
        response="null",
        created_at=None,
    )
    with pytest.raises(ValueError):
        _row_to_supervisor_run(row)


@pytest.mark.parametrize("raw", [None, ""])
def test_row_to_supervisor_run_empty_fields(raw):
    row = _row(
        id=1,
        task_id=2,
        phase_id=3,
        verdict="pass",
        report="r",
        covered=raw,
        missing=raw,
        blockers=raw,
        next_phase_id=None,
        rollback_phase_id=None,
        context_snapshot=raw,
        response=raw,
        created_at=None,
    )
    with pytest.raises(ValueError):
        _row_to_supervisor_run(row)
