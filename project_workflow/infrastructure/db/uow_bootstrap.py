"""Bootstrap helpers for SAUnitOfWork."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .uow import SAUnitOfWork


def bootstrap_default_project(uow: SAUnitOfWork) -> None:
    from project_workflow import config

    code = config.DEFAULT_PROJECT_CODE
    if uow.projects.get_by_code(code) is None:
        default_wf = uow.workflows.ensure_default_exists(config.DEFAULT_WORKFLOW_NAME)
        uow.projects.create(
            {
                "workflow_id": default_wf.id,
                "code": code,
                "name": config.DEFAULT_PROJECT_NAME,
                "key_prefixes": list(config.DEFAULT_TASK_KEY_PREFIXES),
            }
        )
