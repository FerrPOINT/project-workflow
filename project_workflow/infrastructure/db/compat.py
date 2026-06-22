"""Compatibility adapter: legacy WorkflowDB interface backed by SQLAlchemy.

This module provides ``WorkflowDBCompat`` — a duck-typed shim that exposes
exactly the subset of ``project_workflow.infrastructure.db.WorkflowDB`` that CLI, wizard and
seed loaders need.  It delegates reads/writes to the SQLAlchemy-backed
application services and repositories, removing the runtime dependency on the
legacy sqlite3 WorkflowDB while keeping call-site code unchanged.

No new functionality is added; return shapes are kept compatible with legacy
WorkflowDB so downstream consumers continue to work without modification.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generator

if TYPE_CHECKING:
    from ...application.state import _AppState

logger = logging.getLogger(__name__)


class _FakeCursor:
    """No-op cursor-like object for legacy ``with db._conn() as conn`` blocks."""

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

    Implements the tiny surface area used by callers that still reach into
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
    """Legacy-compatible DB handle backed by SQLAlchemy services.

    The constructor accepts an optional ``_AppState`` instance.  When omitted it
    falls back to the global ``project_workflow.application.state._app_state`` so
    legacy ``WorkflowDB()`` call sites keep working.
    """

    def __init__(
        self,
        db_path: str | None = None,
        state: "_AppState" | None = None,
    ) -> None:
        if state is not None:
            self._state = state
            return

        from ... import config
        from ...application.state import _AppState

        if db_path is not None:
            db_url = str(db_path)
            if not db_url.startswith("sqlite://"):
                db_url = f"sqlite:///{db_url}"
            self._state = _AppState(database_url=db_url)
            return

        env_url = config.get_settings().DATABASE_URL
        default_db_path = Path(getattr(config, "DB_PATH", str(Path(config.get_settings().WORKFLOW_DIR) / "workflow.db")))
        if env_url and env_url.startswith("sqlite://"):
            db_url = env_url
        else:
            db_url = f"sqlite:///{default_db_path}"
        self._state = _AppState(database_url=db_url)

    @property
    def _sa_engine(self):
        """Expose the SQLAlchemy engine so PhaseService uses the SA code path."""
        return self._state.get_uow()._session.bind

    @contextmanager
    def _conn(self) -> Generator[_FakeConnection, None, None]:
        """Context manager returning a no-op connection-like object."""
        conn = _FakeConnection()
        try:
            yield conn
        finally:
            conn.close()

    def db_path(self) -> str:
        """Return the SQLite file path if the underlying engine uses SQLite."""
        url = self._state._database_url_public
        if url.startswith("sqlite:///"):
            return url[10:]
        return url

    def _ensure_default_workflows(self, _conn: Any) -> None:
        """Ensure default workflow exists; delegates to WorkflowService."""
        from sqlalchemy import select
        from ... import config
        from . import models as m

        self._state.workflow_service().ensure_default_exists()
        with self._state.get_uow() as uow:
            session = uow._session
            smoke = session.execute(
                select(m.Workflow).where(m.Workflow.name == config.SMOKE_WORKFLOW_NAME)
            ).scalar_one_or_none()
            if smoke is None:
                session.add(
                    m.Workflow(
                        name=config.SMOKE_WORKFLOW_NAME,
                        description="Короткий боевой workflow для CLI smoke/regression тестирования.",
                        is_default=0,
                    )
                )
            uow.commit()

    def _bootstrap_projects(self) -> None:
        from sqlalchemy import select
        from ... import config
        from . import models as m

        projects = [
            {
                "workflow_name": config.DEFAULT_WORKFLOW_NAME,
                "code": "TASK",
                "name": "TASK",
                "key_prefixes": config.DEFAULT_TASK_KEY_PREFIXES,
            },
            {
                "workflow_name": config.SMOKE_WORKFLOW_NAME,
                "code": config.SMOKE_PROJECT_CODE,
                "name": config.SMOKE_PROJECT_NAME,
                "key_prefixes": config.SMOKE_TASK_KEY_PREFIXES,
            },
        ]

        with self._state.get_uow() as uow:
            session = uow._session
            existing_codes = set(
                session.execute(select(m.Project.code).select_from(m.Project)).scalars()
            )
            for p in projects:
                if p["code"] in existing_codes:
                    continue
                wf = session.execute(
                    select(m.Workflow).where(m.Workflow.name == p["workflow_name"])
                ).scalar_one_or_none()
                if wf is None:
                    continue
                key_prefixes = self._serialize_key_prefixes(p["key_prefixes"])
                session.add(
                    m.Project(
                        workflow_id=wf.id,
                        code=p["code"],
                        name=p["name"],
                        key_prefixes=key_prefixes,
                    )
                )
            uow.commit()

    @staticmethod
    def _serialize_key_prefixes(prefixes: list[str] | str | None) -> str:
        if prefixes is None:
            return "[]"
        if isinstance(prefixes, str):
            return json.dumps(
                [str(p).upper() for p in prefixes.splitlines() if str(p).strip()],
                ensure_ascii=False,
            )
        return json.dumps(
            [str(p).upper() for p in prefixes if str(p).strip()], ensure_ascii=False
        )

    @staticmethod
    def _deserialize_key_prefixes(raw: str | None) -> list[str]:
        if raw is None:
            return []
        try:
            value = json.loads(raw)
            if isinstance(value, list):
                return [str(p).upper() for p in value if str(p).strip()]
            return [str(value).upper()]
        except (json.JSONDecodeError, TypeError):
            return []

    def _bootstrap_agents(self) -> None:
        from sqlalchemy import select
        from . import models as m

        agents = [
            {
                "name": "researcher",
                "description": "Исследует кодовую базу, зависимости и dataflow; собирает контекст перед изменениями.",
            },
            {
                "name": "critic",
                "description": "Проводит gate-review планов и результатов, ищет риски и незакрытые обязательные проверки.",
            },
            {
                "name": "reviewer",
                "description": "Проверяет качество решения, тесты и безопасность; фиксирует замечания по результату review.",
            },
            {
                "name": "oracle",
                "description": "Сторонний эксперт по архитектуре, безопасности и требованиям; даёт разрешительные verdictы.",
            },
        ]
        with self._state.get_uow() as uow:
            session = uow._session
            existing = {row.name for row in session.execute(select(m.Agent)).scalars()}
            for a in agents:
                if a["name"] in existing:
                    continue
                session.add(m.Agent(name=a["name"], description=a["description"]))
            uow.commit()

    def init(self) -> None:
        """Bootstrap workflows, projects and agents (schema is already ensured)."""
        self._ensure_default_workflows(None)
        self._bootstrap_agents()
        self._bootstrap_projects()

    def close(self) -> None:
        pass

    def import_phases(self, phases: list[dict[str, Any]]) -> None:
        """Legacy import helper — now delegates to sync_phase_catalog."""
        phase_order = [
            str(p.get("code", p.get("id", ""))).strip()
            for p in phases
            if str(p.get("code", p.get("id", ""))).strip()
        ]
        self.sync_phase_catalog(phases, phase_order)

    # ── Workflows ───────────────────────────────────────────────────────

    def get_workflows(self) -> list[dict[str, Any]]:
        return self._state.workflow_service().list_workflows()

    def get_workflow(self, workflow_id: int | str) -> dict[str, Any] | None:
        # Some callers pass a string code; legacy resolves by name for strings.
        if isinstance(workflow_id, str):
            if workflow_id.isdigit():
                workflow_id = int(workflow_id)
            else:
                return self._state.workflow_service().get_workflow_by_name(workflow_id)
        return self._state.workflow_service().get_workflow(workflow_id)

    def get_default_workflow(self) -> dict[str, Any] | None:
        with self._state.get_uow() as uow:
            wf = uow.workflows.get_default()
            return wf.to_dict() if wf else None

    def get_workflow_by_name(self, name: str) -> dict[str, Any] | None:
        with self._state.get_uow() as uow:
            wf = uow.workflows.get_by_name(name)
            return wf.to_dict() if wf else None

    def create_workflow(self, data: dict[str, Any]) -> int:
        return self._state.workflow_service().create_workflow(data)["id"]

    def update_workflow(self, workflow_id: int, data: dict[str, Any]) -> None:
        self._state.workflow_service().update_workflow(workflow_id, data)

    def delete_workflow(self, workflow_id: int) -> None:
        self._state.workflow_service().delete_workflow(workflow_id)

    # ── Phases ──────────────────────────────────────────────────────────

    def get_phases(self, workflow_id: int | str | None = None) -> list[dict[str, Any]]:
        service = self._state.phase_service()
        phases = service.list_phases(
            workflow_id=int(workflow_id) if isinstance(workflow_id, str) and workflow_id.isdigit() else workflow_id
        )
        # Enrich with the joined workflow metadata that legacy callers expect.
        workflows: dict[int, Any] = {}
        with self._state.get_uow() as uow:
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
                with self._state.get_uow() as uow:
                    p = uow.phases.get_by_code(phase_id)
                    if p is None:
                        from ... import config
                        redirect = config.LEGACY_PHASE_REDIRECTS.get(phase_id)
                        if redirect:
                            p = uow.phases.get_by_code(redirect)
                    return self._enrich_phase(p.to_dict() if p else None)
        p = self._state.phase_service().get_phase(phase_id)
        return self._enrich_phase(p)

    def get_phase_by_code(self, code: str) -> dict[str, Any] | None:
        with self._state.get_uow() as uow:
            p = uow.phases.get_by_code(code)
            return self._enrich_phase(p.to_dict() if p else None)

    def _enrich_phase(self, p: dict[str, Any] | None) -> dict[str, Any] | None:
        if p is None:
            return None
        with self._state.get_uow() as uow:
            wf = uow.workflows.get_by_id(p.get("workflow_id")) if p.get("workflow_id") else None
        if wf:
            p["workflow_name"] = wf.name
            p["workflow_description"] = wf.description
            p["workflow_is_default"] = wf.is_default
        p["is_seed_managed"] = 1 if p.get("is_seed_managed") else 0
        return p

    def create_phase(self, data: dict[str, Any]) -> int:
        payload = dict(data)
        if "workflow_id" not in payload or payload["workflow_id"] is None:
            default_wf = self.get_default_workflow()
            payload["workflow_id"] = default_wf["id"] if default_wf else None
        if "code" not in payload and "id" in payload:
            payload["code"] = str(payload.pop("id"))
        return self._state.phase_service().create_phase(payload)["id"]

    def update_phase(self, phase_id: int | str, data: dict[str, Any]) -> None:
        resolved = self._resolve_phase_id(phase_id)
        self._state.phase_service().update_phase(resolved, data)

    def delete_phase(self, phase_id: int | str) -> None:
        resolved = self._resolve_phase_id(phase_id)
        self._state.phase_service().delete_phase(resolved)

    def batch_update_orders(self, orders: list[tuple[int | str, int]]) -> None:
        with self._state.get_uow() as uow:
            for pid, order in orders:
                resolved = self._resolve_phase_id(pid)
                uow.phases.update(resolved, {"phase_order": order})
            uow.commit()

    def _resolve_phase_id(self, val: int | str) -> int:
        if isinstance(val, int):
            return val
        with self._state.get_uow() as uow:
            p = uow.phases.get_by_code(val)
            if p:
                return int(p.id)
        raise ValueError(f"Unknown phase code: {val}")

    # ── Phase content ───────────────────────────────────────────────────

    def get_phase_instructions(self, phase_id: int | str) -> list[dict[str, Any]]:
        try:
            resolved = self._resolve_phase_id(phase_id)
        except ValueError:
            return []
        from sqlalchemy import select
        from . import models as m

        with self._state.get_uow() as uow:
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
        try:
            resolved = self._resolve_phase_id(phase_id)
        except ValueError:
            return []
        from sqlalchemy import select
        from . import models as m

        with self._state.get_uow() as uow:
            rows = uow._session.execute(
                select(m.Check.id, m.Check.phase_id, m.Check.description)
                .where(m.Check.phase_id == resolved)
            ).mappings().all()
            return [dict(r) for r in rows]

    def get_phase_evidence(self, phase_id: int | str) -> list[dict[str, Any]]:
        try:
            resolved = self._resolve_phase_id(phase_id)
        except ValueError:
            return []
        from sqlalchemy import select
        from . import models as m

        with self._state.get_uow() as uow:
            rows = uow._session.execute(
                select(m.Evidence.id, m.Evidence.phase_id, m.Evidence.description)
                .where(m.Evidence.phase_id == resolved)
            ).mappings().all()
            return [dict(r) for r in rows]

    def create_instruction(self, data: dict[str, Any]) -> int:
        from . import models as m

        resolved = self._resolve_phase_id(data["phase_id"])
        with self._state.get_uow() as uow:
            inst = m.Instruction(
                phase_id=resolved,
                step_num=data["step_num"],
                description=data["description"],
                execution_type=data.get("execution_type", "sync"),
                skills=data.get("skills"),
            )
            uow._session.add(inst)
            uow._session.flush()
            uow.commit()
            return int(inst.id)

    def create_check(self, data: dict[str, Any]) -> int:
        from . import models as m

        resolved = self._resolve_phase_id(data["phase_id"])
        with self._state.get_uow() as uow:
            check = m.Check(phase_id=resolved, description=data["description"])
            uow._session.add(check)
            uow._session.flush()
            uow.commit()
            return int(check.id)

    def create_evidence(self, data: dict[str, Any]) -> int:
        from . import models as m

        resolved = self._resolve_phase_id(data["phase_id"])
        with self._state.get_uow() as uow:
            ev = m.Evidence(
                phase_id=resolved,
                description=data.get("description", data.get("item", "")),
            )
            uow._session.add(ev)
            uow._session.flush()
            uow.commit()
            return int(ev.id)

    # ── Projects ────────────────────────────────────────────────────────

    def get_projects(self) -> list[dict[str, Any]]:
        with self._state.get_uow() as uow:
            rows = uow.projects.list()
            return [r.to_dict() for r in rows]

    def get_project(self, project_id: int) -> dict[str, Any] | None:
        return self._state.project_service().get_project(project_id)

    def get_project_by_code(self, code: str) -> dict[str, Any] | None:
        with self._state.get_uow() as uow:
            p = uow.projects.get_by_code(code)
            return p.to_dict() if p else None

    def create_project(self, data: dict[str, Any]) -> int:
        return self._state.project_service().create_project(data)["id"]

    def update_project(self, project_id: int, data: dict[str, Any]) -> None:
        self._state.project_service().update_project(project_id, data)

    def delete_project(self, project_id: int) -> None:
        self._state.project_service().delete_project(project_id)

    def match_project_for_task_key(self, task_key: str, *, strict: bool = True) -> dict[str, Any] | None:
        with self._state.get_uow() as uow:
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
        project_id = payload.get("project_id")
        if project_id is None and payload.get("project") is not None:
            project_id = self._resolve_project_id(payload.pop("project"))
        if project_id is None and payload.get("project_code") is not None:
            project_id = self._resolve_project_id(payload.pop("project_code"))
        if project_id is None:
            project = self.match_project_for_task_key(payload.get("task_key", ""))
            if not project:
                raise ValueError(f"No project prefix matched task key: {payload.get('task_key')}")
            project_id = project["id"]
        payload["project_id"] = project_id
        return self._state.task_service().create_task(payload)["id"]

    def get_tasks(self) -> list[dict[str, Any]]:
        from sqlalchemy import select
        from . import models as m

        with self._state.get_uow() as uow:
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
        from . import models as m

        with self._state.get_uow() as uow:
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
        from . import models as m

        with self._state.get_uow() as uow:
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
        from . import models as m

        with self._state.get_uow() as uow:
            row = uow._session.get(m.Task, task_id)
            if row is None:
                from ...domain.exceptions import NotFoundError
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
        with self._state.get_uow() as uow:
            uow.tasks.delete(task_id)
            uow.commit()

    # ── Task history ────────────────────────────────────────────────────

    def add_task_history(self, task_id: int, phase_id: int | str, status: str = "pending") -> None:
        resolved = self._resolve_phase_id(phase_id)
        self._state.task_service().add_history(task_id, resolved, status)

    def get_task_history(self, task_id: int) -> list[dict[str, Any]]:
        return list(self._state.task_service()._uow.tasks.get_history(task_id))

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
        resolved_task_id = task_id
        with self._state.get_uow() as uow:
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
                phase = uow.phases.get_by_id(r.phase_id)
                next_phase = uow.phases.get_by_id(r.next_phase_id) if r.next_phase_id else None
                rollback_phase = uow.phases.get_by_id(r.rollback_phase_id) if r.rollback_phase_id else None
                task = uow.tasks.get_by_id(r.task_id)
                d["phase_code"] = phase.code if phase else None
                d["next_phase_code"] = next_phase.code if next_phase else None
                d["rollback_phase_code"] = rollback_phase.code if rollback_phase else None
                d["status"] = d.get("status", r.verdict)
                d["task_key"] = task.task_key if task else None
                result.append(d)
            return result

    def create_supervisor_run(self, data: dict[str, Any]) -> int:
        payload = dict(data)
        with self._state.get_uow() as uow:
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

    def sanitize_runtime_state(self) -> None:
        """Prune known fixture data and dedupe agents."""
        from sqlalchemy import select
        from . import models as m

        with self._state.get_uow() as uow:
            session = uow._session
            # Prune known fixture data
            fixture = session.execute(
                select(m.Project.id).where(
                    m.Project.code == "UITEST",
                    m.Project.name == "UI Test Project",
                )
            ).scalar_one_or_none()
            if fixture:
                session.execute(m.Task.__table__.delete().where(m.Task.project_id == fixture))
                session.execute(m.Project.__table__.delete().where(m.Project.id == fixture))

            # Dedupe agents
            seen: dict[tuple[str, str], int] = {}
            for row in session.execute(
                select(m.Agent.id, m.Agent.name, m.Agent.description).order_by(m.Agent.id)
            ).all():
                key = (row.name or "", row.description or "")
                if key in seen:
                    session.execute(m.Agent.__table__.delete().where(m.Agent.id == row.id))
                else:
                    seen[key] = row.id

            uow.commit()

    def get_agents(self) -> list[dict[str, Any]]:
        return self._state.agent_service().list_agents()

    def get_agent(self, agent_id: int) -> dict[str, Any] | None:
        return self._state.agent_service().get_agent(agent_id)

    def create_agent(self, data: dict[str, Any]) -> int:
        return self._state.agent_service().create_agent(data)["id"]

    def update_agent(self, agent_id: int, data: dict[str, Any]) -> None:
        self._state.agent_service().update_agent(agent_id, data)

    def delete_agent(self, agent_id: int) -> None:
        self._state.agent_service().delete_agent(agent_id)

    # ── Catalog sync / seed helpers (schema.py still calls via schema.py) ─

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
        from . import models as m

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

        with self._state.get_uow() as uow:
            session = uow._session
            self._state.workflow_service().ensure_default_exists()

            if workflow_id is not None:
                catalog_wf_id = int(workflow_id)
            else:
                default_wf = session.execute(
                    select(m.Workflow).where(m.Workflow.is_default == 1)
                ).scalar_one_or_none()
                catalog_wf_id = default_wf.id if default_wf else None
            if catalog_wf_id is None:
                raise RuntimeError("No default workflow available for phase catalog")

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
        from . import models as m

        with self._state.get_uow() as uow:
            count = uow._session.execute(select(func.count()).select_from(m.Phase)).scalar()
            return count == 0

    # ── CLI history (unused by UI, kept for duck typing) ─────────────────

    def log_cli_call(self, command: str, task_key: str | None, request: str | None, response: str | None) -> None:
        from . import models as m

        with self._state.get_uow() as uow:
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
        from . import models as m

        with self._state.get_uow() as uow:
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
