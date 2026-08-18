"""Coverage gap tests for wizard context and store."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.wizard]

from project_workflow.wizard.context import WizardContextBuilder
from project_workflow.wizard.models import Phase


class TestWizardContextBuilder:
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
        builder = WizardContextBuilder(all_phases=[])
        assert builder._phase_by_id(None) is None

    def test_phase_by_id_no_match(self):
        builder = WizardContextBuilder(all_phases=[self._phase(id=1)])
        assert builder._phase_by_id(99) is None

    def test_phase_status_lookup_no_phase(self):
        uow = MagicMock()
        uow.get_task_history.return_value = [{"phase_id": 99, "status": "done"}]
        builder = WizardContextBuilder(
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
        builder = WizardContextBuilder(uow=uow, task={"id": 1}, all_phases=[self._phase(id=1)])
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
        builder = WizardContextBuilder(uow=uow, task={"id": 1}, all_phases=[])
        verdicts = builder._build_recent_verdicts()
        assert len(verdicts) == 1
        assert verdicts[0]["verdict"] == "PASS"

    def test_build_catches_conversation_exception(self):
        uow = MagicMock()
        uow.get_task_history.return_value = []
        uow.get_supervisor_runs.return_value = []
        builder = WizardContextBuilder(
            uow=uow,
            task={"id": 1, "status": "active", "current_phase": "1"},
            project={"code": "PRJ", "name": "Project"},
            workflow={"id": 1, "name": "WF"},
            all_phases=[self._phase(id=1)],
            current_phase="1",
            task_key="PRJ-1",
        )
        with pytest.MonkeyPatch().context() as mp:
            import project_workflow.infrastructure.conversation as convo

            mp.setattr(convo, "get_messages", lambda *a, **kw: (_ for _ in ()).throw(OSError("boom")))
            result = builder.build()
        assert result["messages"] == []
