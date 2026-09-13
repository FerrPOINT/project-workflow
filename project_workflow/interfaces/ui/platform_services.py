"""Base runtime catalog for the native project-workflow service selector.

The UI is server-rendered, so it reads the public Admin Panel catalog on the
server with a short TTL cache. An unreachable Admin Panel never blocks a page:
the local fallback is rendered instead.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.request import urlopen

_FALLBACK_SERVICES: list[dict[str, Any]] = [
    {"key": "admin-panel", "label": "Admin Panel", "url": "http://localhost:7772", "health": "unknown"},
    {"key": "ci-cd", "label": "CI/CD", "url": "http://localhost:7712", "health": "unknown"},
    {"key": "task-tracker", "label": "Task Tracker", "url": "http://localhost:7722", "health": "unknown"},
    {"key": "wiki", "label": "Wiki", "url": "http://localhost:7732", "health": "unknown"},
    {"key": "fleet-control", "label": "Fleet Control", "url": "http://localhost:7742", "health": "unknown"},
]
_CURRENT_KEY = "project-workflow"
_CACHE_TTL_SECONDS = 60.0
_cached_at = 0.0
_cached_services: list[dict[str, Any]] = []
_VALID_HEALTH = {"healthy", "unreachable", "unknown"}


def _normalize(entry: dict[str, Any]) -> dict[str, Any] | None:
    key = entry.get("key")
    label = entry.get("label")
    ui_url = entry.get("ui_url", entry.get("url"))
    if not isinstance(key, str) or key == _CURRENT_KEY:
        return None
    if not isinstance(label, str) or not isinstance(ui_url, str):
        return None
    if not ui_url.startswith(("http://", "https://")):
        return None
    health = entry.get("health", "unknown")
    if health not in _VALID_HEALTH:
        health = "unknown"
    return {"key": key, "label": label, "url": ui_url, "health": health}


def load_other_services(catalog_url: str | None) -> list[dict[str, Any]]:
    """Return other UI services from catalog v1.1, cached and fail-safe."""
    global _cached_at, _cached_services
    if not catalog_url:
        return _FALLBACK_SERVICES
    now = time.monotonic()
    if _cached_services and now - _cached_at < _CACHE_TTL_SECONDS:
        return _cached_services
    try:
        with urlopen(catalog_url, timeout=2.0) as response:  # nosec B310: configured internal URL
            payload = json.loads(response.read().decode("utf-8"))
        raw_entries = payload.get("services", [])
        services = [
            normalized
            for entry in raw_entries
            if isinstance(entry, dict)
            and (normalized := _normalize(entry)) is not None
        ]
    except Exception:
        return _cached_services or _FALLBACK_SERVICES
    if not services:
        return _cached_services or _FALLBACK_SERVICES
    _cached_services = services
    _cached_at = now
    return services
