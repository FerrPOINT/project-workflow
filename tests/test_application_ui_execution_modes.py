"""Regression coverage for mode- and cycle-scoped task UI state."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.ui]


class _AppState:
    def __init__(self, wdb: MagicMock):
        self._wdb = wdb

    def get_db(self) -> MagicMock:
        return self._wdb


def _service(wdb: MagicMock):
    from project_workflow.application.ui import UIDataService

    return UIDataService(_AppState(wdb))


def _phase(phase_id: int, mode_id: int, code: str, order: int) -> dict[str, object]:
    return {
        "id": phase_id,
        "workflow_id": 1,
        "mode_id": mode_id,
        "mode_key": {10: "default", 20: "initial", 30: "rework"}[mode_id],
        "phase_order": order,
        "code": code,
        "name": code.title(),
        "description": "",
        "execution_type": "sync",
        "parallel_with_phase_id": None,
    }


def _task(
    task_id: int,
    *,
    mode_id: int,
    mode_key: str,
    cycle_number: int,
    phase_id: int,
) -> dict[str, object]:
    return {
        "id": task_id,
        "task_key": f"RUN-{task_id}",
        "title": f"Task {task_id}",
        "project_id": 1,
        "workflow_id": 1,
        "mode_id": mode_id,
        "mode_key": mode_key,
        "cycle_number": cycle_number,
        "status": "active",
        "current_phase_id": phase_id,
        "current_phase_code": f"phase-{phase_id}",
        "current_phase_name": f"Phase {phase_id}",
    }


def _event(
    phase_id: int,
    *,
    mode_id: int,
    mode_key: str,
    cycle_number: int,
    event_type: str,
) -> dict[str, object]:
    return {
        "id": phase_id * 10 + cycle_number,
        "phase_id": phase_id,
        "mode_id": mode_id,
        "mode_key": mode_key,
        "cycle_number": cycle_number,
        "event_type": event_type,
        "occurred_at": f"2026-09-{phase_id:02d}",
    }


def _step(
    phase_id: int,
    *,
    mode_id: int,
    mode_key: str,
    cycle_number: int,
    verdict: str,
) -> dict[str, object]:
    return {
        "phase_id": phase_id,
        "mode_id": mode_id,
        "mode_key": mode_key,
        "cycle_number": cycle_number,
        "verdict": verdict,
        "evaluation_snapshot": {
            "phase_code": f"phase-{phase_id}",
            "phase_name": f"Phase {phase_id}",
        },
        "supervisor_response": {},
    }


def _list_db(
    tasks: list[dict[str, object]],
    catalogs: dict[int, list[dict[str, object]]],
    events: dict[int, list[dict[str, object]]] | None = None,
) -> MagicMock:
    wdb = MagicMock()
    wdb.get_tasks.return_value = tasks
    wdb.get_workflows.return_value = [{"id": 1, "name": "Developer"}]
    wdb.get_projects.return_value = [{"id": 1, "name": "Runtime", "workflow_id": 1}]
    wdb.workflows.get_mode.side_effect = lambda mode_id, workflow_id: (
        object() if workflow_id == 1 and mode_id in catalogs else None
    )
    wdb.get_phases.side_effect = lambda workflow_id, mode_id=None: catalogs.get(mode_id, []) if workflow_id == 1 else []
    wdb.list_phase_events_batch.return_value = events or {int(task["id"]): [] for task in tasks}
    wdb.step_history.latest_for_tasks.return_value = []
    return wdb


@pytest.mark.parametrize(
    ("mode_id", "mode_key", "phase_id"),
    [(10, "default", 101), (20, "initial", 201)],
)
def test_task_list_uses_exact_default_or_initial_catalog(mode_id: int, mode_key: str, phase_id: int) -> None:
    task = _task(1, mode_id=mode_id, mode_key=mode_key, cycle_number=0, phase_id=phase_id)
    wdb = _list_db([task], {mode_id: [_phase(phase_id, mode_id, mode_key, 1)]})

    result = _service(wdb)._load_tasks()

    assert result[0]["mode_id"] == mode_id
    assert result[0]["cycle_number"] == 0
    assert result[0]["total_phases"] == 1
    wdb.get_phases.assert_called_once_with(workflow_id=1, mode_id=mode_id)


def test_task_detail_keeps_initial_history_but_graphs_current_rework() -> None:
    initial = [_phase(201, 20, "develop", 1), _phase(202, 20, "verify", 2)]
    rework = [_phase(301, 30, "fix", 1), _phase(302, 30, "recheck", 2)]
    task = _task(1, mode_id=30, mode_key="rework", cycle_number=1, phase_id=302)
    history = [
        _event(201, mode_id=20, mode_key="initial", cycle_number=0, event_type="completed"),
        _event(202, mode_id=20, mode_key="initial", cycle_number=0, event_type="completed"),
        _event(301, mode_id=30, mode_key="rework", cycle_number=1, event_type="completed"),
        _event(302, mode_id=30, mode_key="rework", cycle_number=1, event_type="entered"),
    ]
    steps = [
        _step(
            302,
            mode_id=30,
            mode_key="rework",
            cycle_number=1,
            verdict="partial",
        ),
        _step(
            202,
            mode_id=20,
            mode_key="initial",
            cycle_number=0,
            verdict="pass",
        ),
    ]
    wdb = _detail_db(task, {20: initial, 30: rework}, history, step_history=steps)

    result = _service(wdb)._get_task_detail("RUN-1")

    assert result is not None
    assert [group["mode_id"] for group in result["phase_event_groups"]] == [20, 30]
    assert result["phase_events"] == history
    assert result["current_phase_events"] == history[2:]
    displayed = [phase for block in result["phase_history_blocks"] for phase in block["phases"]]
    assert [phase["phase_id"] for phase in displayed] == [301, 302]
    assert result["progress_done"] == 1
    assert result["progress_total"] == 2
    assert [group["mode_id"] for group in result["step_history_groups"]] == [20, 30]
    assert [step["mode_id"] for step in result["current_step_history"]] == [30]
    assert result["latest_verdict"] == "partial"


def test_rework_cycle_two_does_not_reuse_cycle_one_progress() -> None:
    rework = [_phase(301, 30, "fix", 1), _phase(302, 30, "recheck", 2)]
    task = _task(1, mode_id=30, mode_key="rework", cycle_number=2, phase_id=301)
    events = {
        1: [
            _event(301, mode_id=30, mode_key="rework", cycle_number=1, event_type="completed"),
            _event(302, mode_id=30, mode_key="rework", cycle_number=1, event_type="completed"),
            _event(301, mode_id=30, mode_key="rework", cycle_number=2, event_type="entered"),
        ]
    }
    wdb = _list_db([task], {30: rework}, events)

    result = _service(wdb)._load_tasks()

    assert result[0]["completed"] == 0
    assert result[0]["total_phases"] == 2


def test_mixed_task_list_caches_each_workflow_mode_catalog() -> None:
    catalogs = {
        10: [_phase(101, 10, "default", 1)],
        20: [_phase(201, 20, "develop", 1), _phase(202, 20, "verify", 2)],
        30: [_phase(301, 30, "fix", 1)],
    }
    tasks = [
        _task(1, mode_id=10, mode_key="default", cycle_number=0, phase_id=101),
        _task(2, mode_id=20, mode_key="initial", cycle_number=0, phase_id=201),
        _task(3, mode_id=30, mode_key="rework", cycle_number=1, phase_id=301),
        _task(4, mode_id=30, mode_key="rework", cycle_number=2, phase_id=301),
    ]
    wdb = _list_db(tasks, catalogs)

    result = _service(wdb)._load_tasks()

    assert [(item["mode_id"], item["total_phases"]) for item in result] == [
        (10, 1),
        (20, 2),
        (30, 1),
        (30, 1),
    ]
    assert wdb.get_phases.call_count == 3


def test_unknown_task_mode_fails_without_default_catalog_fallback() -> None:
    task = _task(1, mode_id=99, mode_key="missing", cycle_number=0, phase_id=101)
    wdb = _list_db([task], {})

    with pytest.raises(ValueError, match="не найден режим 99"):
        _service(wdb)._load_tasks()

    wdb.get_phases.assert_not_called()


def test_current_phase_from_another_mode_fails_closed() -> None:
    task = _task(1, mode_id=30, mode_key="rework", cycle_number=1, phase_id=201)
    wdb = _list_db([task], {30: [_phase(301, 30, "fix", 1)]})

    with pytest.raises(ValueError, match="Текущая фаза 201 отсутствует"):
        _service(wdb)._load_tasks()


def _detail_db(
    task: dict[str, object],
    catalogs: dict[int, list[dict[str, object]]],
    history: list[dict[str, object]],
    *,
    step_history: list[dict[str, object]] | None = None,
) -> MagicMock:
    wdb = _list_db([task], catalogs, {int(task["id"]): history})
    wdb.get_task_by_key.return_value = task
    project = MagicMock()
    project.to_dict.return_value = {"id": 1, "name": "Runtime", "workflow_id": 1}
    wdb.projects.get_by_id.return_value = project
    workflow = MagicMock()
    workflow.to_dict.return_value = {"id": 1, "name": "Developer"}
    wdb.workflows.get_by_id.return_value = workflow
    wdb.list_phase_events.return_value = history
    wdb.list_step_history.return_value = step_history or []
    return wdb
