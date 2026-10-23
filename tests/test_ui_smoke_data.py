"""Tests for neutral UI smoke data used by screenshots."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
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
        prepare_smoke_data()
        with SAUnitOfWork() as uow:
            namespaces = [namespace.to_dict() for namespace in uow.projects.list()]
            workflows = [workflow.to_dict() for workflow in uow.workflows.list()]
            phases = [phase.to_dict() for phase in uow.phases.list()]
            visible_text = "\n".join(
                f"{namespace.get('name', '')} {namespace.get('description', '')}" for namespace in namespaces
            )
            visible_text += "\n" + "\n".join(
                f"{workflow.get('name', '')} {workflow.get('description', '')}" for workflow in workflows
            )
            visible_text += "\n" + "\n".join(
                f"{phase.get('name', '')} {phase.get('description', '')}" for phase in phases
            )
            for phase in phases:
                if phase["id"] is None:
                    continue
                for instruction in uow.phase_instructions.list(int(phase["id"])):
                    visible_text += (
                        f"\n{instruction.get('description', '')} "
                        f"{' '.join(instruction.get('skills') or [])}"
                    )
                visible_text += "\n" + "\n".join(
                    str(check.get("description") or "") for check in uow.phase_checks.list(int(phase["id"]))
                )
                visible_text += "\n" + "\n".join(
                    str(evidence.get("description") or "")
                    for evidence in uow.phase_evidence_requirements.list(int(phase["id"]))
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
    assert re.search(r"\bflow-[a-z0-9_-]+", visible_text, re.IGNORECASE) is None
    assert "launch-" not in visible_text.casefold()
    assert "smoke" not in visible_text.casefold()
    assert "project-workflow" not in visible_text.casefold()
    assert "relevanter" not in visible_text.casefold()
    assert "бизнес" not in visible_text.casefold()
    assert "duedate" not in visible_text.casefold()
    assert re.search(r"\bBusiness\b", visible_text, re.IGNORECASE) is None
    assert re.search(r"\bTech\b", visible_text, re.IGNORECASE) is None
    assert re.search(r"\bPR\b", visible_text) is None
    assert "maintainer" not in visible_text.casefold()
    assert "sdlc-business-tech-v1" not in visible_text
    assert DEFAULT_DEMO_WORKFLOW_NAME in visible_text
    assert QA_WORKFLOW_NAME in visible_text
    assert dev["name"] == "Разработка"
    assert qa["name"] == "Проверка качества"
    assert dev["workflow_id"] != qa["workflow_id"]
    assert len(TASK_SCENARIOS["workflow-dev"]) >= 12
    assert len(TASK_SCENARIOS["workflow-qa"]) >= 12
    assert len(dev_tasks) == len(TASK_SCENARIOS["workflow-dev"])
    assert len(qa_tasks) == len(TASK_SCENARIOS["workflow-qa"])
    assert len(dev_tasks) >= 18
    assert len(qa_tasks) >= 18
    assert {task["status"] for task in dev_tasks} == {"active", "blocked", "done"}
    assert {task["status"] for task in qa_tasks} == {"active", "blocked", "done"}
    assert latest_verdicts == {"pass", "partial", "blocked", "delegate", "rollback"}
    assert dev["launch_profile"] == "run-dev"
    assert qa["launch_profile"] == "run-quality"
    assert dev_task is not None
    assert qa_task is not None
    assert dev_task.task_key == qa_task.task_key == TASK_KEY
    assert "orchestrator" not in visible_text
    assert "codex-operator" not in visible_text
    assert "task-record" in visible_text
    assert "source-check" in visible_text


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
            preview_keys = set(re.findall(r'data-task-key="([^"]+)"', dashboard.text))
            assert len(preview_keys) == min(8, len(dev_open_task_keys))
            assert preview_keys <= dev_open_task_keys
            assert f"Показано 8 из {len(dev_open_task_keys)}" in dashboard.text

            tasks_page = client.get(f"/tasks?namespace_id={dev['id']}")
            assert tasks_page.status_code == 200
            for task_key in dev_open_task_keys:
                assert task_key in tasks_page.text

            pages = [
                f"/?namespace_id={dev['id']}",
                "/namespaces",
                "/namespaces/new",
                "/tasks",
                f"/phases?namespace_id={dev['id']}",
                f"/phases?namespace_id={qa['id']}",
                f"/phase/{dev_phase.id}?namespace_id={dev['id']}",
                f"/instructions?phase_id={dev_phase.id}&namespace_id={dev['id']}",
                "/workflows",
                f"/task/{TASK_KEY}?namespace_id={dev['id']}",
                f"/task/{TASK_KEY}?namespace_id={qa['id']}",
                f"/namespaces?namespace_id={dev['id']}",
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
    # Framework assets contain platform identifiers, never smoke business data.
    assets = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/base"
    for asset in ("base-ui.css", "base-ui.js", "theme-preference.js"):
        rendered = rendered.replace((assets / asset).read_text(encoding="utf-8"), "")
    assert "hermes" not in rendered.casefold()
    class VisibleContent(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ignored = 0
            self.values = []

        def handle_starttag(self, tag, attrs):
            if tag in {"script", "style"}:
                self.ignored += 1
            if tag == "input":
                self.values.extend(value for name, value in attrs if name == "value" and value)

        def handle_endtag(self, tag):
            if tag in {"script", "style"}:
                self.ignored -= 1

        def handle_data(self, data):
            if not self.ignored:
                self.values.append(data)

    visible = VisibleContent()
    visible.feed(rendered)
    # Technical service keys and bridge configuration are not screenshot business content.
    assert "project-workflow" not in " ".join(visible.values).casefold()
    assert "relevanter" not in rendered.casefold()
    assert "бизнес" not in rendered.casefold()
    assert "duedate" not in rendered.casefold()
    assert re.search(r"\bBusiness\b", rendered, re.IGNORECASE) is None
    assert re.search(r"\bTech\b", rendered, re.IGNORECASE) is None
    assert "maintainer" not in rendered.casefold()
    assert "Supervisor" not in rendered
    assert "sdlc-" not in rendered.casefold()
    assert re.search(r"\bflow-[a-z0-9_-]+", rendered, re.IGNORECASE) is None
    assert "launch-" not in rendered.casefold()
    assert "smoke" not in rendered.casefold()
    assert "sdlc-business-tech-v1" not in rendered
    assert "sdlc-orchestrator" not in rendered
    assert "Default Namespace" not in rendered
    assert "orchestrator" not in rendered
    assert "codex-operator" not in rendered
    assert "Настройки выполнения" not in rendered
    assert 'id="namespaceLaunchProfile"' not in rendered
    assert DEFAULT_DEMO_WORKFLOW_NAME in rendered
    assert QA_WORKFLOW_NAME in rendered
    assert "workflow-dev" in rendered
    assert "workflow-qa" in rendered
    assert "RUN-42" in rendered
