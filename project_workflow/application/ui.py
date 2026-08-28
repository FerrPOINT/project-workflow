"""Read-only UI data loaders implemented as an application service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from project_workflow.domain.workflow_theme import DEFAULT_WORKFLOW_COLOR, DEFAULT_WORKFLOW_ICON

from ..interfaces.ui.helpers import (
    _build_parallel_phase_blocks,
    _resolve_task_phase_id,
)
from .state import _AppState

_UI_VERDICT_LABELS = {
    "pass": "Принято",
    "partial": "Частично принято",
    "blocked": "Заблокировано",
    "rollback": "Откат",
    "delegate": "Делегировано",
}


def _ui_verdict_label(verdict: Any) -> str:
    value = str(verdict or "")
    return _UI_VERDICT_LABELS.get(value.lower(), value.upper())


def _task_progress_counts(*, completed: int, workflow_total: int) -> tuple[int, int]:
    return completed, workflow_total


class UIDataService:
    """Aggregates read-only data for UI pages and API responses."""

    def __init__(self, app_state: _AppState):
        self._app_state = app_state

    def _load_workflows(self) -> list[dict[str, Any]]:
        wdb = self._app_state.get_db()
        workflows = wdb.get_workflows()
        phases = [phase.to_dict() for phase in wdb.phases.list()]
        projects = wdb.get_projects()
        phase_counts: dict[int, int] = {}
        project_counts: dict[int, int] = {}
        for phase in phases:
            wid = phase.get("workflow_id")
            if isinstance(wid, int):
                phase_counts[wid] = phase_counts.get(wid, 0) + 1
        for project in projects:
            wid = project.get("workflow_id")
            if isinstance(wid, int):
                project_counts[wid] = project_counts.get(wid, 0) + 1

        result = []
        for workflow in workflows:
            result.append(
                {
                    **workflow,
                    "phase_count": phase_counts.get(workflow["id"], 0),
                    "project_count": project_counts.get(workflow["id"], 0),
                }
            )
        return result

    def _load_phases(self, workflow_id: int) -> list[dict[str, Any]]:
        wdb = self._app_state.get_db()
        rows = wdb.get_phases(workflow_id=workflow_id)
        agents_by_id = {agent["id"]: agent for agent in wdb.get_agents()}
        result = []
        for p in rows:
            assigned_agent = agents_by_id.get(p.get("agent_id")) if p.get("agent_id") else None
            result.append(
                {
                    "id": p["id"],
                    "code": p["code"],
                    "workflow_id": p.get("workflow_id"),
                    "workflow_name": p.get("workflow_name"),
                    "workflow_is_default": bool(p.get("workflow_is_default")),
                    "phase_num": p["phase_order"],
                    "name": p["name"],
                    "description": p["description"],
                    "agent_id": p.get("agent_id"),
                    "agent_name": assigned_agent.get("name") if assigned_agent else None,
                    "execution_type": p.get("execution_type", "sync"),
                    "parallel_with_phase_id": p.get("parallel_with_phase_id"),
                    "rollback_target_phase_id": p.get("rollback_target_phase_id"),
                }
            )
        return result

    def _load_phase_detail(self, phase_id: int) -> dict[str, Any] | None:
        if phase_id <= 0:
            return None
        phase = self._app_state.get_service().get_phase_detail(phase_id)
        if not phase:
            return None
        phase = dict(phase)
        phase["phase_num"] = phase.get("phase_num", phase.get("phase_order"))
        return phase

    def _load_tasks(self) -> list[dict[str, Any]]:
        """Load tasks for the UI with batched history/supervisor lookups."""
        wdb = self._app_state.get_db()
        tasks = wdb.get_tasks()
        workflows = wdb.get_workflows()
        workflows_by_id = {
            workflow["id"]: workflow
            for workflow in workflows
            if isinstance(workflow.get("id"), int)
        }

        # Batch phase counts and phase lookup maps per workflow.
        phase_counts_by_workflow: dict[int, int] = {}
        phases_by_workflow: dict[int | None, list[dict[str, Any]]] = {}
        all_phases: list[dict[str, Any]] = []
        for workflow in workflows:
            wid = workflow["id"]
            phases = wdb.get_phases(workflow_id=wid)
            phases_by_workflow[wid] = phases
            all_phases.extend(phases)
            phase_counts_by_workflow[wid] = len(phases)
        phases_by_workflow[None] = all_phases

        # Batch load history and latest supervisor runs for all tasks in one go.
        task_ids = [t["id"] for t in tasks if isinstance(t.get("id"), int)]
        history_batch: Mapping[int, Sequence[dict[str, Any]]] = {}
        latest_runs: dict[int, dict[str, Any]] = {}
        if task_ids:
            history_batch = wdb.list_phase_events_batch(task_ids)
            latest_runs_raw = wdb.step_history.latest_for_tasks(task_ids)
            for latest_run in latest_runs_raw:
                tid = latest_run.task_id
                if tid not in latest_runs:
                    latest_runs[tid] = latest_run.to_dict()

        # Batch project lookup.
        projects_by_id: dict[int, dict[str, Any]] = {}
        for project in wdb.get_projects():
            pid = project.get("id")
            if isinstance(pid, int):
                projects_by_id[pid] = project

        result = []
        for t in tasks:
            task_id = t["id"]
            phase_events = list(history_batch.get(task_id, []))
            latest_event_by_phase = {event["phase_id"]: event for event in phase_events}
            completed = sum(
                1 for event in latest_event_by_phase.values() if event.get("event_type") == "completed"
            )
            project_id = t.get("project_id")
            if not isinstance(project_id, int) or isinstance(project_id, bool) or project_id <= 0:
                raise ValueError(f"У задачи {t['task_key']} отсутствует корректный project_id")
            task_project = projects_by_id.get(project_id)
            if task_project is None:
                raise ValueError(f"Для задачи {t['task_key']} не найден проект {project_id}")
            project_code = str(task_project["code"])
            project_name = str(task_project["name"])
            workflow_id_raw = t.get("workflow_id")
            workflow_id: int | None = int(workflow_id_raw) if isinstance(workflow_id_raw, int) else None
            task_workflow = workflows_by_id.get(workflow_id) if workflow_id is not None else None
            workflow_phase_count = (
                phase_counts_by_workflow.get(workflow_id, 0)
                if workflow_id is not None
                else 0
            )
            completed, total_phases = _task_progress_counts(
                completed=completed,
                workflow_total=workflow_phase_count,
            )

            _resolve_task_phase_id(
                t["current_phase_id"], phases_by_workflow.get(workflow_id, [])
            )

            completed_at = ""
            if t.get("status") == "done":
                done_entries = [
                    event for event in phase_events if event.get("event_type") == "completed"
                ]
                if not done_entries:
                    raise ValueError(f"Для завершённой задачи {t['task_key']} нет события completed")
                completed_at = max(str(event["occurred_at"]) for event in done_entries)

            latest_verdict = None
            latest_verdict_phase = None
            run: dict[str, Any] | None = latest_runs.get(task_id)
            if run:
                latest_verdict = run.get("verdict")
                snapshot = run.get("evaluation_snapshot") or {}
                response = run.get("supervisor_response") or {}
                latest_verdict_phase = (
                    snapshot.get("phase_code") or response.get("current_phase_code")
                )

            result.append(
                {
                    "id": task_id,
                    "task_key": t["task_key"],
                    "title": t.get("title", ""),
                    "project_id": t.get("project_id"),
                    "workflow_id": workflow_id,
                    "workflow_name": task_workflow.get("name") if task_workflow else None,
                    "workflow_theme_icon": (
                        task_workflow.get("theme_icon", DEFAULT_WORKFLOW_ICON)
                        if task_workflow
                        else DEFAULT_WORKFLOW_ICON
                    ),
                    "workflow_theme_color": (
                        task_workflow.get("theme_color", DEFAULT_WORKFLOW_COLOR)
                        if task_workflow
                        else DEFAULT_WORKFLOW_COLOR
                    ),
                    "project_code": project_code,
                    "project_name": project_name,
                    "current_phase_id": t["current_phase_id"],
                    "current_phase_code": t["current_phase_code"],
                    "current_phase_name": t["current_phase_name"],
                    "completed": completed,
                    "total_phases": total_phases,
                    "status": t.get("status", "active"),
                    "status_label": (
                        "Завершена"
                        if t.get("status") == "done"
                        else "Заблокирована"
                        if t.get("status") == "blocked"
                        else "В работе"
                    ),
                    "created_at": t.get("created_at", ""),
                    "completed_at": completed_at,
                    "latest_verdict": latest_verdict,
                    "latest_verdict_label": _ui_verdict_label(latest_verdict),
                    "latest_verdict_phase": latest_verdict_phase,
                }
            )

        return result

    def _load_projects(self) -> list[dict[str, Any]]:
        """Список проектов для UI."""
        wdb = self._app_state.get_db()
        projects = wdb.get_projects()
        tasks = wdb.get_tasks()
        task_counts: dict[int, int] = {}
        for task in tasks:
            pid = task.get("project_id")
            if isinstance(pid, int):
                task_counts[pid] = task_counts.get(pid, 0) + 1

        result = []
        for project in projects:
            prefixes = project.get("key_prefixes") or []
            result.append(
                {
                    **project,
                    "task_count": task_counts.get(project["id"], 0),
                    "prefixes_count": len(prefixes),
                }
            )
        return result

    def _load_dashboard(self) -> dict[str, Any]:
        tasks = self._load_tasks()
        projects = self._load_projects()

        open_tasks = [task for task in tasks if task.get("status") != "done"]
        active_tasks = [task for task in tasks if task.get("status") == "active"]
        done_tasks = [task for task in tasks if task.get("status") == "done"]

        verdict_counts: dict[str, int] = {}
        for task in tasks:
            v = task.get("latest_verdict")
            if v:
                verdict_counts[v] = verdict_counts.get(v, 0) + 1

        return {
            "stats": {
                "projects": len(projects),
                "tasks": len(tasks),
                "active": len(active_tasks),
                "done": len(done_tasks),
                "verdicts": verdict_counts,
                "verdict_labels": {
                    verdict: _ui_verdict_label(verdict) for verdict in verdict_counts
                },
            },
            "open_tasks": open_tasks[:8],
            "projects": sorted(projects, key=lambda item: (-item.get("task_count", 0), item.get("name", "")))[:8],
        }

    def _resolve_task_workflow_id(
        self, task: dict[str, Any], wdb: Any
    ) -> tuple[int | None, list[dict[str, Any]]]:
        workflow_id = task.get("workflow_id")
        if not isinstance(workflow_id, int) or isinstance(workflow_id, bool) or workflow_id <= 0:
            return None, []
        return workflow_id, wdb.get_phases(workflow_id=workflow_id)

    def _compute_completion_time(self, task: dict[str, Any], history: list[dict[str, Any]]) -> str:
        if task.get("status") != "done":
            return ""
        done_entries = [h for h in history if h.get("event_type") == "completed"]
        if not done_entries:
            raise ValueError(f"Для завершённой задачи {task['task_key']} нет события completed")
        return max(str(item["occurred_at"]) for item in done_entries)

    def _build_phase_history_blocks(
        self,
        history: list[dict[str, Any]],
        workflow_phases: list[dict[str, Any]],
        current_phase: dict[str, Any],
        task_status: str,
    ) -> list[dict[str, Any]]:
        phase_by_id: dict[int, dict[str, Any]] = {}
        for p in workflow_phases:
            pid = p.get("id")
            if pid is not None:
                phase_by_id[pid] = p
        unknown_phase_ids = {
            event.get("phase_id") for event in history if event.get("phase_id") not in phase_by_id
        }
        if unknown_phase_ids:
            unknown = ", ".join(
                str(phase_id) for phase_id in sorted(unknown_phase_ids, key=str)
            )
            raise ValueError(f"Журнал событий ссылается на неизвестные фазы: {unknown}")

        latest_event_by_phase = {event["phase_id"]: event for event in history}
        current_phase_event = latest_event_by_phase.get(current_phase["id"])
        expected_current_events = {
            "active": {"entered", "resumed"},
            "blocked": {"blocked"},
            "done": {"completed"},
        }
        if current_phase_event is None or current_phase_event.get("event_type") not in expected_current_events.get(
            task_status, set()
        ):
            raise ValueError("Текущее состояние задачи не согласовано с журналом событий фаз")

        raw_history: list[dict[str, Any]] = []
        event_status = {
            "entered": "current",
            "resumed": "current",
            "completed": "done",
            "blocked": "current",
            "rolled_back": "wait",
        }
        for phase in workflow_phases:
            event = latest_event_by_phase.get(phase["id"])
            pid = phase["id"]
            raw_history.append(
                {
                    "id": pid,
                    "phase_id": pid,
                    "phase_order": phase["phase_order"],
                    "phase_name": phase["name"],
                    "code": phase.get("code", ""),
                    "phase_code": phase.get("code", ""),
                    "phase_description": phase.get("description", ""),
                    "status": event_status[event["event_type"]] if event else "wait",
                    "occurred_at": event.get("occurred_at", "") if event else "",
                    "execution_type": phase.get("execution_type", "sync"),
                    "parallel_with_phase_id": phase.get("parallel_with_phase_id"),
                }
            )

        raw_history.sort(key=lambda item: (int(item.get("phase_order", 0)), int(item.get("phase_id", 0))))
        for sequence_number, phase in enumerate(raw_history, start=1):
            phase["sequence_number"] = sequence_number
        return _build_parallel_phase_blocks(raw_history)

    def _decorate_step_history(self, step_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for step in step_history:
            step["verdict_label"] = _ui_verdict_label(step.get("verdict"))
            resp = step.get("supervisor_response") or {}
            snapshot = step.get("evaluation_snapshot") or {}
            contract_snapshot = snapshot.get("contract_snapshot") or {}
            phase_code = snapshot.get("phase_code")
            phase_name = snapshot.get("phase_name") or contract_snapshot.get("phase_name")
            if not isinstance(phase_code, str) or not phase_code or not isinstance(phase_name, str) or not phase_name:
                raise ValueError("Запись истории step не содержит снимок оценённой фазы")
            step["phase_code"] = phase_code
            step["phase_name"] = phase_name
            step["contract"] = {
                "covered": resp.get("covered", []),
                "missing": resp.get("missing", []),
                "blockers": resp.get("blockers", step.get("blocker_messages", [])),
                "message": resp.get("message", ""),
            }
            next_contract = resp.get("next_phase_contract")
            step["next_contract"] = dict(next_contract) if isinstance(next_contract, dict) else None
        return step_history

    def _get_task_detail(self, task_key: str, workflow_id: int | None = None) -> dict[str, Any] | None:
        """Загрузить деталку задачи: метаданные + история фаз (линейно, без FORK/JOIN)."""
        wdb = self._app_state.get_db()
        task = wdb.get_task_by_key(task_key, workflow_id=workflow_id)
        if not task:
            return None

        task = dict(task)
        project_id = task.get("project_id")
        if not isinstance(project_id, int) or isinstance(project_id, bool) or project_id <= 0:
            raise ValueError(f"У задачи {task_key} отсутствует корректный project_id")
        project_row = wdb.projects.get_by_id(project_id)
        if project_row is None:
            raise ValueError(f"Для задачи {task_key} не найден проект {project_id}")
        project = project_row.to_dict()
        task["project_code"] = project["code"]
        task["project_name"] = project["name"]
        task["project_label"] = (
            task["project_name"]
            if task["project_name"] == task["project_code"]
            else f"{task['project_code']} — {task['project_name']}"
        )

        workflow_id, workflow_phases = self._resolve_task_workflow_id(task, wdb)
        if workflow_id is None:
            raise ValueError("У задачи отсутствует корректный workflow_id")
        workflow_row = wdb.workflows.get_by_id(workflow_id)
        if workflow_row is None:
            raise ValueError(f"Для задачи {task_key} не найден воркфлоу {workflow_id}")
        workflow = workflow_row.to_dict()
        task["workflow"] = workflow
        task["workflow_name"] = workflow["name"]
        task["workflow_theme_icon"] = workflow.get("theme_icon", DEFAULT_WORKFLOW_ICON)
        task["workflow_theme_color"] = workflow.get("theme_color", DEFAULT_WORKFLOW_COLOR)
        current_phase = _resolve_task_phase_id(task["current_phase_id"], workflow_phases)
        task["current_phase_code"] = current_phase["code"]
        task["current_phase_name"] = current_phase["name"]
        task["current_phase_order"] = current_phase["phase_order"]
        task["workflow_phase_count"] = len(workflow_phases)
        task["workflow_cycle_count"] = len(_build_parallel_phase_blocks(workflow_phases))
        task["total_phases"] = len(workflow_phases)

        history = wdb.list_phase_events(task["id"])
        if not history:
            raise ValueError("Для задачи отсутствует обязательный журнал событий фаз")
        task["phase_events"] = history
        task["completed_at"] = self._compute_completion_time(task, history)

        task["phase_history_blocks"] = self._build_phase_history_blocks(
            history, workflow_phases, current_phase, str(task.get("status", "active"))
        )
        displayed_history = [
            phase for block in task["phase_history_blocks"] for phase in block["phases"]
        ]
        task["completed"] = sum(1 for phase in displayed_history if phase.get("status") == "done")
        task["completed_cycles"] = sum(
            1 for block in task["phase_history_blocks"] if block.get("status") == "done"
        )
        if task.get("status") == "done":
            task["completed_cycles"] = task["workflow_cycle_count"]
        task["progress_done"], task["progress_total"] = _task_progress_counts(
            completed=task["completed"],
            workflow_total=task["workflow_phase_count"],
        )
        task["total_phases"] = task["progress_total"]

        step_history = self._decorate_step_history(
            list(reversed(wdb.list_step_history(task_id=task["id"], workflow_id=workflow_id, limit=200)))
        )
        task["step_history"] = step_history

        if step_history:
            task["latest_verdict"] = step_history[-1].get("verdict")
            task["latest_verdict_label"] = step_history[-1].get("verdict_label")
        else:
            task["latest_verdict"] = None
            task["latest_verdict_label"] = None

        return task
