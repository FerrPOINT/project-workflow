"""Thin facade exposing UI data loaders to routes and tests.

The actual loader logic lives in project_workflow.application.ui to keep the
interface layer free of DB/infrastructure details.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import project_workflow.interfaces.ui as _ui_module
from project_workflow.application.ui import UIDataService

from .dependencies import _AppState
from .helpers import (
    _build_parallel_phase_blocks,
    _parse_key_prefixes,
    _parse_optional_int,
)
from .payloads import _phase_create_payload, _workflow_form_payload


def _get_app_state() -> _AppState:
    """Return the current UI application state (supports test monkeypatching)."""
    return cast(_AppState, _ui_module._app_state)


def _get_db() -> Any:
    """Return the current DB/UoW for UI page loaders."""
    return _get_app_state().get_db()


def _ui_data_service() -> UIDataService:
    """Return the UI data service backed by the current application state."""
    return UIDataService(_get_app_state())


def _load_cli_reference() -> list[dict[str, Any]]:
    """Auto-discover CLI commands for the UI reference page."""
    from .cli_reference import _load_cli_reference as _impl

    return _impl()


def _load_workflows() -> list[dict[str, Any]]:
    """Load workflows for UI pages/API."""
    return _ui_data_service()._load_workflows()


def _load_phases(workflow_id: int | None = None) -> list[dict[str, Any]]:
    """Load phases for UI pages/API."""
    return _ui_data_service()._load_phases(workflow_id)


def _load_phase_detail(phase_id: int | str) -> dict[str, Any] | None:
    """Load phase detail for UI pages/API."""
    return _ui_data_service()._load_phase_detail(phase_id)


def _load_tasks() -> list[dict[str, Any]]:
    """Load tasks for the UI with batched history/supervisor lookups."""
    return _ui_data_service()._load_tasks()


def _load_projects() -> list[dict[str, Any]]:
    """Load projects for UI pages/API."""
    return _ui_data_service()._load_projects()


def _load_dashboard() -> dict[str, Any]:
    """Load dashboard payload."""
    return _ui_data_service()._load_dashboard()


def _get_task_detail(task_key: str) -> dict[str, Any] | None:
    """Load task detail for UI pages/API."""
    return _ui_data_service()._get_task_detail(task_key)


def _coerce_phase_db_id(raw_phase_id: int | str | None) -> int | None:
    """Coerce a phase identifier to a positive integer DB id."""
    return _ui_data_service()._coerce_phase_db_id(raw_phase_id)


def _resolve_task_phase(
    current_phase: str | int | None,
    _db: Any | None = None,
    workflow_id: int | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Resolve a phase token to (phase_id, phase_dict)."""
    from .helpers import _resolve_task_phase as _impl

    db = _db if _db is not None else _get_db()
    return _impl(current_phase, _db=db, workflow_id=workflow_id)


def _resolve_task_phase_local(
    current_phase: str | int | None,
    phases: Sequence[dict[str, Any]],
    workflow_id: int | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Resolve a phase token using a preloaded phase list."""
    from .helpers import _resolve_task_phase_local as _impl

    return _impl(current_phase, phases, workflow_id=workflow_id)


# Helpers and payloads remain importable from this module.
__all__ = [
    "_build_parallel_phase_blocks",
    "_parse_key_prefixes",
    "_parse_optional_int",
    "_phase_create_payload",
    "_workflow_form_payload",
    "_load_cli_reference",
    "_load_workflows",
    "_load_phases",
    "_load_phase_detail",
    "_load_tasks",
    "_load_projects",
    "_load_dashboard",
    "_get_task_detail",
    "_coerce_phase_db_id",
    "_resolve_task_phase",
    "_resolve_task_phase_local",
]
