"""FastAPI application factory and route wiring."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from .. import __version__
from .routes import api, pages


def create_app() -> FastAPI:
    app = FastAPI(title="project-workflow UI", version=__version__)

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

    return app


app = create_app()
