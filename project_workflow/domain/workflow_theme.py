"""Workflow branding and theme normalization."""

from __future__ import annotations

import re
from typing import Any

DEFAULT_WORKFLOW_ICON = "workflow"
DEFAULT_WORKFLOW_COLOR = "#5E6AD2"

WORKFLOW_THEME_ICONS: dict[str, str] = {
    "workflow": "Воркфлоу",
    "check": "Проверка",
    "bug": "Тестирование",
    "rocket": "Релиз",
    "shield": "Контроль",
    "code": "Разработка",
    "flask": "Эксперимент",
    "wrench": "Поддержка",
}


def normalize_theme_icon(value: Any) -> str:
    """Return a canonical icon key from the fixed workflow icon catalog."""
    if value is None:
        return DEFAULT_WORKFLOW_ICON
    if not isinstance(value, str):
        raise ValueError("Иконка воркфлоу должна быть строкой")
    icon = value.strip().lower()
    if icon not in WORKFLOW_THEME_ICONS:
        allowed = ", ".join(sorted(WORKFLOW_THEME_ICONS))
        raise ValueError(f"Иконка воркфлоу должна быть одной из: {allowed}")
    return icon


def normalize_theme_color(value: Any) -> str:
    """Return a canonical uppercase ``#RRGGBB`` theme color."""
    if value is None:
        return DEFAULT_WORKFLOW_COLOR
    if not isinstance(value, str):
        raise ValueError("Цвет воркфлоу должен быть строкой")
    color = value.strip()
    if re.fullmatch(r"[0-9a-fA-F]{6}", color):
        color = f"#{color}"
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("Цвет воркфлоу должен быть HEX-цветом #RRGGBB")
    return color.upper()
