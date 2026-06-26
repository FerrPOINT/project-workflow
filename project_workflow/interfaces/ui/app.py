"""FastAPI application factory and route wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text

from ... import __version__
from ...infrastructure.db.session import get_engine
from .routes import api, pages


async def _health() -> JSONResponse:
    """Liveness/readiness probe with DB connectivity check."""
    from ...infrastructure.db import session as _session
    health = {"ok": True, "version": __version__, "database": "unknown"}
    status = 200
    try:
        engine = _session.get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            health["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        health["ok"] = False
        health["database"] = "error"
        health["error"] = str(exc)
        status = 503
    return JSONResponse(health, status_code=status)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Graceful startup: verify DB is reachable before accepting traffic."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        app.state.startup_error = str(exc)
    else:
        app.state.startup_error = None
    yield
    # Shutdown: dispose engine pool to release DB connections cleanly.
    try:
        engine = get_engine()
        engine.dispose()
    except Exception:  # noqa: BLE001
        pass


def create_app() -> FastAPI:
    app = FastAPI(title="project-workflow UI", version=__version__, lifespan=_lifespan)

    app.get("/health")(_health)

    # Pages
    app.get("/", response_class=HTMLResponse)(pages.index)
    app.get("/phases", response_class=HTMLResponse)(pages.phases_page)
    app.get("/phase/{phase_id}", response_class=HTMLResponse)(pages.phase_detail)
    app.get("/tasks", response_class=HTMLResponse)(pages.tasks_page)
    app.get("/projects", response_class=HTMLResponse)(pages.projects_page)
    app.get("/workflows", response_class=HTMLResponse)(pages.workflows_page)
    app.get("/task/{task_key}", response_class=HTMLResponse)(pages.task_detail_page)
    app.get("/settings", response_class=HTMLResponse)(pages.settings_page)
    app.get("/skills", response_class=HTMLResponse)(pages.skills_page)
    app.get("/agents", response_class=HTMLResponse)(pages.agents_page)

    # API
    app.get("/api/settings", response_model=None)(api.api_settings_get)
    app.get("/api/skills", response_model=None)(api.api_skills)
    app.get("/api/phases", response_model=None)(api.api_phases)
    app.get("/api/phases/{phase_id}", response_model=None)(api.api_phase_detail)
    app.post("/api/phases", response_model=None)(api.api_phase_create)
    app.delete("/api/phases/{phase_id}", response_model=None)(api.api_phase_delete)
    app.get("/api/tasks", response_model=None)(api.api_tasks)
    app.get("/api/tasks/{task_key}", response_model=None)(api.api_task_detail)
    app.delete("/api/tasks/{task_key}", response_model=None)(api.api_task_delete)
    app.get("/api/workflows", response_model=None)(api.api_workflows)
    app.post("/api/workflows", response_model=None)(api.api_workflow_create)
    app.put("/api/workflows/{workflow_id}", response_model=None)(api.api_workflow_update)
    app.delete("/api/workflows/{workflow_id}", response_model=None)(api.api_workflow_delete)
    app.get("/api/projects", response_model=None)(api.api_projects)
    app.post("/api/projects", response_model=None)(api.api_project_create)
    app.put("/api/projects/{project_id}", response_model=None)(api.api_project_update)
    app.delete("/api/projects/{project_id}", response_model=None)(api.api_project_delete)
    app.get("/api/agents", response_model=None)(api.api_agents)
    app.post("/api/agents", response_model=None)(api.api_agent_create)
    app.put("/api/agents/{agent_id}", response_model=None)(api.api_agent_update)
    app.delete("/api/agents/{agent_id}", response_model=None)(api.api_agent_delete)
    # Removed legacy endpoints handler
    async def _not_found() -> JSONResponse:
        return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)

    # Phase order / detail / legacy removed (must come before /{phase_id})
    app.put("/api/phases/order", response_model=None)(api.api_update_order)
    app.put("/api/phases/parallel", response_model=None)(_not_found)
    app.put("/api/phases/{phase_id}", response_model=None)(api.api_phase_update)
    app.put("/api/phases/{phase_id}/group", response_model=None)(_not_found)

    # Instructions management
    app.get("/api/phases/{phase_id}/instructions", response_model=None)(api.api_instructions_list)
    app.post("/api/instructions", response_model=None)(api.api_instruction_create)
    app.put("/api/instructions/{instruction_id}", response_model=None)(api.api_instruction_update)
    app.put("/api/instructions/{instruction_id}/skills", response_model=None)(api.api_instruction_update_skills)
    app.delete("/api/instructions/{instruction_id}", response_model=None)(api.api_instruction_delete)
    app.put("/api/phases/{phase_id}/instructions/reorder", response_model=None)(api.api_instructions_reorder)

    return app


app = create_app()
