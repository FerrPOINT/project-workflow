"""Base runtime catalog for the native project-workflow service selector.

The UI is server-rendered, so it reads the public Admin Panel catalog on the
server with a short TTL cache. An unreachable Admin Panel never blocks a page:
the local fallback is rendered instead.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit
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
_ORDER = {service["key"]: index for index, service in enumerate(_FALLBACK_SERVICES)}


@dataclass(frozen=True)
class ServiceCatalog:
    services: list[dict[str, Any]]
    source: str


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


def _with_request_host(services: list[dict[str, Any]], request_url: str | None) -> list[dict[str, Any]]:
    """Make localhost fallback targets usable from a remote UI session."""
    if not request_url:
        return services
    request_host = urlsplit(request_url).hostname
    if not request_host:
        return services

    adjusted: list[dict[str, Any]] = []
    for service in services:
        url = str(service["url"])
        parts = urlsplit(url)
        if parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
            adjusted.append(service)
            continue
        netloc = request_host if parts.port is None else f"{request_host}:{parts.port}"
        adjusted.append({**service, "url": urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))})
    return adjusted


def load_service_catalog(catalog_url: str | None, *, request_url: str | None = None) -> ServiceCatalog:
    """Return other UI services and the source used to render them."""
    global _cached_at, _cached_services
    if not catalog_url:
        return ServiceCatalog(_with_request_host(_FALLBACK_SERVICES, request_url), "fallback-unreachable")
    now = time.monotonic()
    if _cached_services and now - _cached_at < _CACHE_TTL_SECONDS:
        return ServiceCatalog(_with_request_host(_cached_services, request_url), "runtime")
    try:
        with urlopen(catalog_url, timeout=2.0) as response:  # nosec B310: configured internal URL
            body = response.read()
    except Exception:
        return ServiceCatalog(
            _with_request_host(_cached_services or _FALLBACK_SERVICES, request_url),
            "runtime-cached" if _cached_services else "fallback-unreachable",
        )
    try:
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("services"), list):
            raise ValueError("invalid catalog")
        raw_entries = payload["services"]
        services = [
            normalized
            for entry in raw_entries
            if isinstance(entry, dict)
            and (normalized := _normalize(entry)) is not None
        ]
    except Exception:
        return ServiceCatalog(
            _with_request_host(_cached_services or _FALLBACK_SERVICES, request_url),
            "runtime-cached" if _cached_services else "fallback-invalid",
        )
    if not services:
        return ServiceCatalog(
            _with_request_host(_cached_services or _FALLBACK_SERVICES, request_url),
            "runtime-cached" if _cached_services else ("fallback-empty" if not raw_entries else "fallback-invalid"),
        )
    services.sort(key=lambda service: (_ORDER.get(service["key"], len(_ORDER)), service["key"]))
    _cached_services = services
    _cached_at = now
    return ServiceCatalog(_with_request_host(services, request_url), "runtime")


def load_other_services(catalog_url: str | None, *, request_url: str | None = None) -> list[dict[str, Any]]:
    """Compatibility helper for callers that only need the navigation links."""
    return load_service_catalog(catalog_url, request_url=request_url).services
