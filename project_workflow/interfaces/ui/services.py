"""Thin facade exposing UI data loaders to routes and tests.

The actual loader logic lives in project_workflow.application.ui to keep the
interface layer free of DB/infrastructure details.
"""

from __future__ import annotations

from typing import Any, cast

import project_workflow.interfaces.ui as _ui_module
from project_workflow.application.ui import UIDataService

from .dependencies import _AppState
from .helpers import (
    _build_parallel_phase_blocks,
)


def _get_app_state() -> _AppState:
    """Return the current UI application state (supports test monkeypatching)."""
    return cast(_AppState, _ui_module._app_state)


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


def _load_phases(workflow_id: int) -> list[dict[str, Any]]:
    """Load phases for UI pages/API."""
    return _ui_data_service()._load_phases(workflow_id)


def _load_phase_detail(phase_id: int) -> dict[str, Any] | None:
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


def _get_task_detail(task_key: str, project_id: int | None = None) -> dict[str, Any] | None:
    """Load task detail for UI pages/API."""
    return _ui_data_service()._get_task_detail(task_key, project_id=project_id)


__all__ = [
    "_build_parallel_phase_blocks",
    "_load_cli_reference",
    "_load_workflows",
    "_load_phases",
    "_load_phase_detail",
    "_load_tasks",
    "_load_projects",
    "_load_dashboard",
    "_get_task_detail",
]
