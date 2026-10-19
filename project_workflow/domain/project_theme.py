"""Branding and theme normalization for configured CLI entries."""

from __future__ import annotations

import re
from typing import Any

DEFAULT_PROJECT_ICON = "folder"
DEFAULT_PROJECT_COLOR = "#5E6AD2"

PROJECT_THEME_ICONS: dict[str, str] = {
    "folder": "Папка",
    "workflow": "Воркфлоу",
    "check": "Проверка",
    "bug": "Тестирование",
    "rocket": "Релиз",
    "shield": "Контроль",
    "code": "Разработка",
    "flask": "Эксперимент",
    "wrench": "Поддержка",
    "user": "Пользователь",
    "users": "Команда",
    "briefcase": "Портфель",
    "clipboard": "План",
    "chart": "Аналитика",
    "database": "База данных",
    "server": "Сервер",
    "cloud": "Облако",
    "globe": "Мир",
    "terminal": "Терминал",
    "cpu": "Процессор",
    "lightbulb": "Идея",
    "book": "Книга",
    "graduation": "Обучение",
    "search": "Поиск",
    "target": "Цель",
    "star": "Звезда",
    "heart": "Сердце",
    "calendar": "Календарь",
    "clock": "Время",
    "message": "Обсуждение",
    "mail": "Почта",
    "camera": "Камера",
    "palette": "Дизайн",
    "music": "Музыка",
    "compass": "Направление",
    "layers": "Слои",
}

# User-facing defaults are independent of immutable executor/profile keys.
MANAGED_PROFESSION_PRESENTATION = {
    "project_manager": ("Руководитель проекта", "Уточнение задачи, формулирование целей и критериев приёмки."),
    "analyst": ("Аналитик", "Анализ требований, сценариев и ограничений задачи."),
    "architect": ("Архитектор", "Проектирование решения, компонентов и их взаимодействия."),
    "developer": ("Разработчик", "Реализация изменений и проверка их работоспособности."),
    "reviewer": ("Рецензент кода", "Независимая проверка изменений и качества кода."),
    "tester": ("Тестировщик", "Проверка поведения приложения и критериев приёмки."),
    "devops": ("Инженер по эксплуатации", "Подготовка поставки и проверка работы приложения в окружении."),
}

MANAGED_PROFESSION_THEMES = {
    "project_manager": ("briefcase", "#F59E0B"),
    "analyst": ("chart", "#06B6D4"),
    "architect": ("layers", "#8B5CF6"),
    "developer": ("code", "#3B82F6"),
    "reviewer": ("shield", "#F97316"),
    "tester": ("flask", "#22C55E"),
    "devops": ("rocket", "#F43F5E"),
}

_LEGACY_ICON_ALIASES = {"project": DEFAULT_PROJECT_ICON}


def normalize_theme_icon(value: Any) -> str:
    """Return a canonical icon key from the fixed icon catalog."""
    if value is None:
        return DEFAULT_PROJECT_ICON
    if not isinstance(value, str):
        raise ValueError("Иконка должна быть строкой")
    icon = _LEGACY_ICON_ALIASES.get(value.strip().lower(), value.strip().lower())
    if icon not in PROJECT_THEME_ICONS:
        allowed = ", ".join(sorted(PROJECT_THEME_ICONS))
        raise ValueError(f"Иконка должна быть одной из: {allowed}")
    return icon


def normalize_theme_color(value: Any) -> str:
    """Return a canonical uppercase ``#RRGGBB`` theme color."""
    if value is None:
        return DEFAULT_PROJECT_COLOR
    if not isinstance(value, str):
        raise ValueError("Цвет должен быть строкой")
    color = value.strip()
    if re.fullmatch(r"[0-9a-fA-F]{6}", color):
        color = f"#{color}"
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("Цвет должен быть HEX-цветом #RRGGBB")
    return color.upper()
