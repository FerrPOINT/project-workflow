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


def _is_namespace_visible(namespace_id: int) -> bool:
    return _ui_data_service().is_namespace_visible(namespace_id)


def _visibility_is_restricted() -> bool:
    return _ui_data_service().visibility_is_restricted()


def _is_workflow_visible(workflow_id: int) -> bool:
    return _ui_data_service().is_workflow_visible(workflow_id)


def _is_phase_visible(phase_id: int) -> bool:
    return _ui_data_service().is_phase_visible(phase_id)


def _is_agent_visible(agent_id: int) -> bool:
    return _ui_data_service().is_agent_visible(agent_id)


def _load_phases(workflow_id: int) -> list[dict[str, Any]]:
    """Load phases for UI pages/API."""
    return _ui_data_service()._load_phases(workflow_id)


def _load_phase_detail(phase_id: int) -> dict[str, Any] | None:
    """Load phase detail for UI pages/API."""
    return _ui_data_service()._load_phase_detail(phase_id)


def _load_tasks(namespace_id: int | None = None) -> list[dict[str, Any]]:
    """Load tasks for the UI with batched history/supervisor lookups."""
    return _ui_data_service()._load_tasks(namespace_id=namespace_id)


def _load_projects() -> list[dict[str, Any]]:
    """Load projects for UI pages/API."""
    return _ui_data_service()._load_projects()


def _load_namespaces() -> list[dict[str, Any]]:
    """Load namespaces for UI pages/API."""
    return _ui_data_service()._load_namespaces()


def _load_agents() -> list[dict[str, Any]]:
    return _ui_data_service()._load_agents()


def _load_dashboard(namespace_id: int | None = None) -> dict[str, Any]:
    """Load dashboard payload."""
    return _ui_data_service()._load_dashboard(namespace_id=namespace_id)


def _get_task_detail(task_key: str, project_id: int | None = None) -> dict[str, Any] | None:
    """Load task detail for UI pages/API."""
    return _ui_data_service()._get_task_detail(task_key, project_id=project_id)


__all__ = [
    "_build_parallel_phase_blocks",
    "_load_cli_reference",
    "_is_namespace_visible",
    "_visibility_is_restricted",
    "_is_workflow_visible",
    "_is_phase_visible",
    "_is_agent_visible",
    "_load_workflows",
    "_load_phases",
    "_load_phase_detail",
    "_load_tasks",
    "_load_projects",
    "_load_namespaces",
    "_load_agents",
    "_load_dashboard",
    "_get_task_detail",
]
