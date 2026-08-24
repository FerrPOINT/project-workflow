"""Read-only UI data loaders implemented as an application service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..infrastructure.db.row_utils import row_to_dict
from ..interfaces.ui.helpers import (
    _build_parallel_phase_blocks,
    _resolve_task_phase,
    _resolve_task_phase_local,
    _run_to_dict,
)
from .state import _AppState


def _task_progress_counts(
    *, status: str, completed: int, history_total: int, workflow_total: int
) -> tuple[int, int]:
    """Keep completed tasks tied to their history while unfinished tasks follow the live workflow."""
    total = history_total if status == "done" else workflow_total
    return completed, total


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

    def _load_phases(self, workflow_id: int | None = None) -> list[dict[str, Any]]:
        wdb = self._app_state.get_db()
        rows = wdb.get_phases(workflow_id=workflow_id)
        agents_by_id = {agent["id"]: agent for agent in wdb.get_agents()}
        result = []
        for p in rows:
            delegate_agent = p.get("delegate_agent")
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
                    "is_delegated": bool(delegate_agent),
                    "agent_id": p.get("agent_id"),
                    "agent_name": assigned_agent.get("name") if assigned_agent else None,
                    "execution_type": p.get("execution_type", "sync"),
                    "parallel_with": p.get("parallel_with"),
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
            history_batch = wdb.tasks.get_history_batch(task_ids)
            latest_runs_raw = wdb.supervisor_runs.latest_for_tasks(task_ids)
            for latest_run in latest_runs_raw:
                tid = getattr(latest_run, "task_id", None)
                if tid is not None and tid not in latest_runs:
                    latest_runs[tid] = _run_to_dict(latest_run)

        # Batch project lookup.
        projects_by_id: dict[int, dict[str, Any]] = {}
        for project in wdb.get_projects():
            pid = project.get("id")
            if isinstance(pid, int):
                projects_by_id[pid] = project

        result = []
        for t in tasks:
            task_id = t["id"]
            task_history = list(history_batch.get(task_id, []))
            completed = sum(1 for tp in task_history if tp.get("status") == "done")
            project = projects_by_id.get(t.get("project_id"), {})
            project_code = project.get("code") or ""
            project_name = project.get("name") or ""
            workflow_id_raw = project.get("workflow_id")
            workflow_id: int | None = int(workflow_id_raw) if isinstance(workflow_id_raw, int) else None
            workflow_phase_count = (
                phase_counts_by_workflow.get(workflow_id, 0)
                if workflow_id is not None
                else 0
            )
            completed, total_phases = _task_progress_counts(
                status=str(t.get("status", "active")),
                completed=completed,
                history_total=len(task_history),
                workflow_total=workflow_phase_count,
            )

            current_phase_id, current = _resolve_task_phase_local(
                t.get("current_phase", ""),
                phases_by_workflow.get(workflow_id, []),
            )
            current = current or {}

            completed_at = ""
            if t.get("status") == "done":
                done_entries = [tp for tp in task_history if tp.get("status") == "done"]
                if done_entries:
                    completed_at = max(
                        (tp.get("completed_at") or "" for tp in done_entries),
                        key=lambda x: x or "",
                    )
                if not completed_at:
                    completed_at = t.get("updated_at", "")

            latest_verdict = None
            latest_verdict_phase = None
            run: dict[str, Any] | None = latest_runs.get(task_id)
            if run:
                latest_verdict = run.get("verdict")
                snapshot = run.get("context_snapshot") or {}
                response = run.get("response") or {}
                latest_verdict_phase = (
                    snapshot.get("phase") or response.get("current_phase") or run.get("phase_code")
                )

            result.append(
                {
                    "id": task_id,
                    "task_key": t["task_key"],
                    "title": t.get("title", ""),
                    "project_id": t.get("project_id"),
                    "workflow_id": workflow_id,
                    "project_code": project_code,
                    "project_name": project_name,
                    "current_phase_name": current.get("name", current_phase_id),
                    "completed": completed,
                    "total_phases": total_phases,
                    "status": t.get("status", "active"),
                    "status_label": "В работе" if t.get("status") != "done" else "Завершена",
                    "created_at": t.get("created_at", ""),
                    "completed_at": completed_at,
                    "latest_verdict": latest_verdict,
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
            },
            "active_tasks": active_tasks[:8],
            "projects": sorted(projects, key=lambda item: (-item.get("task_count", 0), item.get("name", "")))[:8],
        }

    def _resolve_task_workflow_id(
        self, task: dict[str, Any], wdb: Any
    ) -> tuple[int | None, list[dict[str, Any]]]:
        workflow_id = task.get("workflow_id")
        if workflow_id is None:
            project = task.get("project")
            if isinstance(project, dict):
                workflow_id = project.get("workflow_id")
            elif task.get("project_id") is not None:
                proj_row = wdb.projects.get_by_id(int(task["project_id"]))
                if proj_row is not None:
                    workflow_id = getattr(proj_row, "workflow_id", None) or row_to_dict(proj_row).get("workflow_id")
        if workflow_id is not None:
            phases = wdb.get_phases(workflow_id=workflow_id)
        else:
            phases = wdb.get_phases()
        return workflow_id, phases

    def _compute_completion_time(self, task: dict[str, Any], history: list[dict[str, Any]]) -> str:
        if task.get("status") != "done":
            return ""
        done_entries = [h for h in history if h.get("status") == "done"]
        if done_entries:
            completed_at = max(
                (h.get("completed_at") or "" for h in done_entries),
                key=lambda x: x or "",
            )
            if completed_at:
                return completed_at
        return task.get("updated_at", "")

    def _build_phase_history_blocks(
        self,
        history: list[dict[str, Any]],
        workflow_phases: list[dict[str, Any]],
        current_phase: dict[str, Any] | None,
        wdb: Any,
    ) -> list[dict[str, Any]]:
        phase_by_id: dict[int, dict[str, Any]] = {}
        for p in workflow_phases:
            pid = p.get("id")
            if pid is not None:
                phase_by_id[pid] = p

        raw_history: list[dict[str, Any]] = []
        for h in history:
            phase = phase_by_id.get(h["phase_id"])
            if not phase:
                continue
            history_status = h.get("status", "pending")
            pid = phase["id"]
            raw_history.append(
                {
                    "phase_id": pid,
                    "phase_order": phase["phase_order"],
                    "phase_name": phase["name"],
                    "code": phase.get("code", ""),
                    "phase_code": phase.get("code", ""),
                    "phase_description": phase.get("description", ""),
                    "status": "done"
                    if history_status == "done"
                    else ("current" if current_phase and pid == current_phase["id"] else "wait"),
                    "completed_at": h.get("completed_at", ""),
                    "execution_type": phase.get("execution_type", "sync"),
                    "parallel_with": phase.get("parallel_with"),
                }
            )

        raw_history.sort(key=lambda item: (int(item.get("phase_order", 0)), int(item.get("phase_id", 0))))
        for sequence_number, phase in enumerate(raw_history, start=1):
            phase["sequence_number"] = sequence_number
        return _build_parallel_phase_blocks(raw_history)

    def _decorate_supervisor_runs(self, supervisor_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from project_workflow.supervisor.types import VERDICT_LABELS

        for super_run in supervisor_runs:
            super_run["verdict_label"] = VERDICT_LABELS.get(
                super_run.get("verdict", ""), super_run.get("verdict", "").upper()
            )
            resp = super_run.get("response") or {}
            snapshot = super_run.get("context_snapshot") or {}
            contract_snapshot = snapshot.get("contract_snapshot") or {}
            super_run["phase_code"] = snapshot.get("phase") or resp.get("current_phase") or "—"
            super_run["phase_name"] = (
                snapshot.get("phase_name")
                or contract_snapshot.get("phase_name")
                or super_run["phase_code"]
            )
            super_run["contract"] = {
                "covered": resp.get("covered", super_run.get("covered", [])),
                "missing": resp.get("missing", super_run.get("missing", [])),
                "blockers": resp.get("blockers", super_run.get("blockers", [])),
                "message": resp.get("message", ""),
            }
            next_contract = resp.get("next_phase_contract")
            super_run["next_contract"] = dict(next_contract) if isinstance(next_contract, dict) else None
        return supervisor_runs

    def _get_task_detail(self, task_key: str) -> dict[str, Any] | None:
        """Загрузить деталку задачи: метаданные + история фаз (линейно, без FORK/JOIN)."""
        wdb = self._app_state.get_db()
        task = wdb.get_task_by_key(task_key)
        if not task:
            return None

        task = dict(task)
        project_id = task.get("project_id")
        project = row_to_dict(wdb.projects.get_by_id(project_id)) if isinstance(project_id, int) else None
        if project:
            task["workflow_id"] = project.get("workflow_id")
            task["project_code"] = project.get("code")
            task["project_name"] = project.get("name")
        task["project_code"] = task.get("project_code") or "—"
        task["project_name"] = task.get("project_name") or task["project_code"]
        task["project_label"] = (
            task["project_name"]
            if task["project_name"] == task["project_code"]
            else f"{task['project_code']} — {task['project_name']}"
        )

        current_phase_id, current_phase = _resolve_task_phase(
            task.get("current_phase", ""), wdb, workflow_id=task.get("workflow_id")
        )
        task["current_phase_name"] = current_phase["name"] if current_phase else task.get("current_phase", "")
        task["current_phase_order"] = current_phase["phase_order"] if current_phase else 0

        workflow_id, workflow_phases = self._resolve_task_workflow_id(task, wdb)
        task["workflow_phase_count"] = len(workflow_phases)
        task["workflow_cycle_count"] = len(_build_parallel_phase_blocks(workflow_phases))
        task["total_phases"] = len(workflow_phases)

        history = wdb.get_task_history(task["id"])
        task["completed_at"] = self._compute_completion_time(task, history)

        task["phase_history_blocks"] = self._build_phase_history_blocks(
            history, workflow_phases, current_phase, wdb
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
            status=str(task.get("status", "active")),
            completed=task["completed"],
            history_total=len(displayed_history),
            workflow_total=task["workflow_phase_count"],
        )
        task["total_phases"] = task["progress_total"]

        supervisor_runs = self._decorate_supervisor_runs(
            list(reversed(wdb.get_supervisor_runs(task_key=task_key, limit=200)))
        )
        task["supervisor_runs"] = supervisor_runs

        if supervisor_runs:
            task["latest_verdict"] = supervisor_runs[-1].get("verdict")
            task["latest_verdict_label"] = supervisor_runs[-1].get("verdict_label")
        else:
            task["latest_verdict"] = None
            task["latest_verdict_label"] = None

        return task
