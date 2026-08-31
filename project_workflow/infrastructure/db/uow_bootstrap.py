"""Bootstrap helpers for SAUnitOfWork."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .uow import SAUnitOfWork


def bootstrap_default_project(uow: SAUnitOfWork) -> None:
    from project_workflow import config

    code = config.DEFAULT_PROJECT_CODE
    if uow.projects.get_by_code(code) is None:
        default_wf = uow.workflows.get_default()
        if default_wf is None or default_wf.id is None:
            raise ValueError("Начальный воркфлоу не загружен")
        if not uow.phases.list(default_wf.id):
            raise ValueError("Начальный воркфлоу не содержит фаз")
        uow.projects.create(
            {
                "workflow_id": default_wf.id,
                "code": code,
                "name": config.DEFAULT_PROJECT_NAME,
                "cli_command": config.DEFAULT_NAMESPACE_CLI_COMMAND,
                "key_prefixes": list(config.DEFAULT_TASK_KEY_PREFIXES),
            }
        )
