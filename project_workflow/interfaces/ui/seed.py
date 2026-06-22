"""Seed/phase-order runtime helpers for the UI."""

from __future__ import annotations

from typing import Any, cast

import project_workflow.interfaces.ui as _ui_module

from ... import config
from ...application.phase import PhaseServiceApp
from ...infrastructure.db import schema
from ...infrastructure.db.uow import SAUnitOfWork
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
    if isinstance(source_db, SAUnitOfWork):
        uow = source_db
    else:
        uow = _get_app_state().get_uow()
    default_workflow = uow.workflows.get_default()
    workflow_id = default_workflow.id if default_workflow else None
    rows = [
        phase
        for phase in PhaseServiceApp(uow).list_phases(workflow_id=workflow_id)
        if phase.get("workflow_is_default") and phase.get("is_seed_managed")
    ]
    if not rows:
        return
    sorted_rows = sorted(rows, key=lambda phase: phase["phase_order"])
    config.PHASE_ORDER[:] = [phase["code"] for phase in sorted_rows]
