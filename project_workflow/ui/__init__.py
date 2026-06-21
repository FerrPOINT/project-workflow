"""Public UI package exports.

``_app_state`` is resolved lazily through ``__getattr__`` so that test
monkeypatches of ``project_workflow.ui.state._app_state`` are visible to consumers
importing ``project_workflow.ui._app_state``.
"""

from __future__ import annotations

from .app import app
from .main import main
from .seed import _seed_to_sqlite, _update_config_phase_order
from .services import (
    _build_parallel_phase_blocks,
    _coerce_phase_db_id,
    _get_task_detail,
    _group_instructions,
    _load_cli_reference,
    _load_dashboard,
    _load_phase_detail,
    _load_phases,
    _load_projects,
    _load_tasks,
    _load_workflows,
    _parse_key_patterns,
    _parse_optional_int,
    _resolve_task_phase,
    _workflow_form_payload,
)
from .skills import _load_skills_catalog, _scan_hermes_skills
from .templates import _tojson_unicode, env as _templates_env

__all__ = [
    "app",
    "main",
    "_app_state",
    "_AppState",
    "_build_parallel_phase_blocks",
    "_coerce_phase_db_id",
    "_get_task_detail",
    "_group_instructions",
    "_load_cli_reference",
    "_load_dashboard",
    "_load_phase_detail",
    "_load_phases",
    "_load_projects",
    "_load_skills_catalog",
    "_load_tasks",
    "_load_workflows",
    "_parse_key_patterns",
    "_parse_optional_int",
    "_resolve_task_phase",
    "_scan_hermes_skills",
    "_seed_to_sqlite",
    "_tojson_unicode",
    "_update_config_phase_order",
    "_workflow_form_payload",
    "_templates_env",
]


def __getattr__(name: str) -> object:
    if name == "_app_state":
        from .state import _app_state
        return _app_state
    if name == "_AppState":
        from .dependencies import _AppState
        return _AppState
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
