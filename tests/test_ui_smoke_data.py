"""Tests for neutral UI smoke data used by screenshots."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.application import state as app_state
from project_workflow.application.agent import AgentService
from project_workflow.application.project import ProjectService
from project_workflow.application.state import _AppState
from project_workflow.application.workflow import WorkflowService
from project_workflow.infrastructure.db.session import reset_engine
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from scripts.prepare_ui_smoke_data import (
    DEFAULT_DEMO_WORKFLOW_NAME,
    DEMO_AGENT_PROFILES,
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
            task_ids = [int(task["id"]) for task in [*dev_tasks, *qa_tasks]]
            latest_verdicts = {
                run.verdict for run in uow.step_history.latest_for_tasks(task_ids)
            }
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
    assert len(TASK_SCENARIOS["workflow-dev"]) >= 12
    assert len(TASK_SCENARIOS["workflow-qa"]) >= 12
    assert len(dev_tasks) == len(TASK_SCENARIOS["workflow-dev"])
    assert len(qa_tasks) == len(TASK_SCENARIOS["workflow-qa"])
    assert len(dev_tasks) >= 18
    assert len(qa_tasks) >= 18
    assert {task["status"] for task in dev_tasks} == {"active", "blocked", "done"}
    assert {task["status"] for task in qa_tasks} == {"active", "blocked", "done"}
    assert latest_verdicts == {"pass", "partial", "blocked", "delegate", "rollback"}
    expected_profiles = {
        str(profile["name"]): profile["hermes_profile"] for profile in DEMO_AGENT_PROFILES.values()
    }
    for agent in agents:
        if agent["name"] in expected_profiles:
            assert agent["hermes_profile"] == expected_profiles[agent["name"]]
    assert dev_task is not None
    assert qa_task is not None
    assert dev_task.task_key == qa_task.task_key == TASK_KEY
    assert {agent["name"] for agent in agents} >= {
        str(agent["name"]) for agent in DEMO_AGENT_PROFILES.values()
    }
    assert "orchestrator" not in visible_text
    assert "codex-operator" not in visible_text


def test_prepare_ui_smoke_data_resets_stale_visible_runtime_rows(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'ui-smoke.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.get_settings.cache_clear()
    reset_engine()

    try:
        prepare_smoke_data()
        with SAUnitOfWork() as uow:
            workflow = WorkflowService(uow).create_workflow(
                {"name": "Hermes stale workflow", "description": "old Hermes fixture"}
            )
            ProjectService(uow).create_project(
                {
                    "code": "OLD",
                    "name": "Hermes stale namespace",
                    "description": "old visible runtime",
                    "workflow_id": workflow["id"],
                    "theme_icon": "bug",
                    "theme_color": "#EF4444",
                    "cli_command": "workflow-old",
                    "key_prefixes": [],
                }
            )
            AgentService(uow).create_agent(
                {
                    "name": "Hermes stale agent",
                    "description": "old visible runtime",
                    "hermes_profile": "stale-profile",
                }
            )

        prepare_smoke_data()
        with SAUnitOfWork() as uow:
            namespaces = [namespace.to_dict() for namespace in uow.projects.list()]
            task_counts = {
                namespace["cli_command"]: len(uow.tasks.list_by_project(int(namespace["id"])))
                for namespace in namespaces
            }
            workflows = [workflow.to_dict() for workflow in uow.workflows.list()]
            agents = [agent.to_dict() for agent in uow.agents.list()]
            rendered_text = "\n".join(
                str(value)
                for row in [*namespaces, *workflows, *agents]
                for value in row.values()
                if value is not None
            )
    finally:
        reset_engine()
        config.get_settings.cache_clear()

    assert {namespace["cli_command"] for namespace in namespaces} == {"workflow-dev", "workflow-qa"}
    assert task_counts == {command: len(scenarios) for command, scenarios in TASK_SCENARIOS.items()}
    assert {workflow["name"] for workflow in workflows} == {DEFAULT_DEMO_WORKFLOW_NAME, QA_WORKFLOW_NAME}
    assert "hermes" not in rendered_text.casefold()
    assert "orchestrator" not in rendered_text
    assert "codex-operator" not in rendered_text


def test_prepare_ui_smoke_data_rejects_non_smoke_database_url(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'runtime.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.get_settings.cache_clear()
    reset_engine()

    try:
        with pytest.raises(RuntimeError, match="отдельную SQLite-базу"):
            prepare_smoke_data()
    finally:
        reset_engine()
        config.get_settings.cache_clear()


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
            dashboard = client.get(f"/?namespace_id={dev['id']}")
            assert dashboard.status_code == 200
            dev_open_task_keys = {
                str(scenario["key"])
                for scenario in TASK_SCENARIOS["workflow-dev"]
                if scenario["status"] != "done"
            }
            for task_key in dev_open_task_keys:
                assert task_key in dashboard.text

            pages = [
                f"/?namespace_id={dev['id']}",
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
    assert "orchestrator" not in rendered
    assert "codex-operator" not in rendered
    assert "Координатор" in rendered
    assert "Ревьюер" in rendered
    assert DEFAULT_DEMO_WORKFLOW_NAME in rendered
    assert QA_WORKFLOW_NAME in rendered
    assert "workflow-dev" in rendered
    assert "workflow-qa" in rendered
    assert "RUN-42" in rendered
