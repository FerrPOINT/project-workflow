"""Tests for repository row-to-domain converters edge cases."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from project_workflow.infrastructure.db.repositories.converters import (
    _row_to_project,
    _row_to_step_history,
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
        current_phase_id=4,
        status="active",
        created_at=None,
        updated_at=None,
        workflow=None,
    )
    with pytest.raises(ValueError, match="не найден связанный воркфлоу"):
        _row_to_task(row)


def test_row_to_task_unknown_phase_fails_closed():
    row = _row(
        id=1,
        project_id=2,
        workflow_id=3,
        task_key="T-1",
        title="t",
        description="d",
        current_phase_id=99,
        status="active",
        created_at=None,
        updated_at=None,
        workflow=SimpleNamespace(
            phases=[SimpleNamespace(id=4, code="1.INTAKE", name="Входящий запрос")]
        ),
    )
    with pytest.raises(ValueError, match="не найдена текущая фаза"):
        _row_to_task(row)


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


def test_row_to_step_history_bad_json_fields():
    row = _row(
        id=1,
        task_id=2,
        phase_id=3,
        verdict="pass",
        worker_report="r",
        covered_item_ids="not list",
        missing_item_ids="{}",
        blocker_messages="[",
        next_phase_id=None,
        rollback_phase_id=None,
        evaluation_snapshot="not object",
        supervisor_response="42",
        replay_fingerprint=None,
        created_at=None,
    )
    with pytest.raises(ValueError):
        _row_to_step_history(row)


def test_row_to_step_history_non_collection_json():
    row = _row(
        id=1,
        task_id=2,
        phase_id=3,
        verdict="pass",
        worker_report="r",
        covered_item_ids='"string"',
        missing_item_ids="42",
        blocker_messages="{}",
        next_phase_id=None,
        rollback_phase_id=None,
        evaluation_snapshot="[]",
        supervisor_response="null",
        replay_fingerprint=None,
        created_at=None,
    )
    with pytest.raises(ValueError):
        _row_to_step_history(row)


@pytest.mark.parametrize("raw", [None, ""])
def test_row_to_step_history_empty_fields(raw):
    row = _row(
        id=1,
        task_id=2,
        phase_id=3,
        verdict="pass",
        worker_report="r",
        covered_item_ids=raw,
        missing_item_ids=raw,
        blocker_messages=raw,
        next_phase_id=None,
        rollback_phase_id=None,
        evaluation_snapshot=raw,
        supervisor_response=raw,
        replay_fingerprint=None,
        created_at=None,
    )
    with pytest.raises(ValueError):
        _row_to_step_history(row)
