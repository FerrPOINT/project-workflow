"""Tests for neutral UI smoke data used by screenshots."""

from __future__ import annotations

from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.application import state as app_state
from project_workflow.application.state import _AppState
from project_workflow.infrastructure.db.session import reset_engine
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from scripts.prepare_ui_smoke_data import (
    DEFAULT_DEMO_WORKFLOW_NAME,
    QA_WORKFLOW_NAME,
    TASK_KEY,
    TASK_SCENARIOS,
    prepare_smoke_data,
)


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
            phases = [phase.to_dict() for phase in uow.phases.list()]
            agents = [agent.to_dict() for agent in uow.agents.list()]
            visible_text = "\n".join(
                f"{namespace.get('name', '')} {namespace.get('description', '')}" for namespace in namespaces
            )
            visible_text += "\n" + "\n".join(
                f"{workflow.get('name', '')} {workflow.get('description', '')}" for workflow in workflows
            )
            visible_text += "\n" + "\n".join(
                f"{phase.get('name', '')} {phase.get('description', '')}" for phase in phases
            )
            visible_text += "\n" + "\n".join(
                f"{agent.get('name', '')} {agent.get('description', '')} {agent.get('hermes_profile', '')}"
                for agent in agents
            )
            dev = next(namespace for namespace in namespaces if namespace["cli_command"] == "workflow-dev")
            qa = next(namespace for namespace in namespaces if namespace["cli_command"] == "workflow-qa")
            dev_tasks = [task.to_dict() for task in uow.tasks.list_by_project(dev["id"])]
            qa_tasks = [task.to_dict() for task in uow.tasks.list_by_project(qa["id"])]
            visible_text += "\n" + "\n".join(
                f"{task.get('task_key', '')} {task.get('title', '')}" for task in [*dev_tasks, *qa_tasks]
            )
            visible_text += "\n" + "\n".join(
                f"{entry.worker_report} {entry.supervisor_response.get('message', '')}"
                for entry in uow.step_history.list(limit=None)
            )
            dev_task = uow.tasks.get_by_key(TASK_KEY, project_id=dev["id"])
            qa_task = uow.tasks.get_by_key(TASK_KEY, project_id=qa["id"])
    finally:
        reset_engine()
        config.get_settings.cache_clear()

    assert "hermes" not in visible_text.casefold()
    assert "sdlc-" not in visible_text.casefold()
    assert "sdlc-business-tech-v1" not in visible_text
    assert "Smoke" not in visible_text
    assert DEFAULT_DEMO_WORKFLOW_NAME in visible_text
    assert QA_WORKFLOW_NAME in visible_text
    assert dev["name"] == "Разработка"
    assert qa["name"] == "Проверка качества"
    assert dev["workflow_id"] != qa["workflow_id"]
    assert all(
        agent["hermes_profile"] is None or str(agent["hermes_profile"]).startswith("launch-")
        for agent in agents
    )
    assert len(TASK_SCENARIOS["workflow-dev"]) >= 8
    assert len(TASK_SCENARIOS["workflow-qa"]) >= 8
    assert len(dev_tasks) == len(TASK_SCENARIOS["workflow-dev"])
    assert len(qa_tasks) == len(TASK_SCENARIOS["workflow-qa"])
    assert {task["status"] for task in dev_tasks} == {"active", "blocked", "done"}
    assert {task["status"] for task in qa_tasks} == {"active", "blocked", "done"}
    assert dev_task is not None
    assert qa_task is not None
    assert dev_task.task_key == qa_task.task_key == TASK_KEY


def test_ui_smoke_pages_render_neutral_screenshot_fixture(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'ui-smoke.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(app_state, "_app_state", _AppState(database_url=database_url))
    config.get_settings.cache_clear()
    reset_engine()

    try:
        prepare_smoke_data()
        with SAUnitOfWork(database_url) as uow:
            namespaces = [namespace.to_dict() for namespace in uow.projects.list()]
            dev = next(namespace for namespace in namespaces if namespace["cli_command"] == "workflow-dev")
            qa = next(namespace for namespace in namespaces if namespace["cli_command"] == "workflow-qa")
            dev_phase = next(
                phase for phase in uow.phases.list(workflow_id=dev["workflow_id"]) if phase.phase_order == 1
            )

        with TestClient(create_app()) as client:
            pages = [
                "/",
                "/namespaces",
                "/namespaces/new",
                "/tasks",
                f"/phases?namespace_id={dev['id']}",
                f"/phases?namespace_id={qa['id']}",
                f"/phase/{dev_phase.id}?namespace_id={dev['id']}",
                "/workflows",
                f"/task/{TASK_KEY}?namespace_id={dev['id']}",
                f"/task/{TASK_KEY}?namespace_id={qa['id']}",
                f"/agents?namespace_id={dev['id']}",
            ]
            rendered_pages = []
            for path in pages:
                response = client.get(path)
                assert response.status_code == 200, path
                rendered_pages.append(response.text)
    finally:
        reset_engine()
        config.get_settings.cache_clear()

    rendered = "\n".join(rendered_pages)
    assert "hermes" not in rendered.casefold()
    assert "Supervisor" not in rendered
    assert "sdlc-" not in rendered.casefold()
    assert "sdlc-business-tech-v1" not in rendered
    assert "sdlc-orchestrator" not in rendered
    assert "Default Namespace" not in rendered
    assert DEFAULT_DEMO_WORKFLOW_NAME in rendered
    assert QA_WORKFLOW_NAME in rendered
    assert "workflow-dev" in rendered
    assert "workflow-qa" in rendered
    assert "RUN-42" in rendered
