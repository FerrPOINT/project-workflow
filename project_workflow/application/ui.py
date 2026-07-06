"""Read-only UI data loaders implemented as an application service."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .. import config
from .state import _AppState
from ..interfaces.ui.helpers import _resolve_task_phase, _resolve_task_phase_local, _run_to_dict


class UIDataService:
    """Aggregates read-only data for UI pages and API responses."""

    def __init__(self, app_state: _AppState):
        self._app_state = app_state

    def _get_db(self) -> Any:
        return self._app_state.get_db()

    def _load_workflows(self) -> list[dict[str, Any]]:
        wdb = self._app_state.get_db()
        workflows = wdb.get_workflows()
        phases = wdb.get_all_phases()
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
            selected_agent = agents_by_id.get(p.get("agent_id")) if p.get("agent_id") else None
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
                    "delegate_agent": delegate_agent,
                    "is_delegated": bool(delegate_agent),
                    "agent_id": p.get("agent_id"),
                    "agent_name": selected_agent.get("name") if selected_agent else None,
                    "rollback_target": p.get("rollback_target"),
                    "delegate_timeout": p.get("delegate_timeout"),
                    "execution_type": p.get("execution_type", "sync"),
                    "parallel_with": p.get("parallel_with"),
                }
            )
        return result

    def _coerce_phase_db_id(self, raw_phase_id: int | str | None) -> int | None:
        if isinstance(raw_phase_id, int):
            return raw_phase_id if raw_phase_id > 0 else None
        if raw_phase_id is None:
            return None
        token = str(raw_phase_id).strip()
        if not token.isdigit():
            return None
        phase_id = int(token)
        return phase_id if phase_id > 0 else None

    def _load_phase_detail(self, phase_id: int | str) -> dict[str, Any] | None:
        resolved_phase_id = self._coerce_phase_db_id(phase_id)
        if resolved_phase_id is None:
            return None
        phase = self._app_state.get_service().get_phase_detail(resolved_phase_id)
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

        default_phase_count = len(config.PHASE_ORDER)

        # Batch load history and latest supervisor runs for all tasks in one go.
        task_ids = [t["id"] for t in tasks if isinstance(t.get("id"), int)]
        history_batch: Mapping[int, Sequence[dict[str, Any]]] = {}
        latest_runs: dict[int, dict[str, Any]] = {}
        if task_ids:
            raw_history_batch = wdb.tasks.get_history_batch(task_ids)
            if isinstance(raw_history_batch, Mapping):
                history_batch = raw_history_batch
            else:
                history_batch = {tid: wdb.get_task_history(tid) for tid in task_ids}

            raw_latest = wdb.supervisor_runs.latest_for_tasks(task_ids)
            if isinstance(raw_latest, Sequence) and not isinstance(raw_latest, (str, bytes)):
                for latest_run in raw_latest:
                    tid = getattr(latest_run, "task_id", None)
                    if tid is not None and tid not in latest_runs:
                        latest_runs[tid] = _run_to_dict(latest_run)
            else:
                for tid in task_ids:
                    runs = wdb.get_supervisor_runs(task_id=tid, limit=1)
                    if runs:
                        latest_runs[tid] = _run_to_dict(runs[0])

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
            project = projects_by_id.get(int(t["project_id"]) if isinstance(t.get("project_id"), int) else 0, {})
            project_code = project.get("code") or ""
            project_name = project.get("name") or ""
            workflow_id_raw = project.get("workflow_id")
            workflow_id: int | None = int(workflow_id_raw) if isinstance(workflow_id_raw, int) else None
            total_phases = phase_counts_by_workflow.get(workflow_id, default_phase_count) if workflow_id is not None else default_phase_count

            current_phase_id, current = _resolve_task_phase_local(
                t.get("current_phase", "-1"),
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
            latest_verdict_message = ""
            latest_verdict_at = ""
            run: dict[str, Any] | None = latest_runs.get(task_id)
            if run:
                latest_verdict = run.get("verdict")
                latest_verdict_phase = run.get("phase_code")
                response = run.get("response") or {}
                if isinstance(response, dict):
                    latest_verdict_message = response.get("message", "")
                else:
                    latest_verdict_message = str(response)[:120]
                latest_verdict_at = str(run.get("created_at", ""))[:16]

            result.append(
                {
                    "id": task_id,
                    "task_key": t["task_key"],
                    "title": t.get("title", ""),
                    "project_id": t.get("project_id"),
                    "project_code": project_code,
                    "project_name": project_name,
                    "project_label": project_name if project_name == project_code else f"{project_code} — {project_name}",
                    "phase_id": current.get("code", current_phase_id),
                    "phase_num": current.get("phase_num", current.get("phase_order", "?")),
                    "phase_name": current.get("name", current_phase_id),
                    "current_phase_name": current.get("name", current_phase_id),
                    "completed": completed,
                    "total_phases": total_phases,
                    "status": t.get("status", "active"),
                    "status_label": "В работе" if t.get("status") != "done" else "Завершена",
                    "created_at": t.get("created_at", ""),
                    "completed_at": completed_at,
                    "latest_verdict": latest_verdict,
                    "latest_verdict_phase": latest_verdict_phase,
                    "latest_verdict_message": latest_verdict_message,
                    "latest_verdict_at": latest_verdict_at,
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
            "projects": sorted(
                projects, key=lambda item: (-item.get("task_count", 0), item.get("name", ""))
            )[:8],
        }

    def _get_task_detail(self, task_key: str) -> dict[str, Any] | None:
        """Загрузить деталку задачи: метаданные + история фаз (линейно, без FORK/JOIN)."""
        from project_workflow.wizard import VERDICT_LABELS

        wdb = self._app_state.get_db()
        task = wdb.get_task_by_key(task_key)
        if not task:
            return None

        task = dict(task)
        task["project_code"] = task.get("project_code") or "—"
        task["project_name"] = task.get("project_name") or task["project_code"]
        task["project_label"] = (
            task["project_name"]
            if task["project_name"] == task["project_code"]
            else f"{task['project_code']} — {task['project_name']}"
        )

        current_phase_id, current_phase = _resolve_task_phase(
            task.get("current_phase", "-1"), wdb, workflow_id=task.get("workflow_id")
        )
        task["current_phase_name"] = current_phase["name"] if current_phase else task.get("current_phase", "")
        task["current_phase_order"] = current_phase["phase_order"] if current_phase else 0

        task["status_label"] = {"active": "В работе", "done": "Завершена", "blocked": "Заблокирована"}.get(
            task.get("status", ""), "—"
        )
        task["status_class"] = {"active": "active", "done": "done", "blocked": "blocked"}.get(
            task.get("status", ""), "wait"
        )

        workflow_id = task.get("workflow_id")
        workflow_phases = (
            wdb.get_phases(workflow_id=workflow_id) if workflow_id is not None else wdb.get_phases()
        )
        task["workflow_phase_count"] = len(workflow_phases)

        history = wdb.get_task_history(task["id"])

        task["completed_at"] = ""
        if task.get("status") == "done":
            done_entries = [h for h in history if h.get("status") == "done"]
            if done_entries:
                task["completed_at"] = max(
                    (h.get("completed_at") or "" for h in done_entries),
                    key=lambda x: x or "",
                )
            if not task["completed_at"]:
                task["completed_at"] = task.get("updated_at", "")

        phase_execution_type: dict[int, str] = {}
        phase_order_map: dict[int, int] = {}
        for p in workflow_phases:
            pid = p.get("id")
            if pid is not None:
                phase_execution_type[pid] = p.get("execution_type", "sync")
                phase_order_map[pid] = p.get("phase_order", 0)

        raw_history: list[dict[str, Any]] = []
        for h in history:
            phase = wdb.get_phase(h["phase_id"])
            if not phase:
                continue
            history_status = h.get("status", "pending")
            pid = phase["id"]
            raw_history.append(
                {
                    "phase_id": pid,
                    "phase_order": phase["phase_order"],
                    "phase_name": phase["name"],
                    "phase_code": phase.get("code", ""),
                    "phase_description": phase.get("description", ""),
                    "status": "done"
                    if history_status == "done"
                    else ("current" if current_phase and pid == current_phase["id"] else "wait"),
                    "completed_at": h.get("completed_at", ""),
                    "execution_type": phase_execution_type.get(pid, "sync"),
                }
            )

        phase_history: list[dict[str, Any]] = []
        phase_history_blocks: list[dict[str, Any]] = []
        if raw_history:
            runs: list[list[dict[str, Any]]] = []
            current_run: list[dict[str, Any]] = [raw_history[0]]
            for item in raw_history[1:]:
                if item.get("execution_type") == "parallel":
                    current_run.append(item)
                else:
                    runs.append(current_run)
                    current_run = [item]
            runs.append(current_run)

            for run in runs:
                if len(run) > 1:
                    group_key = run[0]["phase_code"]
                    for item in run:
                        item["parallel_group"] = group_key
                        item["is_parallel"] = True
                else:
                    run[0]["parallel_group"] = None
                    run[0]["is_parallel"] = False
                phase_history.extend(run)
                phase_history_blocks.append({
                    "kind": "parallel" if len(run) > 1 else "single",
                    "phases": run,
                })

        task["phase_history"] = phase_history
        task["phase_history_blocks"] = phase_history_blocks
        task["completed"] = sum(1 for h in phase_history if h.get("status") == "done")
        task["total_phases"] = task.get("workflow_phase_count", len(config.PHASE_ORDER))
        task["progress_done"] = task["completed"]
        task["progress_total"] = task["total_phases"]
        task["work_time"] = None

        supervisor_runs: list[dict[str, Any]] = wdb.get_supervisor_runs(task_key=task_key, limit=200)
        for super_run in supervisor_runs:
            super_run["verdict_label"] = VERDICT_LABELS.get(super_run.get("verdict", ""), super_run.get("verdict", "").upper())
            resp = super_run.get("response") or {}
            super_run["contract"] = {
                "description": resp.get("description", ""),
                "instructions": resp.get("instructions", []),
                "required_checks": resp.get("required_checks", []),
                "required_evidence": resp.get("required_evidence", []),
                "covered": resp.get("covered", []),
                "missing": resp.get("missing", []),
                "blockers": resp.get("blockers", []),
                "message": resp.get("message", ""),
                "next_phase_name": resp.get("next_phase_name", ""),
            }
            next_code = resp.get("next_phase")
            if next_code:
                next_ph = wdb.get_phase_by_code(next_code)
                if next_ph:
                    super_run["next_contract"] = {
                        "phase_name": next_ph.get("name", next_code),
                        "description": next_ph.get("description", ""),
                        "instructions": [i.get("text", "") for i in (next_ph.get("instructions") or [])],
                        "required_checks": [c.get("text", "") for c in (next_ph.get("checks") or [])],
                        "required_evidence": [e.get("text", "") for e in (next_ph.get("evidence") or [])],
                        "delegate_agent": next_ph.get("delegate_agent"),
                        "delegate_toolsets": next_ph.get("delegate_toolsets", []),
                    }
                else:
                    super_run["next_contract"] = None
            else:
                super_run["next_contract"] = None
        task["supervisor_runs"] = supervisor_runs

        if supervisor_runs:
            task["latest_verdict"] = supervisor_runs[0].get("verdict")
            task["latest_verdict_label"] = supervisor_runs[0].get("verdict_label")
        else:
            task["latest_verdict"] = None
            task["latest_verdict_label"] = None

        return task
