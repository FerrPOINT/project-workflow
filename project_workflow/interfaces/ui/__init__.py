"""Public UI package exports.

``_app_state`` is resolved lazily through ``__getattr__`` so that test
monkeypatches of ``project_workflow.interfaces.ui.state._app_state`` are visible to consumers
importing ``project_workflow.interfaces.ui._app_state``.
"""

from __future__ import annotations

import sys
from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import app
    from .dependencies import _AppState
    from .main import main
    from .services import (
        _build_parallel_phase_blocks,
        _get_task_detail,
        _load_cli_reference,
        _load_dashboard,
        _load_namespaces,
        _load_phase_detail,
        _load_phases,
        _load_projects,
        _load_tasks,
        _load_workflows,
    )
    from .state import _app_state
    from .templates import _group_instructions
    from .templates import env as _templates_env

_EXPORTS = {
    "app": (".app", "app"),
    "main": (".main", "main"),
    "_app_state": (".state", "_app_state"),
    "_AppState": (".dependencies", "_AppState"),
    "_build_parallel_phase_blocks": (".services", "_build_parallel_phase_blocks"),
    "_get_task_detail": (".services", "_get_task_detail"),
    "_group_instructions": (".templates", "_group_instructions"),
    "_load_cli_reference": (".services", "_load_cli_reference"),
    "_load_dashboard": (".services", "_load_dashboard"),
    "_load_namespaces": (".services", "_load_namespaces"),
    "_load_phase_detail": (".services", "_load_phase_detail"),
    "_load_phases": (".services", "_load_phases"),
    "_load_projects": (".services", "_load_projects"),
    "_load_tasks": (".services", "_load_tasks"),
    "_load_workflows": (".services", "_load_workflows"),
    "_templates_env": (".templates", "env"),
}
__all__ = [
    "app", "main", "_app_state", "_AppState", "_build_parallel_phase_blocks",
    "_get_task_detail", "_group_instructions", "_load_cli_reference", "_load_dashboard",
    "_load_namespaces", "_load_phase_detail", "_load_phases", "_load_projects",
    "_load_tasks", "_load_workflows", "_templates_env",
]


def __getattr__(name: str) -> object:
    try:
        module, attribute = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(import_module(module, __name__), attribute)
    # Preserve state read-through and explicit test overrides; immutable legacy
    # exports retain the same object identity after their first consumer.
    if name not in {"_app_state", "_AppState"}:
        globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


class _UiExports(ModuleType):
    def __setattr__(self, name: str, value: object) -> None:
        # Importlib installs child modules on their parent after execution. Two
        # legacy exports share those names: preserve the actual app/function
        # even when ui.app or ui.main is imported before the package export.
        if (
            name in {"app", "main"} and isinstance(value, ModuleType)
            and value.__name__ == f"{__name__}.{name}"
        ):
            value = getattr(value, name)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _UiExports
