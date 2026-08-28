"""Jinja2 template setup and custom filters for the UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

from project_workflow.domain.workflow_theme import (
    DEFAULT_WORKFLOW_ICON,
    WORKFLOW_THEME_ICONS,
)

BASE_DIR = Path(__file__).parent

WORKFLOW_ICON_PATHS = {
    "workflow": "M4 6h16v5H4z M4 14h16v4H4z M8 11v3 M16 11v3",
    "check": "M20 6 9 17l-5-5",
    "bug": "M8 7V5m8 2V5M7 8h10v9a5 5 0 0 1-10 0V8Zm-3 4h3m10 0h3M4 17h3m10 0h3M9 3l3 3 3-3",
    "rocket": "M5 19l4-1 9-9 1-4-4 1-9 9-1 4Zm6-6 3-3m-8 7-2 3 3-2",
    "shield": "M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6l7-3Zm-3 9 2 2 4-5",
    "code": "M8 9l-4 3 4 3m8-6 4 3-4 3m-2-8-4 10",
    "flask": "M9 3h6m-1 0v5l5 9a3 3 0 0 1-3 4H8a3 3 0 0 1-3-4l5-9V3m-2 12h8",
    "wrench": "M14 7a4 4 0 0 0 5 5L10 21l-5-5 9-9Zm-8 9 2 2",
}


def _workflow_icon_path(icon: str | None) -> str:
    return WORKFLOW_ICON_PATHS.get(
        str(icon or DEFAULT_WORKFLOW_ICON).lower(),
        WORKFLOW_ICON_PATHS[DEFAULT_WORKFLOW_ICON],
    )


def _workflow_icon_options() -> list[dict[str, str]]:
    return [
        {"key": key, "label": label, "path": _workflow_icon_path(key)}
        for key, label in WORKFLOW_THEME_ICONS.items()
    ]


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
templates.env.filters["group_instructions"] = _group_instructions
templates.env.filters["pluralize"] = _pluralize
templates.env.globals["workflow_icon_path"] = _workflow_icon_path
templates.env.globals["workflow_icon_paths"] = WORKFLOW_ICON_PATHS
templates.env.globals["workflow_icon_options"] = _workflow_icon_options()
env = templates.env
