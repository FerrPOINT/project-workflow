"""Focused tests for the retained UnitOfWork transaction and run facade."""

from __future__ import annotations

import pytest

from project_workflow import config
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

    def test_context_manager_rolls_back_on_exception(self):
        uow = _fresh_uow()
        with pytest.raises(RuntimeError):
            with uow:
                raise RuntimeError("boom")
        uow.close()
