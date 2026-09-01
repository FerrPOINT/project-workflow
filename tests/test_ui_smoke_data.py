"""Tests for neutral UI smoke data used by screenshots."""

from __future__ import annotations

from project_workflow import config
from project_workflow.infrastructure.db.session import reset_engine
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from scripts.prepare_ui_smoke_data import TASK_KEY, prepare_smoke_data


def test_prepare_ui_smoke_data_creates_neutral_parallel_namespace_fixture(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'ui-smoke.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.get_settings.cache_clear()
    reset_engine()

    try:
        prepare_smoke_data()
        with SAUnitOfWork() as uow:
            namespaces = [namespace.to_dict() for namespace in uow.projects.list()]
            workflows = [workflow.to_dict() for workflow in uow.workflows.list()]
            visible_text = "\n".join(
                f"{namespace.get('name', '')} {namespace.get('description', '')}" for namespace in namespaces
            )
            visible_text += "\n" + "\n".join(
                f"{workflow.get('name', '')} {workflow.get('description', '')}" for workflow in workflows
            )
            dev = next(namespace for namespace in namespaces if namespace["cli_command"] == "workflow-dev")
            qa = next(namespace for namespace in namespaces if namespace["cli_command"] == "workflow-qa")
            dev_task = uow.tasks.get_by_key(TASK_KEY, project_id=dev["id"])
            qa_task = uow.tasks.get_by_key(TASK_KEY, project_id=qa["id"])
    finally:
        reset_engine()
        config.get_settings.cache_clear()

    assert "Hermes" not in visible_text
    assert "Smoke" not in visible_text
    assert dev["name"] == "Разработка"
    assert qa["name"] == "Проверка качества"
    assert dev["workflow_id"] != qa["workflow_id"]
    assert dev_task is not None
    assert qa_task is not None
    assert dev_task.task_key == qa_task.task_key == TASK_KEY
