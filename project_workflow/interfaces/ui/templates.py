"""Jinja2 template setup and custom filters for the UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

from project_workflow.config import get_settings
from project_workflow.domain.project_theme import (
    DEFAULT_PROJECT_ICON,
    PROJECT_THEME_ICONS,
)
from project_workflow.interfaces.ui.project_admission import display_window

BASE_DIR = Path(__file__).parent

PROJECT_ICON_PATHS = {
    "folder": "M4 6a2 2 0 0 1 2-2h5l2 2h5a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6z",
    "project": "M4 6a2 2 0 0 1 2-2h5l2 2h5a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6z",
    "workflow": "M4 6h16v5H4z M4 14h16v4H4z M8 11v3 M16 11v3",
    "check": "M20 6 9 17l-5-5",
    "bug": "M8 7V5m8 2V5M7 8h10v9a5 5 0 0 1-10 0V8Zm-3 4h3m10 0h3M4 17h3m10 0h3M9 3l3 3 3-3",
    "rocket": "M5 19l4-1 9-9 1-4-4 1-9 9-1 4Zm6-6 3-3m-8 7-2 3 3-2",
    "shield": "M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6l7-3Zm-3 9 2 2 4-5",
    "code": "M8 9l-4 3 4 3m8-6 4 3-4 3m-2-8-4 10",
    "flask": "M9 3h6m-1 0v5l5 9a3 3 0 0 1-3 4H8a3 3 0 0 1-3-4l5-9V3m-2 12h8",
    "wrench": "M14 7a4 4 0 0 0 5 5L10 21l-5-5 9-9Zm-8 9 2 2",
    "user": "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-2a8 8 0 0 1 16 0v2",
    "users": "M14 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM2 21v-2a8 8 0 0 1 16 0v2M18 3a4 4 0 0 1 0 8m2 4a6 6 0 0 1 2 6",
    "briefcase": "M8 7V4h8v3M3 7h18v14H3V7Zm0 6h18m-11 0v3h4v-3",
    "clipboard": "M9 5H5v16h14V5h-4M9 3h6v4H9V3Zm-1 9h8m-8 4h6",
    "chart": "M3 3v18h18M7 17v-5m5 5V7m5 10V4",
    "database": "M3 6c0-4 18-4 18 0s-18 4-18 0Zm0 0v12c0 4 18 4 18 0V6M3 12c0 4 18 4 18 0",
    "server": "M3 3h18v7H3V3Zm0 11h18v7H3v-7Zm4-7h1m-1 10h1m5-10h4m-4 10h4",
    "cloud": "M6 19a5 5 0 1 1 1-10 7 7 0 0 1 13 2 4 4 0 0 1-1 8H6Z",
    "globe": "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM3 12h18M12 3c5 6 5 12 0 18-5-6-5-12 0-18Z",
    "terminal": "M3 4h18v16H3V4Zm4 4 4 4-4 4m6 0h4",
    "cpu": "M7 7h10v10H7V7Zm3 3h4v4h-4v-4M9 3v4m6-4v4M9 17v4m6-4v4M3 9h4m-4 6h4m10-6h4m-4 6h4",
    "lightbulb": "M9 18v-3a6 6 0 1 1 6 0v3H9Zm0 3h6m-3-9v6",
    "book": "M12 5C9 3 6 3 3 4v16c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1v16",
    "graduation": "m2 8 10-5 10 5-10 5L2 8Zm4 2v7c4 3 8 3 12 0v-7m4-2v10",
    "search": "M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Zm-2 5 6 6",
    "target": "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-4 0a5 5 0 1 1-10 0 5 5 0 0 1 10 0Zm-4 0h-2",
    "star": "m12 3 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1 3-6Z",
    "heart": "M12 21 3 12C-2 5 6 0 12 7c6-7 14-2 9 5l-9 9Z",
    "calendar": "M3 5h18v16H3V5Zm4-3v6m10-6v6M3 10h18M7 14h2m4 0h2m-8 4h2",
    "clock": "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 7v5l3 2",
    "message": "M3 3h18v14H8l-5 4V3Zm4 5h10M7 12h7",
    "mail": "M3 5h18v14H3V5Zm0 0 9 8 9-8",
    "camera": "M3 7h4l2-3h6l2 3h4v14H3V7Zm13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
    "palette": (
        "M12 3a9 9 0 1 0 0 18h1a2 2 0 0 0 0-4 2 2 0 0 1 0-4h4a4 4 0 0 0 4-4c0-4-4-6-9-6Z"
        "M7 8h.01M12 6h.01M17 8h.01M5 13h.01"
    ),
    "music": "M9 18V5l12-2v13M9 18c0 4-6 4-6 0s6-4 6 0Zm12-2c0 4-6 4-6 0s6-4 6 0ZM9 9l12-2",
    "compass": "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-5-4-3 5-5 3 3-5 5-3Z",
    "layers": "m12 3 10 5-10 5L2 8l10-5Zm-10 9 10 5 10-5M2 16l10 5 10-5",
}


def _project_icon_path(icon: str | None) -> str:
    return PROJECT_ICON_PATHS.get(
        str(icon or DEFAULT_PROJECT_ICON).lower(),
        PROJECT_ICON_PATHS[DEFAULT_PROJECT_ICON],
    )


def _project_icon_options() -> list[dict[str, str]]:
    return [{"key": key, "label": label, "path": _project_icon_path(key)} for key, label in PROJECT_THEME_ICONS.items()]


def _group_instructions(instructions: list[dict[str, Any]] | None) -> list[list[dict[str, Any]]]:
    """Группирует инструкции по runs: parallel примыкает к предыдущей sync и идёт с ней рядом."""
    if not instructions:
        return []
    groups: list[list[dict[str, Any]]] = [instructions[0:1]]
    for item in instructions[1:]:
        if item.get("execution_type") == "parallel":
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


def _pluralize(value: int, forms: str) -> str:
    """Russian pluralization filter: {{ count | pluralize('проект,проекта,проектов') }}."""
    n = int(value)
    one, few, many = [f.strip() for f in forms.split(",")]
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20):
        return f"{n} {few}"
    return f"{n} {many}"


templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _platform_branding_url() -> str | None:
    from .platform_branding import branding_url

    if not branding_url():
        return None
    return get_settings().UI_BASE_PATH.rstrip("/") + "/api/platform/branding"


templates.env.globals["platform_branding_url"] = _platform_branding_url

templates.env.globals["project_access_window"] = display_window
templates.env.globals["ui_base_path"] = lambda: get_settings().UI_BASE_PATH
templates.env.filters["group_instructions"] = _group_instructions
templates.env.filters["pluralize"] = _pluralize
templates.env.globals["project_icon_path"] = _project_icon_path
templates.env.globals["project_icon_paths"] = {key: _project_icon_path(key) for key in PROJECT_THEME_ICONS}
templates.env.globals["project_icon_options"] = _project_icon_options()
templates.env.globals["default_project_icon"] = DEFAULT_PROJECT_ICON
env = templates.env
