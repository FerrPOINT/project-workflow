"""Data-loading services for UI pages and API responses."""

from __future__ import annotations

from typing import Any, cast

import click

from .. import config, db
from ..cli.core import cli as project_workflow
from .dependencies import _AppState
import project_workflow.ui as _ui_module
from .templates import env as _templates_env


def _get_app_state() -> _AppState:
    """Return the current UI application state (supports test monkeypatching)."""
    return cast(_AppState, _ui_module._app_state)


def _parse_optional_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _group_instructions(instructions: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Группирует инструкции по runs: parallel примыкает к предыдущей sync и идёт с ней рядом."""
    if not instructions:
        return []
    groups: list[list[dict[str, Any]]] = []
    current = [instructions[0]]
    for instruction in instructions[1:]:
        if instruction.get("execution_type") == "parallel":
            current.append(instruction)
        else:
            groups.append(current)
            current = [instruction]
    groups.append(current)
    return groups


_templates_env.filters["group_instructions"] = _group_instructions


def _workflow_form_payload(body: dict[str, Any]) -> dict[str, Any]:
    """Normalize workflow creation/update payload."""
    name = str(body.get("name", "")).strip()
    description = str(body.get("description", "")).strip()
    return {
        "name": name,
        "description": description,
    }


def _phase_create_payload(body: dict[str, Any]) -> dict[str, Any]:
    """Normalize phase creation payload with safe defaults."""
    name = str(body.get("name", "")).strip()
    if not name:
        name = "Новая фаза"
    description = str(body.get("description", "")).strip()
    execution_type = str(body.get("execution_type", "sync")).strip()
    if execution_type not in {"sync", "parallel"}:
        execution_type = "sync"
    return {
        "name": name,
        "description": description,
        "execution_type": execution_type,
        "workflow_id": body.get("workflow_id"),
        "phase_order": body.get("phase_order"),
        "code": str(body.get("code", "")).strip() or None,
        "agent_id": body.get("agent_id"),
    }


def _load_workflows() -> list[dict[str, Any]]:
    wdb = _get_app_state().get_db()
    workflows = wdb.get_workflows()
    phases = wdb.get_phases()
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


def _load_phases(workflow_id: int | None = None) -> list[dict[str, Any]]:
    wdb = _get_app_state().get_db()
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


def _coerce_phase_db_id(raw_phase_id: int | str | None) -> int | None:
    if isinstance(raw_phase_id, int):
        return raw_phase_id if raw_phase_id > 0 else None
    if raw_phase_id is None:
        return None
    token = str(raw_phase_id).strip()
    if not token.isdigit():
        return None
    phase_id = int(token)
    return phase_id if phase_id > 0 else None


def _load_phase_detail(phase_id: int | str) -> dict[str, Any] | None:
    resolved_phase_id = _coerce_phase_db_id(phase_id)
    if resolved_phase_id is None:
        return None
    phase = _get_app_state().get_service().get_phase_detail(resolved_phase_id)
    if not phase:
        return None
    phase = dict(phase)
    phase["phase_num"] = phase.get("phase_num", phase.get("phase_order"))
    return phase


def _resolve_task_phase(
    current_phase: Any, wdb: db.WorkflowDB, workflow_id: int | None = None
) -> tuple[str, dict[str, Any] | None]:
    token = str(current_phase if current_phase is not None else "-1")
    if workflow_id is not None:
        workflow_phases = wdb.get_phases(workflow_id=workflow_id)
        for phase in workflow_phases:
            if str(phase.get("code", phase.get("id"))) == token:
                return token, phase
        for phase in workflow_phases:
            if str(phase.get("id")) == token:
                return token, phase
    found_phase = wdb.get_phase(token)
    if found_phase:
        return token, dict(found_phase)
    redirected = config.LEGACY_PHASE_REDIRECTS.get(token)
    if redirected:
        if workflow_id is not None:
            for phase in wdb.get_phases(workflow_id=workflow_id):
                if str(phase.get("code", phase.get("id"))) == redirected:
                    return redirected, dict(phase)
        redirected_phase = wdb.get_phase(redirected)
        if redirected_phase:
            return redirected, dict(redirected_phase)
    try:
        numeric = int(token)
    except (TypeError, ValueError):
        return token, None
    numeric_phase = wdb.get_phase(numeric)
    return token, dict(numeric_phase) if numeric_phase else None


def _load_tasks() -> list[dict[str, Any]]:
    """Загрузить задачи из SQLite."""
    wdb = _get_app_state().get_db()
    tasks = wdb.get_tasks()
    workflows = wdb.get_workflows()
    phase_counts_by_workflow = {
        workflow["id"]: len(wdb.get_phases(workflow_id=workflow["id"]))
        for workflow in workflows
    }
    default_phase_count = len(config.PHASE_ORDER)
    result = []

    for t in tasks:
        task_history = wdb.get_task_history(t["id"])
        completed = sum(1 for tp in task_history if tp["status"] == "done")
        workflow_id = t.get("workflow_id")
        total_phases = phase_counts_by_workflow.get(workflow_id, default_phase_count)

        current_phase_id, current = _resolve_task_phase(
            t.get("current_phase", "-1"), wdb, workflow_id=workflow_id
        )
        current = current or {}
        project_code = t.get("project_code") or "—"
        project_name = t.get("project_name") or project_code

        completed_at = ""
        if t.get("status") == "done":
            done_entries = [tp for tp in task_history if tp["status"] == "done"]
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
        supervisor_runs = wdb.get_supervisor_runs(task_id=t["id"], limit=1)
        if supervisor_runs:
            run = supervisor_runs[0]
            latest_verdict = run.get("verdict")
            latest_verdict_phase = run.get("phase_code")
            response = run.get("response") or {}
            if isinstance(response, dict):
                latest_verdict_message = response.get("message", "")
            else:
                latest_verdict_message = str(response)[:120]
            latest_verdict_at = run.get("created_at", "")[:16]

        result.append(
            {
                "id": t["id"],
                "task_key": t["task_key"],
                "title": t.get("title", ""),
                "project_id": t.get("project_id"),
                "project_code": project_code,
                "project_name": project_name,
                "project_label": project_name if project_name == project_code else f"{project_code} — {project_name}",
                "phase_id": current.get("code", current_phase_id),
                "phase_num": current.get("phase_num", "?"),
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


def _load_projects() -> list[dict[str, Any]]:
    """Список проектов для UI."""
    wdb = _get_app_state().get_db()
    projects = wdb.get_projects()
    tasks = wdb.get_tasks()
    task_counts: dict[int, int] = {}
    for task in tasks:
        pid = task.get("project_id")
        if isinstance(pid, int):
            task_counts[pid] = task_counts.get(pid, 0) + 1

    result = []
    for project in projects:
        patterns = project.get("key_patterns") or []
        result.append(
            {
                **project,
                "task_count": task_counts.get(project["id"], 0),
                "patterns_count": len(patterns),
            }
        )
    return result


def _parse_key_patterns(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [line.strip() for line in raw.splitlines() if line.strip()]
    return []


def _build_parallel_phase_blocks(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Группирует фазы по execution_type-run: parallel примыкает к текущему sync-run."""
    if not phases:
        return []

    runs: list[list[dict[str, Any]]] = []
    current_run: list[dict[str, Any]] = [phases[0]]

    for phase in phases[1:]:
        if phase.get("execution_type") == "parallel":
            current_run.append(phase)
        else:
            runs.append(current_run)
            current_run = [phase]
    runs.append(current_run)

    blocks: list[dict[str, Any]] = []
    for run in runs:
        if len(run) > 1:
            group_key = run[0]["code"]
            for phase in run:
                phase["parallel_group"] = group_key
            blocks.append({"kind": "parallel", "phases": run})
        else:
            run[0]["parallel_group"] = None
            blocks.append({"kind": "single", "phases": run})

    return blocks


def _load_dashboard() -> dict[str, Any]:
    tasks = _load_tasks()
    projects = _load_projects()

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


def _get_task_detail(task_key: str) -> dict[str, Any] | None:
    """Загрузить деталку задачи: метаданные + история фаз (линейно, без FORK/JOIN)."""
    from ..wizard import VERDICT_LABELS

    wdb = _get_app_state().get_db()
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


def _load_cli_reference() -> list[dict[str, Any]]:
    """Авто-обнаружение пользовательских CLI-команд для справки UI."""
    commands: list[dict[str, Any]] = []
    for name, command in project_workflow.commands.items():
        if name == "ui" or getattr(command, "hidden", False):
            continue

        help_text = (command.help or command.short_help or "").strip()
        summary = help_text.splitlines()[0].strip() if help_text else ""
        options = []
        for param in command.params:
            if not isinstance(param, click.Option):
                continue
            flags = [flag for flag in [*param.opts, *param.secondary_opts] if flag]
            if not flags:
                continue

            option_payload = {
                "flags": ", ".join(flags),
                "help": (param.help or "").strip(),
                "required": bool(param.required),
            }
            default_value = param.default
            unset_default = getattr(click.core, "UNSET", None)
            has_meaningful_default = (
                default_value is not unset_default
                and default_value is not None
                and default_value != ""
                and not (isinstance(default_value, bool) and default_value is False)
                and not param.required
            )
            if has_meaningful_default:
                option_payload["default"] = default_value

            options.append(option_payload)

        commands.append(
            {
                "name": name,
                "summary": summary,
                "usage": f"project-workflow {name}",
                "help": help_text,
                "options": options,
            }
        )

    return commands
