"""Focused tests for the retained UnitOfWork transaction and run facade."""

from __future__ import annotations

import pytest

from project_workflow import config
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._db_helpers import phase_by_code

pytestmark = [pytest.mark.ui]


def _fresh_uow():
    url = config.get_settings().DATABASE_URL
    return SAUnitOfWork(url)


class TestUowEdgeCases:
    def test_uow_init_with_none_uses_config_url(self, monkeypatch):
        url = config.get_settings().DATABASE_URL
        monkeypatch.setenv("DATABASE_URL", url)
        uow = SAUnitOfWork(None)
        assert uow._session is not None
        uow.close()

    def test_record_step_uses_keyword_only_contract(self):
        uow = _fresh_uow()
        with uow:
            project = uow.projects.get_by_code(config.DEFAULT_PROJECT_CODE)
            phase = phase_by_code(uow, "1.INTAKE")
            assert project is not None and phase is not None
            task_id = uow.tasks.create(
                {
                    "project_id": project.id,
                    "workflow_id": project.workflow_id,
                    "task_key": "RUN-UOW-1",
                    "title": "t",
                    "status": "active",
                    "current_phase_id": phase.id,
                }
            )
            uow.commit()

        run_id = uow.record_step(
            task_id=task_id,
            phase_id=phase.id,
            verdict="pass",
            worker_report="r",
            covered_item_ids=[],
            missing_item_ids=[],
            blocker_messages=[],
            evaluation_snapshot={},
            supervisor_response={},
        )
        assert isinstance(run_id, int)
        uow.close()

    def test_task_repository_requires_explicit_workflow_id(self):
        uow = _fresh_uow()
        project = uow.projects.get_by_code(config.DEFAULT_PROJECT_CODE)
        phase = phase_by_code(uow, "1.INTAKE")
        assert project is not None and phase is not None

        with pytest.raises(ValueError, match="workflow_id задачи"):
            uow.tasks.create(
                {
                    "project_id": project.id,
                    "task_key": "RUN-UOW-MISSING-WORKFLOW",
                    "current_phase_id": phase.id,
                }
            )

        uow.rollback()
        uow.close()

    def test_workflow_scoped_task_lookup_fails_closed_when_key_exists_in_multiple_namespaces(self):
        uow = _fresh_uow()
        workflow = uow.workflows.get_default()
        phase = phase_by_code(uow, "1.INTAKE")
        assert workflow is not None and workflow.id is not None and phase is not None
        first_project_id = uow.projects.create(
            {
                "workflow_id": workflow.id,
                "code": "DUPA",
                "name": "Duplicate A",
                "cli_command": "workflow-dup-a",
                "key_prefixes": [],
            }
        )
        second_project_id = uow.projects.create(
            {
                "workflow_id": workflow.id,
                "code": "DUPB",
                "name": "Duplicate B",
                "cli_command": "workflow-dup-b",
                "key_prefixes": [],
            }
        )
        task_ids = []
        for project_id in (first_project_id, second_project_id):
            task_ids.append(
                uow.tasks.create(
                    {
                        "project_id": project_id,
                        "workflow_id": workflow.id,
                        "task_key": "DUP-42",
                        "title": "Same external task",
                        "current_phase_id": phase.id,
                    }
                )
            )
        uow.commit()
        for task_id, report in zip(task_ids, ("first namespace report", "second namespace report"), strict=True):
            uow.record_step(
                task_id=task_id,
                phase_id=phase.id,
                verdict="pass",
                worker_report=report,
                covered_item_ids=[],
                missing_item_ids=[],
                blocker_messages=[],
                evaluation_snapshot={},
                supervisor_response={},
            )
        uow.commit()

        with pytest.raises(ConflictError, match="несколько неймспейсов"):
            uow.get_task_by_key("DUP-42", workflow_id=workflow.id)
        with pytest.raises(ConflictError, match="несколько неймспейсов"):
            uow.list_step_history(task_key="DUP-42", workflow_id=workflow.id, limit=None)

        assert uow.get_task_by_key("DUP-42", project_id=first_project_id)["project_id"] == first_project_id
        first_history = uow.list_step_history(task_key="DUP-42", project_id=first_project_id, limit=None)
        assert [entry["worker_report"] for entry in first_history] == ["first namespace report"]
        uow.close()

    def test_workflow_scoped_task_history_lookup_without_project_id_allows_unique_task_key(self):
        uow = _fresh_uow()
        workflow = uow.workflows.get_default()
        project = uow.projects.get_by_code(config.DEFAULT_PROJECT_CODE)
        phase = phase_by_code(uow, "1.INTAKE")
        assert workflow is not None and workflow.id is not None
        assert project is not None and project.id is not None and phase is not None
        task_id = uow.tasks.create(
            {
                "project_id": project.id,
                "workflow_id": workflow.id,
                "task_key": "UNIQUE-42",
                "title": "Unique external task",
                "current_phase_id": phase.id,
            }
        )
        uow.record_step(
            task_id=task_id,
            phase_id=phase.id,
            verdict="pass",
            worker_report="unique report",
            covered_item_ids=[],
            missing_item_ids=[],
            blocker_messages=[],
            evaluation_snapshot={},
            supervisor_response={},
        )
        uow.commit()

        history = uow.list_step_history(task_key="UNIQUE-42", workflow_id=workflow.id, limit=None)

        assert [entry["worker_report"] for entry in history] == ["unique report"]
        uow.close()

    def test_context_manager_rolls_back_on_exception(self):
        uow = _fresh_uow()
        with pytest.raises(RuntimeError):
            with uow:
                raise RuntimeError("boom")
        uow.close()
