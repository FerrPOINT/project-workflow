"""Compatibility adapter: legacy WorkflowDB interface backed by SQLAlchemy.

This module provides ``WorkflowDBCompat`` — a duck-typed shim that exposes
exactly the subset of ``project_workflow.db.WorkflowDB`` that the UI and CLI
call sites need.  It delegates reads/writes to the existing SQLAlchemy-backed
application services and repositories, removing the UI's runtime dependency on
legacy sqlite3 WorkflowDB while keeping route/service/template code unchanged.

No new functionality is added; return shapes are kept compatible with legacy
WorkflowDB so downstream consumers continue to work without modification.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)


class _FakeCursor:
    """No-op cursor-like object for legacy ``with db._conn() as conn`` blocks.

    The adapter's writes are already committed by application services / UoW,
    so the compat shim does not need a real transaction cursor.  Some callers
    (e.g. ``api_workflow_delete``) still call ``conn.execute``/``conn.commit``
    after issuing a few legacy statements; this fake cursor ignores them safely.
    """

    def execute(self, *args, **kwargs) -> "_FakeCursor":
        return self

    def executemany(self, *args, **kwargs) -> "_FakeCursor":
        return self

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeConnection:
    """No-op connection returned by ``WorkflowDBCompat._conn()``.

    Implements the tiny surface area used by UI callers that still reach into
the raw connection object.
    """

    def __init__(self) -> None:
        self._cursor = _FakeCursor()

    def execute(self, *args, **kwargs) -> _FakeCursor:
        return self._cursor

    def executemany(self, *args, **kwargs) -> _FakeCursor:
        return self._cursor

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *args) -> None:
        pass


class WorkflowDBCompat:
    """Legacy-compatible DB handle that sits on top of SQLAlchemy/UoW services.

    The constructor accepts no arguments (matching the legacy ``WorkflowDB()``
signature) and lazily resolves the shared UI ``_app_state`` on first use to
avoid circular imports at import time.
    """

    def __init__(self) -> None:
        self._state: Any | None = None

    def _app_state(self) -> Any:
        if self._state is None:
            from project_workflow.ui.state import _app_state

            self._state = _app_state
        return self._state

    @property
    def _sa_engine(self):
        """Expose the SQLAlchemy engine so PhaseService uses the SA code path."""
        return self._app_state().get_uow()._session.bind

    @contextmanager
    def _conn(self) -> Generator[_FakeConnection, None, None]:
        """Context manager returning a no-op connection-like object."""
        conn = _FakeConnection()
        try:
            yield conn
        finally:
            conn.close()

    def db_path(self) -> str:
        """Return the SQLite file path the underlying SQLAlchemy engine uses."""
        url = self._app_state()._database_url
        if url.startswith("sqlite:///"):
            return url[10:]
        return url

    def _ensure_default_workflows(self, _conn: Any) -> None:
        """Ensure default workflow exists; delegates to WorkflowService."""
        self._app_state().workflow_service().ensure_default_exists()

    def init(self) -> None:
        """Legacy no-op; schema is created/migrated by the SQLAlchemy session."""
        pass

    def close(self) -> None:
        pass

    # ── Workflows ───────────────────────────────────────────────────────

    def get_workflows(self) -> list[dict[str, Any]]:
        return self._app_state().workflow_service().list_workflows()

    def get_workflow(self, workflow_id: int | str) -> dict[str, Any] | None:
        # Some callers pass a string code; legacy resolves by name for strings.
        if isinstance(workflow_id, str):
            if workflow_id.isdigit():
                workflow_id = int(workflow_id)
            else:
                return self._app_state().workflow_service().get_workflow_by_name(workflow_id)
        return self._app_state().workflow_service().get_workflow(workflow_id)

    def get_default_workflow(self) -> dict[str, Any] | None:
        with self._app_state().get_uow() as uow:
            wf = uow.workflows.get_default()
            return wf.to_dict() if wf else None

    def get_workflow_by_name(self, name: str) -> dict[str, Any] | None:
        with self._app_state().get_uow() as uow:
            wf = uow.workflows.get_by_name(name)
            return wf.to_dict() if wf else None

    def create_workflow(self, data: dict[str, Any]) -> int:
        return self._app_state().workflow_service().create_workflow(data)["id"]

    def update_workflow(self, workflow_id: int, data: dict[str, Any]) -> None:
        self._app_state().workflow_service().update_workflow(workflow_id, data)

    def delete_workflow(self, workflow_id: int) -> None:
        self._app_state().workflow_service().delete_workflow(workflow_id)

    # ── Phases ──────────────────────────────────────────────────────────

    def get_phases(self, workflow_id: int | str | None = None) -> list[dict[str, Any]]:
        service = self._app_state().phase_service()
        phases = service.list_phases(
            workflow_id=int(workflow_id) if isinstance(workflow_id, str) and workflow_id.isdigit() else workflow_id
        )
        # Enrich with the joined workflow metadata that legacy callers expect.
        workflows: dict[int, Any] = {}
        with self._app_state().get_uow() as uow:
            workflows = {w.id: w for w in uow.workflows.list()}
        for p in phases:
            wf = workflows.get(p.get("workflow_id"))
            p["workflow_name"] = wf.name if wf else None
            p["workflow_description"] = wf.description if wf else None
            p["workflow_is_default"] = wf.is_default if wf else False
            # Ensure integer 0/1 for is_seed_managed (legacy used 0/1).
            p["is_seed_managed"] = 1 if p.get("is_seed_managed") else 0
        return phases

    def get_phase(self, phase_id: int | str) -> dict[str, Any] | None:
        if isinstance(phase_id, str):
            if phase_id.isdigit():
                phase_id = int(phase_id)
            else:
                with self._app_state().get_uow() as uow:
                    p = uow.phases.get_by_code(phase_id)
                    return self._enrich_phase(p.to_dict() if p else None)
        p = self._app_state().phase_service().get_phase(phase_id)
        return self._enrich_phase(p)

    def get_phase_by_code(self, code: str) -> dict[str, Any] | None:
        with self._app_state().get_uow() as uow:
            p = uow.phases.get_by_code(code)
            return self._enrich_phase(p.to_dict() if p else None)

    def _enrich_phase(self, p: dict[str, Any] | None) -> dict[str, Any] | None:
        if p is None:
            return None
        with self._app_state().get_uow() as uow:
            wf = uow.workflows.get_by_id(p.get("workflow_id")) if p.get("workflow_id") else None
        if wf:
            p["workflow_name"] = wf.name
            p["workflow_description"] = wf.description
            p["workflow_is_default"] = wf.is_default
        p["is_seed_managed"] = 1 if p.get("is_seed_managed") else 0
        return p

    def create_phase(self, data: dict[str, Any]) -> int:
        return self._app_state().phase_service().create_phase(data)["id"]

    def update_phase(self, phase_id: int | str, data: dict[str, Any]) -> None:
        resolved = self._resolve_phase_id(phase_id)
        self._app_state().phase_service().update_phase(resolved, data)

    def delete_phase(self, phase_id: int | str) -> None:
        resolved = self._resolve_phase_id(phase_id)
        self._app_state().phase_service().delete_phase(resolved)

    def batch_update_orders(self, orders: list[tuple[int | str, int]]) -> None:
        with self._app_state().get_uow() as uow:
            for pid, order in orders:
                resolved = self._resolve_phase_id(pid)
                uow.phases.update(resolved, {"phase_order": order})
            uow.commit()

    def _resolve_phase_id(self, val: int | str) -> int:
        if isinstance(val, int):
            return val
        with self._app_state().get_uow() as uow:
            p = uow.phases.get_by_code(val)
            if p:
                return int(p.id)
        raise ValueError(f"Unknown phase code: {val}")

    # ── Phase content ───────────────────────────────────────────────────

    def get_phase_instructions(self, phase_id: int | str) -> list[dict[str, Any]]:
        resolved = self._resolve_phase_id(phase_id)
        from sqlalchemy import select
        from project_workflow.infrastructure.db import models as m

        with self._app_state().get_uow() as uow:
            rows = uow._session.execute(
                select(
                    m.Instruction.id,
                    m.Instruction.phase_id,
                    m.Instruction.step_num,
                    m.Instruction.description,
                    m.Instruction.execution_type,
                    m.Instruction.skills,
                )
                .where(m.Instruction.phase_id == resolved)
                .order_by(m.Instruction.step_num)
            ).mappings().all()
            return [dict(r) for r in rows]

    def get_phase_checks(self, phase_id: int | str) -> list[dict[str, Any]]:
        resolved = self._resolve_phase_id(phase_id)
        from sqlalchemy import select
        from project_workflow.infrastructure.db import models as m

        with self._app_state().get_uow() as uow:
            rows = uow._session.execute(
                select(m.Check.id, m.Check.phase_id, m.Check.description)
                .where(m.Check.phase_id == resolved)
            ).mappings().all()
            return [dict(r) for r in rows]

    def get_phase_evidence(self, phase_id: int | str) -> list[dict[str, Any]]:
        resolved = self._resolve_phase_id(phase_id)
        from sqlalchemy import select
        from project_workflow.infrastructure.db import models as m

        with self._app_state().get_uow() as uow:
            rows = uow._session.execute(
                select(m.Evidence.id, m.Evidence.phase_id, m.Evidence.description)
                .where(m.Evidence.phase_id == resolved)
            ).mappings().all()
            return [dict(r) for r in rows]

    # ── Projects ────────────────────────────────────────────────────────

    def get_projects(self) -> list[dict[str, Any]]:
        with self._app_state().get_uow() as uow:
            rows = uow.projects.list()
            return [r.to_dict() for r in rows]

    def get_project(self, project_id: int) -> dict[str, Any] | None:
        return self._app_state().project_service().get_project(project_id)

    def get_project_by_code(self, code: str) -> dict[str, Any] | None:
        with self._app_state().get_uow() as uow:
            p = uow.projects.get_by_code(code)
            return p.to_dict() if p else None

    def create_project(self, data: dict[str, Any]) -> int:
        return self._app_state().project_service().create_project(data)["id"]

    def update_project(self, project_id: int, data: dict[str, Any]) -> None:
        self._app_state().project_service().update_project(project_id, data)

    def delete_project(self, project_id: int) -> None:
        self._app_state().project_service().delete_project(project_id)

    def match_project_for_task_key(self, task_key: str, *, strict: bool = True) -> dict[str, Any] | None:
        with self._app_state().get_uow() as uow:
            p = uow.projects.match_by_task_key(task_key)
            if p:
                return p.to_dict()
            if not strict:
                rows = uow.projects.list()
                return rows[0].to_dict() if rows else None
            return None

    # ── Tasks ───────────────────────────────────────────────────────────

    def create_task(self, data: dict[str, Any]) -> int:
        payload = dict(data)
        if "project_id" not in payload:
            project = self.match_project_for_task_key(payload.get("task_key", ""))
            if not project:
                raise ValueError(f"No project regex matched task key: {payload.get('task_key')}")
            payload["project_id"] = project["id"]
        return self._app_state().task_service().create_task(payload)["id"]

    def get_tasks(self) -> list[dict[str, Any]]:
        from sqlalchemy import select
        from project_workflow.infrastructure.db import models as m

        with self._app_state().get_uow() as uow:
            rows = uow._session.execute(
                select(
                    m.Task.id,
                    m.Task.project_id,
                    m.Task.task_key,
                    m.Task.title,
                    m.Task.description,
                    m.Task.current_phase,
                    m.Task.status,
                    m.Task.created_at,
                    m.Task.updated_at,
                    m.Project.code.label("project_code"),
                    m.Project.name.label("project_name"),
                    m.Project.workflow_id,
                    m.Workflow.name.label("workflow_name"),
                )
                .join(m.Project, m.Project.id == m.Task.project_id)
                .join(m.Workflow, m.Workflow.id == m.Project.workflow_id, isouter=True)
                .order_by(m.Task.updated_at.desc())
            ).mappings().all()
            return [dict(r) for r in rows]

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        from sqlalchemy import select
        from project_workflow.infrastructure.db import models as m

        with self._app_state().get_uow() as uow:
            row = uow._session.execute(
                select(
                    m.Task.id,
                    m.Task.project_id,
                    m.Task.task_key,
                    m.Task.title,
                    m.Task.description,
                    m.Task.current_phase,
                    m.Task.status,
                    m.Task.created_at,
                    m.Task.updated_at,
                    m.Project.code.label("project_code"),
                    m.Project.name.label("project_name"),
                    m.Project.workflow_id,
                    m.Workflow.name.label("workflow_name"),
                )
                .join(m.Project, m.Project.id == m.Task.project_id)
                .join(m.Workflow, m.Workflow.id == m.Project.workflow_id, isouter=True)
                .where(m.Task.id == task_id)
            ).mappings().one_or_none()
            return dict(row) if row else None

    def get_task_by_key(self, task_key: str) -> dict[str, Any] | None:
        from sqlalchemy import select
        from project_workflow.infrastructure.db import models as m

        with self._app_state().get_uow() as uow:
            row = uow._session.execute(
                select(
                    m.Task.id,
                    m.Task.project_id,
                    m.Task.task_key,
                    m.Task.title,
                    m.Task.description,
                    m.Task.current_phase,
                    m.Task.status,
                    m.Task.created_at,
                    m.Task.updated_at,
                    m.Project.code.label("project_code"),
                    m.Project.name.label("project_name"),
                    m.Project.workflow_id,
                    m.Workflow.name.label("workflow_name"),
                )
                .join(m.Project, m.Project.id == m.Task.project_id)
                .join(m.Workflow, m.Workflow.id == m.Project.workflow_id, isouter=True)
                .where(m.Task.task_key == task_key)
            ).mappings().one_or_none()
            return dict(row) if row else None

    def update_task(self, task_id: int, data: dict[str, Any]) -> None:
        payload = dict(data)
        # Normalize legacy "project"/"project_code" keys into project_id.
        if "project" in payload:
            payload["project_id"] = self._resolve_project_id(payload.pop("project"))
        if "project_code" in payload:
            payload["project_id"] = self._resolve_project_id(payload.pop("project_code"))
        from project_workflow.infrastructure.db import models as m

        with self._app_state().get_uow() as uow:
            row = uow._session.get(m.Task, task_id)
            if row is None:
                from project_workflow.domain.exceptions import NotFoundError
                raise NotFoundError(f"Task {task_id} not found")
            for key, val in payload.items():
                if hasattr(row, key):
                    setattr(row, key, val)
            uow.commit()

    def _resolve_project_id(self, val: int | str) -> int:
        if isinstance(val, int):
            return val
        p = self.get_project_by_code(val)
        if p:
            return int(p["id"])
        raise ValueError(f"Unknown project code: {val}")

    def delete_task(self, task_id: int) -> None:
        with self._app_state().get_uow() as uow:
            uow.tasks.delete(task_id)
            uow.commit()

    # ── Task history ────────────────────────────────────────────────────

    def add_task_history(self, task_id: int, phase_id: int | str, status: str = "pending") -> None:
        resolved = self._resolve_phase_id(phase_id)
        self._app_state().task_service().add_history(task_id, resolved, status)

    def get_task_history(self, task_id: int) -> list[dict[str, Any]]:
        return list(self._app_state().task_service()._uow.tasks.get_history(task_id))

    def add_task_phase(self, task_id: int, phase_id: int | str, status: str = "pending") -> None:
        return self.add_task_history(task_id, phase_id, status)

    def get_task_phases(self, task_id: int) -> list[dict[str, Any]]:
        return self.get_task_history(task_id)

    # ── Supervisor runs ─────────────────────────────────────────────────

    def get_supervisor_runs(
        self,
        *,
        task_id: int | None = None,
        task_key: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        # The SASupervisorRunRepository currently only supports task_id.
        resolved_task_id = task_id
        with self._app_state().get_uow() as uow:
            if resolved_task_id is None:
                if task_key is None:
                    raise ValueError("task_id or task_key is required")
                t = uow.tasks.get_by_key(task_key)
                if t is None:
                    return []
                resolved_task_id = int(t.id)
            rows = uow.supervisor_runs.list(task_id=resolved_task_id, limit=limit)
            result: list[dict[str, Any]] = []
            for r in rows:
                d = r.to_dict()
                # Add the joined-code columns the UI expects.
                phase = uow.phases.get_by_id(r.phase_id)
                next_phase = uow.phases.get_by_id(r.next_phase_id) if r.next_phase_id else None
                rollback_phase = uow.phases.get_by_id(r.rollback_phase_id) if r.rollback_phase_id else None
                task = uow.tasks.get_by_id(r.task_id)
                d["phase_code"] = phase.code if phase else None
                d["next_phase_code"] = next_phase.code if next_phase else None
                d["rollback_phase_code"] = rollback_phase.code if rollback_phase else None
                d["task_key"] = task.task_key if task else None
                result.append(d)
            return result

    def create_supervisor_run(self, data: dict[str, Any]) -> int:
        payload = dict(data)
        with self._app_state().get_uow() as uow:
            if payload.get("task_id") is None and payload.get("task_key") is not None:
                t = uow.tasks.get_by_key(payload["task_key"])
                if t is None:
                    raise ValueError(f"Unknown task key: {payload['task_key']}")
                payload["task_id"] = int(t.id)
            if payload.get("phase_id") is not None:
                payload["phase_id"] = self._resolve_phase_id(payload["phase_id"])
            if payload.get("next_phase_id") is not None:
                payload["next_phase_id"] = self._resolve_phase_id(payload["next_phase_id"])
            if payload.get("rollback_phase_id") is not None:
                payload["rollback_phase_id"] = self._resolve_phase_id(payload["rollback_phase_id"])
            rid = uow.supervisor_runs.create(payload)
            uow.commit()
            return rid

    # ── Agents ──────────────────────────────────────────────────────────

    def get_agents(self) -> list[dict[str, Any]]:
        return self._app_state().agent_service().list_agents()

    def get_agent(self, agent_id: int) -> dict[str, Any] | None:
        return self._app_state().agent_service().get_agent(agent_id)

    def create_agent(self, data: dict[str, Any]) -> int:
        return self._app_state().agent_service().create_agent(data)["id"]

    def update_agent(self, agent_id: int, data: dict[str, Any]) -> None:
        self._app_state().agent_service().update_agent(agent_id, data)

    def delete_agent(self, agent_id: int) -> None:
        self._app_state().agent_service().delete_agent(agent_id)

    # ── Catalog sync / seed helpers (UI still calls via schema.py) ───────

    def sync_phase_catalog(
        self,
        phases: list[dict[str, Any]],
        phase_order: list[str],
        phase_redirects: dict[str, str] | None = None,
        workflow_id: int | str | None = None,
    ) -> None:
        """Synchronise the Postgres phase catalog with seed.json.

        Mirrors the legacy WorkflowDB logic: upsert phases, migrate legacy
        redirects, replace instructions/checks/evidence, and remove stale
        seed-managed phases that are no longer in the seed.
        """
        from sqlalchemy import delete, select, update
        from project_workflow.infrastructure.db import models as m

        phase_redirects = phase_redirects or {}

        seed_by_code: dict[str, dict] = {}
        for fallback_order, phase in enumerate(phases, start=1):
            code = str(phase.get("code", phase.get("id", ""))).strip()
            if not code:
                continue
            normalized = dict(phase)
            normalized["code"] = code
            normalized["phase_order"] = (
                phase_order.index(code) + 1 if code in phase_order else fallback_order
            )
            seed_by_code[code] = normalized

        desired_codes = set(seed_by_code)
        removed_codes = [code for code in phase_redirects if code not in desired_codes]

        with self._app_state().get_uow() as uow:
            session = uow._session
            self._app_state().workflow_service().ensure_default_exists()

            if workflow_id is not None:
                catalog_wf_id = int(workflow_id)
            else:
                default_wf = session.execute(
                    select(m.Workflow).where(m.Workflow.is_default == 1)
                ).scalar_one_or_none()
                catalog_wf_id = default_wf.id if default_wf else None
            if catalog_wf_id is None:
                raise RuntimeError("No default workflow available for phase catalog")

            # Resolve (or create) agents named in seed items.
            def _resolve_agent(seed_item: dict) -> int | None:
                selected = seed_item.get("selected_agent")
                if selected:
                    agent = session.execute(
                        select(m.Agent).where(m.Agent.name == selected)
                    ).scalar_one_or_none()
                    if agent is None:
                        agent = m.Agent(name=selected, description="")
                        session.add(agent)
                        session.flush()
                    return agent.id
                return seed_item.get("agent_id")

            existing_by_code: dict[str, m.Phase] = {
                row.code: row
                for row in session.execute(
                    select(m.Phase).where(m.Phase.workflow_id == catalog_wf_id)
                ).scalars()
            }

            for code in phase_order:
                seed = seed_by_code.get(code)
                if not seed:
                    continue
                existing = existing_by_code.get(code)
                agent_id = _resolve_agent(seed)
                values = {
                    "workflow_id": catalog_wf_id,
                    "name": seed["name"],
                    "description": seed.get("description") or "",
                    "min_time_min": seed.get("min_time_min", 0),
                    "phase_order": seed["phase_order"],
                    "agent_id": agent_id,
                    "next_recommendation": seed.get("next_recommendation"),
                    "parallel_with": seed.get("parallel_with"),
                    "rollback_target": seed.get("rollback_target"),
                    "execution_type": seed.get("execution_type", "sync"),
                    "is_seed_managed": 1,
                }
                if existing:
                    session.execute(
                        update(m.Phase).where(m.Phase.id == existing.id).values(**values)
                    )
                    phase_id = existing.id
                else:
                    new_phase = m.Phase(code=code, **values)
                    session.add(new_phase)
                    session.flush()
                    phase_id = new_phase.id
                    existing_by_code[code] = new_phase

                # Replace phase content (instructions/checks/evidence).
                session.execute(delete(m.Instruction).where(m.Instruction.phase_id == phase_id))
                session.execute(delete(m.Check).where(m.Check.phase_id == phase_id))
                session.execute(delete(m.Evidence).where(m.Evidence.phase_id == phase_id))

                for fallback_step, inst in enumerate(seed.get("instructions", []), start=1):
                    raw_skills = inst.get("skills")
                    skills_payload = (
                        json.dumps(raw_skills, ensure_ascii=False)
                        if isinstance(raw_skills, list)
                        else raw_skills
                    )
                    session.add(
                        m.Instruction(
                            phase_id=phase_id,
                            step_num=inst.get("step_num", fallback_step),
                            description=inst["description"],
                            execution_type=inst.get("execution_type", "sync"),
                            skills=skills_payload,
                        )
                    )

                for check in seed.get("checks", []):
                    session.add(
                        m.Check(phase_id=phase_id, description=check["description"])
                    )

                for evidence in seed.get("evidence", []):
                    session.add(
                        m.Evidence(
                            phase_id=phase_id,
                            description=evidence.get("description", evidence.get("item", "")),
                        )
                    )

            # Migrate task_history rows for redirected legacy codes.
            for legacy_code, target_code in phase_redirects.items():
                legacy_phase = existing_by_code.get(legacy_code)
                target_phase = existing_by_code.get(target_code)
                if not legacy_phase or not target_phase:
                    continue
                legacy_hist = session.execute(
                    select(m.TaskHistory).where(m.TaskHistory.phase_id == legacy_phase.id)
                ).scalars().all()
                for hist in legacy_hist:
                    target_hist = session.execute(
                        select(m.TaskHistory).where(
                            m.TaskHistory.task_id == hist.task_id,
                            m.TaskHistory.phase_id == target_phase.id,
                        )
                    ).scalar_one_or_none()
                    if target_hist:
                        merged_status = (
                            "done"
                            if hist.status == "done" or target_hist.status == "done"
                            else target_hist.status
                        )
                        target_hist.status = merged_status
                        target_hist.completed_at = target_hist.completed_at or hist.completed_at
                        session.delete(hist)
                    else:
                        hist.phase_id = target_phase.id

            if removed_codes:
                session.execute(
                    update(m.Phase)
                    .where(m.Phase.parallel_with.in_(removed_codes))
                    .values(parallel_with=None)
                )

            # Delete stale seed-managed phases that are no longer present.
            for code, phase in list(existing_by_code.items()):
                if code in desired_codes:
                    continue
                if not phase.is_seed_managed:
                    continue
                session.execute(
                    delete(m.Phase).where(m.Phase.id == phase.id)
                )

            uow.commit()

    def is_empty(self) -> bool:
        from sqlalchemy import func, select
        from project_workflow.infrastructure.db import models as m

        with self._app_state().get_uow() as uow:
            count = uow._session.execute(select(func.count()).select_from(m.Phase)).scalar()
            return count == 0

    # ── CLI history (unused by UI, kept for duck typing) ─────────────────

    def log_cli_call(self, command: str, task_key: str | None, request: str | None, response: str | None) -> None:
        from project_workflow.infrastructure.db import models as m

        with self._app_state().get_uow() as uow:
            uow._session.add(
                m.CliHistory(
                    command=command,
                    task_key=task_key,
                    request=request,
                    response=response,
                )
            )
            uow.commit()

    def get_cli_history(self, limit: int = 100) -> list[dict[str, Any]]:
        from sqlalchemy import select
        from project_workflow.infrastructure.db import models as m

        with self._app_state().get_uow() as uow:
            rows = uow._session.execute(
                select(
                    m.CliHistory.id,
                    m.CliHistory.command,
                    m.CliHistory.task_key,
                    m.CliHistory.request,
                    m.CliHistory.response,
                    m.CliHistory.created_at,
                )
                .order_by(m.CliHistory.created_at.asc(), m.CliHistory.id.asc())
                .limit(limit)
            ).mappings().all()
            return [dict(r) for r in rows]
