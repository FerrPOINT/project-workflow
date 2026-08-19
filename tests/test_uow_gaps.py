"""Coverage gap tests for infrastructure.db.uow edge cases."""

from __future__ import annotations

import pytest

from project_workflow import config
from project_workflow.infrastructure.db.schema import ensure_phase_catalog, mark_catalog_not_ensured
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
            default_wf = uow.workflows.ensure_default_exists()
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

    def test_create_phase_without_workflow_id_is_rejected(self):
        uow = _fresh_uow()
        with pytest.raises(ValueError, match="workflow_id"):
            uow.create_phase(
                {
                    "code": "GAP-AUTO",
                    "name": "Auto WF Phase",
                    "phase_order": 9001,
                }
            )
        uow.close()

    def test_create_phase_without_code_generates_code(self):
        uow = _fresh_uow()
        workflow_id = uow.workflows.ensure_default_exists().id
        phase_id = uow.create_phase(
            {
                "workflow_id": workflow_id,
                "name": "No Code Phase",
                "phase_order": 9002,
            }
        )
        phase = uow.phases.get_by_id(phase_id)
        assert phase is not None
        assert phase.code
        uow.close()

    def test_create_instruction_with_phase_code(self):
        uow = _fresh_uow()
        with uow:
            default_wf = uow.workflows.ensure_default_exists()
            uow.phases.create(
                {
                    "workflow_id": default_wf.id,
                    "code": "GAP-INST",
                    "name": "Instruction Phase",
                    "phase_order": 9003,
                }
            )
            uow.commit()
        instruction_id = uow.create_instruction(
            {
                "phase_id": "GAP-INST",
                "description": "step",
                "step_num": 1,
            }
        )
        assert isinstance(instruction_id, int)
        uow.close()

    def test_get_phase_by_code(self):
        uow = _fresh_uow()
        ensure_phase_catalog(uow)
        phase = uow.get_phase_by_code("1")
        assert phase is not None
        assert phase["code"] == "1"
        assert uow.get_phase_by_code("nonexistent-code-xyz") is None
        uow.close()

    def test_get_phase_by_string_id(self):
        uow = _fresh_uow()
        ensure_phase_catalog(uow)
        first = uow.get_phase("0.0a")
        assert first is not None
        assert first["code"] == "0.0a"
        uow.close()

    def test_get_phase_invalid_token(self):
        uow = _fresh_uow()
        ensure_phase_catalog(uow)
        assert uow.get_phase("not-a-code-or-id") is None
        uow.close()

    def test_delete_phase_by_code(self):
        uow = _fresh_uow()
        with uow:
            default_wf = uow.workflows.ensure_default_exists()
            uow.phases.create(
                {
                    "workflow_id": default_wf.id,
                    "code": "GAP-DEL",
                    "name": "Delete Phase",
                    "phase_order": 9004,
                }
            )
            uow.commit()
        uow.delete_phase("GAP-DEL")
        assert uow.phases.get_by_code("GAP-DEL") is None
        uow.close()

    def test_create_task_with_project_id_dict(self):
        uow = _fresh_uow()
        with uow:
            default_wf = uow.workflows.ensure_default_exists()
            project_id = uow.projects.create(
                {"code": "DICT", "name": "Dict", "workflow_id": default_wf.id}
            )
            uow.commit()
        task_id = uow.create_task(
            {
                "project_id": {"id": project_id},
                "task_key": "DICT-1",
                "title": "t",
                "status": "active",
            }
        )
        task = uow.tasks.get_by_id(task_id)
        assert task is not None
        assert task.project_id == project_id
        uow.close()

    def test_init_bootstraps_only_default_catalog(self, monkeypatch):
        url = config.get_settings().DATABASE_URL
        mark_catalog_not_ensured(url)
        uow = SAUnitOfWork(url)
        uow.init()
        projects = list(uow.projects.list())
        workflows = list(uow.workflows.list())
        assert [project.code for project in projects] == ["TASK"]
        assert [workflow.name for workflow in workflows] == ["Default Workflow"]
        assert len(uow.phases.list(workflow_id=workflows[0].id)) == 27
        uow.close()

    def test_context_manager_rolls_back_on_exception(self):
        uow = _fresh_uow()
        with pytest.raises(RuntimeError):
            with uow:
                raise RuntimeError("boom")
        uow.close()
