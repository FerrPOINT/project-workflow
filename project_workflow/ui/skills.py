"""CLI skills catalog helpers used by the UI settings page."""

from __future__ import annotations

import importlib
import time

_SKILLS_CACHE_TTL_SECONDS = 60.0
_skills_catalog_cache: list[dict[str, str | None]] | None = None
_skills_catalog_cached_at = 0.0


def _scan_hermes_skills() -> list[dict[str, str | None]]:
    try:
        skills_tool = importlib.import_module("tools.skills_tool")
        find_all_skills = getattr(skills_tool, "_find_all_skills")
    except Exception:
        return []

    try:
        found = find_all_skills()
    except Exception:
        return []

    skills: list[dict[str, str | None]] = []
    for item in found or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        skills.append({
            "name": name,
            "description": str(item.get("description") or "").strip() or None,
            "category": str(item.get("category") or "").strip() or None,
        })

    skills.sort(key=lambda item: ((item.get("category") or ""), item["name"]))
    return skills


def _load_skills_catalog(*, refresh: bool = False) -> list[dict[str, str | None]]:
    global _skills_catalog_cache, _skills_catalog_cached_at

    now = time.monotonic()
    if (
        not refresh
        and _skills_catalog_cache is not None
        and now - _skills_catalog_cached_at < _SKILLS_CACHE_TTL_SECONDS
    ):
        return [dict(item) for item in _skills_catalog_cache]

    # Resolve the scanner dynamically so test monkeypatches on project_workflow.ui
    # propagate even though the scanner lives in a submodule.
    from project_workflow.ui import _scan_hermes_skills

    _skills_catalog_cache = _scan_hermes_skills()
    _skills_catalog_cached_at = now
    return [dict(item) for item in _skills_catalog_cache]
