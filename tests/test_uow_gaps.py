"""Focused tests for the retained UnitOfWork transaction and run facade."""

from __future__ import annotations

import pytest

from project_workflow import config
from project_workflow.infrastructure.db.uow import SAUnitOfWork

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

    def test_create_supervisor_run_with_positional_dict(self):
        uow = _fresh_uow()
        with uow:
            default_wf = uow.workflows.ensure_default_exists("Default Workflow")
            project_id = uow.projects.create(
                {"code": "RUN", "name": "Run", "workflow_id": default_wf.id}
            )
            phase_id = uow.phases.create(
                {
                    "workflow_id": default_wf.id,
                    "code": "GAP-RUN",
                    "name": "Run Phase",
                    "phase_order": 9000,
                }
            )
            task_id = uow.tasks.create(
                {
                    "project_id": project_id,
                    "task_key": "RUN-1",
                    "title": "t",
                    "status": "active",
                    "current_phase": "-1",
                }
            )
            uow.commit()

        run_id = uow.create_supervisor_run(
            {
                "task_id": task_id,
                "phase_id": phase_id,
                "verdict": "pass",
                "report": "r",
                "covered": [],
                "missing": [],
                "blockers": [],
                "response": {},
            }
        )
        assert isinstance(run_id, int)
        uow.close()

    def test_context_manager_rolls_back_on_exception(self):
        uow = _fresh_uow()
        with pytest.raises(RuntimeError):
            with uow:
                raise RuntimeError("boom")
        uow.close()
