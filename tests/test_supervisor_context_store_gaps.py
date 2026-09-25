"""Coverage gap tests for supervisor context and store."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.supervisor]

from project_workflow.supervisor.context import SupervisorContextBuilder
from project_workflow.supervisor.models import Phase


class TestSupervisorContextBuilder:
    def _phase(self, code="1", name="One", id=1, parallel_with=None, rollback_target=None):
        return Phase(
            code=code,
            name=name,
            id=id,
            description="",
            instructions=[],
            checks=[],
            evidence=[],
            execution_type="sync",
            parallel_with=parallel_with,
            rollback_target=rollback_target,
        )

    def test_phase_by_id_none(self):
        builder = SupervisorContextBuilder(all_phases=[])
        assert builder._phase_by_id(None) is None

    def test_phase_by_id_no_match(self):
        builder = SupervisorContextBuilder(all_phases=[self._phase(id=1)])
        assert builder._phase_by_id(99) is None

    def test_phase_status_lookup_no_phase(self):
        uow = MagicMock()
        uow.get_task_history.return_value = [{"phase_id": 99, "status": "done"}]
        builder = SupervisorContextBuilder(
            uow=uow,
            task={"id": 1, "status": "active", "current_phase": "1"},
            all_phases=[self._phase(id=1)],
            current_phase="1",
        )
        statuses = builder._phase_status_lookup()
        assert statuses == {"1": "current"}

    def test_phase_history_skips_unknown_phase(self):
        uow = MagicMock()
        uow.get_task_history.return_value = [{"phase_id": 99, "status": "done", "completed_at": "2025-01-01"}]
        builder = SupervisorContextBuilder(uow=uow, task={"id": 1}, all_phases=[self._phase(id=1)])
        assert builder._build_phase_history() == []

    def test_recent_verdicts_dict_row(self):
        uow = MagicMock()
        uow.get_supervisor_runs.return_value = [
            {
                "phase_code": "1",
                "verdict": "pass",
                "blockers": [],
                "missing": [],
                "next_phase_code": None,
                "rollback_phase_code": None,
                "created_at": "2025-01-01",
            }
        ]
        builder = SupervisorContextBuilder(uow=uow, task={"id": 1}, all_phases=[])
        verdicts = builder._build_recent_verdicts()
        assert len(verdicts) == 1
        assert verdicts[0]["verdict"] == "PASS"

    def test_build_has_no_file_conversation_messages(self):
        uow = MagicMock()
        uow.get_task_history.return_value = []
        uow.get_supervisor_runs.return_value = []
        builder = SupervisorContextBuilder(
            uow=uow,
            task={"id": 1, "status": "active", "current_phase": "1"},
            project={"code": "PRJ", "name": "Project"},
            workflow={"id": 1, "name": "WF"},
            all_phases=[self._phase(id=1)],
            current_phase="1",
            task_key="PRJ-1",
        )
        result = builder.build()
        assert "messages" not in result

    def test_prompt_history_excludes_other_mode_cycle_and_phase(self):
        current = self._phase(code="DV-02", id=2)
        uow = MagicMock()
        uow.get_task_history.return_value = [
            {"phase_id": 2, "mode_id": 11, "cycle_number": 1, "status": "done", "completed_at": "now"},
            {"phase_id": 2, "mode_id": 11, "cycle_number": 0, "status": "done", "completed_at": "old"},
            {"phase_id": 2, "mode_id": 12, "cycle_number": 1, "status": "done", "completed_at": "mode"},
            {"phase_id": 1, "mode_id": 11, "cycle_number": 1, "status": "done", "completed_at": "phase"},
        ]
        uow.get_supervisor_runs.return_value = [
            {"phase_id": 2, "mode_id": 11, "cycle_number": 1, "verdict": "pass", "blockers": ["current"]},
            {"phase_id": 2, "mode_id": 11, "cycle_number": 0, "verdict": "blocked", "blockers": ["old-cycle"]},
            {"phase_id": 2, "mode_id": 12, "cycle_number": 1, "verdict": "blocked", "blockers": ["old-mode"]},
            {"phase_id": 1, "mode_id": 11, "cycle_number": 1, "verdict": "blocked", "blockers": ["old-phase"]},
        ]
        builder = SupervisorContextBuilder(
            uow=uow,
            task={
                "id": 7,
                "mode_id": 11,
                "mode_key": "rework",
                "cycle_number": 1,
                "status": "active",
                "current_phase": "DV-02",
            },
            all_phases=[current],
            current_phase="DV-02",
        )

        context = builder.build()

        assert context["phase_history"] == [
            {"phase_code": "DV-02", "phase_name": "One", "status": "done", "completed_at": "now"}
        ]
        assert [item["blockers"] for item in context["recent_verdicts"]] == [["current"]]
        assert context["workflow_path"] == [
            {
                "code": "DV-02",
                "name": "One",
                "status": "done",
                "parallel_with": None,
                "rollback_target": None,
            }
        ]
