"""FastAPI application factory and route wiring."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from ... import __version__
from ...infrastructure.db.session import get_engine, reset_engine
from .routes import api, pages

logger = logging.getLogger(__name__)

_VALIDATION_MESSAGES = {
    "missing": "Обязательное поле не указано",
    "extra_forbidden": "Неизвестное поле",
    "int_type": "Ожидается целое число",
    "string_type": "Ожидается строка",
    "list_type": "Ожидается массив",
    "literal_error": "Недопустимое значение",
    "greater_than": "Значение меньше допустимого",
    "greater_than_equal": "Значение меньше допустимого",
    "too_short": "Недостаточно элементов",
}


def _validation_details(exc: RequestValidationError) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for issue in exc.errors():
        location = ".".join(str(part) for part in issue["loc"] if part not in {"body", "query", "path"})
        message = str(issue.get("msg", ""))
        if message.startswith("Value error, "):
            message = message.removeprefix("Value error, ")
        else:
            message = _VALIDATION_MESSAGES.get(str(issue.get("type")), "Недопустимое значение")
        details.append({"field": location or "request", "message": message})
    return details


class _UoWMiddleware(BaseHTTPMiddleware):
    """Share and close one UnitOfWork for all services used by a request."""

    async def dispatch(self, request: Request, call_next):
        from ...application.state import _app_state, _uow_ctx

        if request.url.path == "/health":
            return await call_next(request)
        uow = _app_state.create_uow()
        token = _uow_ctx.set(uow)
        try:
            return await call_next(request)
        except Exception:
            uow.rollback()
            raise
        finally:
            _uow_ctx.reset(token)
            uow.close()


class _RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every incoming request with method, path, status and duration."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s %s %.2fms",
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
        return response


async def _health() -> JSONResponse:
    """Readiness probe for connectivity, schema presence, and migration head."""
    from ...infrastructure.db import session as _session

    health = {"ok": True, "version": __version__, "database": "unknown", "schema": "unknown"}
    status = 200
    start = time.perf_counter()
    try:
        engine = _session.get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        health["database"] = "ok"
        if not _session.schema_is_ready(engine):
            raise RuntimeError("schema-not-ready")
        health["schema"] = "ok"
    except Exception:
        logger.error("Health readiness check failed")
        health["ok"] = False
        if health["database"] != "ok":
            health["database"] = "error"
            health["error_code"] = "database-unavailable"
        else:
            health["schema"] = "error"
            health["error_code"] = "schema-not-ready"
        status = 503
    health["db_latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
    return JSONResponse(health, status_code=status)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Graceful startup: verify DB is reachable before accepting traffic."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        logger.warning("База данных недоступна при запуске приложения")
    yield
    # Shutdown: dispose and clear the cached engine pool.
    try:
        reset_engine()
    except Exception:
        logger.warning("Не удалось освободить пул базы данных при остановке приложения")


def create_app() -> FastAPI:
    app = FastAPI(title="Интерфейс project-workflow", version=__version__, lifespan=_lifespan)
    app.add_middleware(_RequestLoggingMiddleware)
    app.add_middleware(_UoWMiddleware)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {
                "ok": False,
                "error": "Некорректные данные запроса",
                "details": _validation_details(exc),
            },
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404 and request.method == "DELETE" and request.url.path.startswith("/api/tasks/"):
            return JSONResponse({"ok": False, "error": "Метод не поддерживается"}, status_code=405)
        if exc.status_code == 404:
            return JSONResponse({"ok": False, "error": "Ресурс не найден"}, status_code=404)
        if exc.status_code == 405:
            return JSONResponse({"ok": False, "error": "Метод не поддерживается"}, status_code=405)
        return JSONResponse({"ok": False, "error": str(exc.detail)}, status_code=exc.status_code)

    app.get("/health")(_health)

    # Pages
    app.get("/", response_class=HTMLResponse)(pages.index)
    app.get("/phases", response_class=HTMLResponse)(pages.phases_page)
    app.get("/phase/{phase_id}", response_class=HTMLResponse)(pages.phase_detail)
    app.get("/instructions", response_class=HTMLResponse)(pages.instructions_page)
    app.get("/tasks", response_class=HTMLResponse)(pages.tasks_page)
    app.get("/projects", response_class=HTMLResponse)(pages.projects_page)
    app.get("/workflows", response_class=HTMLResponse)(pages.workflows_page)
    app.get("/task/{task_key}", response_class=HTMLResponse)(pages.task_detail_page)
    app.get("/settings", response_class=HTMLResponse)(pages.settings_page)
    app.get("/agents", response_class=HTMLResponse)(pages.agents_page)

    # API
    app.get("/api/settings", response_model=None)(api.api_settings_get)
    app.get("/api/phases", response_model=None)(api.api_phases)
    app.get("/api/phases/{phase_id:int}", response_model=None)(api.api_phase_detail)
    app.post("/api/phases", response_model=None)(api.api_phase_create)
    app.delete("/api/phases/{phase_id:int}", response_model=None)(api.api_phase_delete)
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

    # Phase order update must be registered before /{phase_id} to avoid shadowing.
    app.put("/api/phases/order", response_model=None)(api.api_phase_batch_order)
    app.put("/api/phases/{phase_id:int}", response_model=None)(api.api_phase_update)

    # Instructions management
    app.get("/api/phases/{phase_id:int}/instructions", response_model=None)(api.api_instructions_list)
    app.post("/api/instructions", response_model=None)(api.api_instruction_create)
    app.put("/api/instructions/{instruction_id}", response_model=None)(api.api_instruction_update)
    app.delete("/api/instructions/{instruction_id}", response_model=None)(api.api_instruction_delete)
    app.put("/api/phases/{phase_id:int}/instructions/reorder", response_model=None)(api.api_instructions_reorder)

    return app


app = create_app()
