"""Jinja2 template setup and custom filters for the UI."""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from markupsafe import Markup


BASE_DIR = Path(__file__).parent


def _tojson_unicode(value: Any, indent: int = 2) -> Markup:
    return Markup(_json.dumps(value, ensure_ascii=False, indent=indent, default=str))


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
templates.env.filters["tojson_unicode"] = _tojson_unicode
templates.env.filters["group_instructions"] = _group_instructions
templates.env.filters["pluralize"] = _pluralize
env = templates.env
