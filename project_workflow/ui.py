"""Backwards-compatible shim for ``python -m project_workflow.ui``.

All implementation now lives in ``project_workflow.ui`` package.  This module
re-exports the public symbols previously defined here so that tests, systemd
and manual imports keep working.
"""

from __future__ import annotations

from project_workflow.ui import (
    _AppState,
    _app_state,
    _build_parallel_phase_blocks,
    _coerce_phase_db_id,
    _get_task_detail,
    _group_instructions,
    _load_cli_reference,
    _load_dashboard,
    _load_phase_detail,
    _load_phases,
    _load_projects,
    _load_skills_catalog,
    _load_tasks,
    _load_workflows,
    _parse_key_patterns,
    _parse_optional_int,
    _resolve_task_phase,
    _scan_hermes_skills,
    _seed_to_sqlite,
    _tojson_unicode,
    _update_config_phase_order,
    _workflow_form_payload,
    app,
    main,
)

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
]
