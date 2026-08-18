"""Coverage gap tests for Wizard context."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from project_workflow.wizard.context import WizardContextBuilder
from project_workflow.wizard.models import Phase

pytestmark = [pytest.mark.wizard]


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
        assert builder._phase_status_lookup() == {"1": "current"}

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
