"""Coverage gap tests for supervisor context and store."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.supervisor]

from project_workflow.supervisor.context import SupervisorContextBuilder
from project_workflow.supervisor.models import Phase


class TestSupervisorContextBuilder:
    def _phase(
        self,
        code="1",
        name="One",
        id=1,
        parallel_with_phase_code=None,
        rollback_target_phase_code=None,
    ):
        return Phase(
            code=code,
            name=name,
            id=id,
            description="",
            instructions=[],
            checks=[],
            evidence=[],
            execution_type="sync",
            parallel_with_phase_code=parallel_with_phase_code,
            rollback_target_phase_code=rollback_target_phase_code,
        )

    def test_phase_by_id_none(self):
        builder = SupervisorContextBuilder(all_phases=[])
        assert builder._phase_by_id(None) is None

    def test_phase_by_id_no_match(self):
        builder = SupervisorContextBuilder(all_phases=[self._phase(id=1)])
        assert builder._phase_by_id(99) is None

    def test_phase_status_lookup_no_phase(self):
        uow = MagicMock()
        uow.list_phase_events.return_value = [{"phase_id": 99, "event_type": "completed"}]
        builder = SupervisorContextBuilder(
            uow=uow,
            task={"id": 1, "status": "active", "current_phase_id": 1},
            all_phases=[self._phase(id=1)],
            current_phase_code="1",
        )
        with pytest.raises(ValueError, match="неизвестную фазу"):
            builder._phase_status_lookup()

    def test_phase_history_skips_unknown_phase(self):
        uow = MagicMock()
        uow.list_phase_events.return_value = [
            {"phase_id": 99, "event_type": "completed", "occurred_at": "2025-01-01"}
        ]
        builder = SupervisorContextBuilder(uow=uow, task={"id": 1}, all_phases=[self._phase(id=1)])
        with pytest.raises(ValueError, match="неизвестную фазу"):
            builder._build_phase_history()

    def test_recent_verdicts_dict_row(self):
        uow = MagicMock()
        uow.list_step_history.return_value = [
            {
                "phase_id": 1,
                "verdict": "pass",
                "blocker_messages": [],
                "missing_item_ids": [],
                "next_phase_id": 2,
                "rollback_phase_id": None,
                "supervisor_response": {"message": "accepted"},
                "created_at": "2025-01-01",
            }
        ]
        builder = SupervisorContextBuilder(
            uow=uow,
            task={"id": 1},
            all_phases=[self._phase(code="1", id=1), self._phase(code="2", id=2)],
        )
        verdicts = builder._build_recent_verdicts()
        assert len(verdicts) == 1
        assert verdicts[0]["verdict"] == "PASS"
        assert verdicts[0]["phase_code"] == "1"
        assert verdicts[0]["next_phase_code"] == "2"
        assert verdicts[0]["message"] == "accepted"

    def test_build_has_no_file_conversation_messages(self):
        uow = MagicMock()
        uow.list_phase_events.return_value = [
            {"phase_id": 1, "event_type": "entered", "occurred_at": "2025-01-01"}
        ]
        uow.list_step_history.return_value = []
        builder = SupervisorContextBuilder(
            uow=uow,
            task={"id": 1, "status": "active", "current_phase_id": 1},
            project={"code": "PRJ", "name": "Project"},
            workflow={"id": 1, "name": "WF"},
            all_phases=[self._phase(id=1)],
            current_phase_code="1",
            task_key="PRJ-1",
        )
        result = builder.build()
        assert "messages" not in result
