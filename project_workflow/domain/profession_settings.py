"""Execution configuration is owned by a profession, independently of its workflows."""

import re
from typing import Any


def normalize_role_key(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Роль должна быть непустой строкой или null")
    return value.strip()


def normalize_launch_profile(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Профиль запуска должен быть строкой или null")
    profile = value.strip()
    if not profile or len(profile) > 251 or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", profile):
        raise ValueError("Профиль запуска должен соответствовать [a-z0-9][a-z0-9_-]* и содержать от 1 до 251 символа")
    return profile
