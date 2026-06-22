"""Seed/phase-order runtime helpers for the UI."""

from __future__ import annotations

from typing import Any, cast

import project_workflow.interfaces.ui as _ui_module

from ... import config
from ...infrastructure.db import schema
from .dependencies import _AppState


def _get_app_state() -> _AppState:
    """Return the current UI application state (supports test monkeypatching)."""
    return cast(_AppState, _ui_module._app_state)


def _seed_to_sqlite() -> None:
    """Разовый импорт seed.json → SQLite."""
    wdb = _get_app_state().get_db()
    schema.ensure_phase_catalog(wdb)


def _update_config_phase_order(wdb: Any | None = None) -> None:
    """Пересобрать runtime PHASE_ORDER из default workflow без повторного seed-sync."""
    source_db = wdb or _get_app_state().get_db()
    rows = [
        phase
        for phase in source_db.get_phases()
        if phase.get("workflow_is_default") and phase.get("is_seed_managed")
    ]
    if not rows:
        return
    sorted_rows = sorted(rows, key=lambda phase: phase["phase_order"])
    config.PHASE_ORDER[:] = [phase["code"] for phase in sorted_rows]
