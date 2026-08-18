"""RED-GREEN for the refined verdict contract: pass/soft_fail/hard_fail/blocked/rollback/delegate."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.wizard]

from project_workflow.domain.fsm import PhaseFSM
from project_workflow.wizard.core import format_result
from project_workflow.wizard.types import VERDICT_LABELS, PhaseContract, WizardAssessment

CORE_VERDICT_LABELS = VERDICT_LABELS


class TestVerdictLabels:
    def test_all_contract_verdicts_have_labels(self):
        for v in ("pass", "soft_fail", "hard_fail", "blocked", "rollback", "delegate"):
            assert v in VERDICT_LABELS
            assert v in CORE_VERDICT_LABELS


class TestFSMAcceptsNewVerdicts:
    def test_soft_fail_and_hard_fail_stay_in_progress(self):
        fsm = PhaseFSM("in_progress")
        assert fsm.apply_verdict("soft_fail") == "in_progress"
        assert fsm.apply_verdict("hard_fail") == "in_progress"


class TestFormatResult:
    def _assessment(self, verdict: str, covered: list[str], missing: list[str]) -> WizardAssessment:
        return WizardAssessment(
            task_key="T-1",
            phase_code="1",
            phase_name="Plan",
            verdict=verdict,
            covered=covered,
            missing=missing,
            blockers=[],
            instructions=["i1"],
            required_checks=["c1"],
            required_evidence=["e1"],
            next_phase="2",
            next_phase_name="Implement",
            next_phase_contract=PhaseContract(phase_code="2", phase_name="Implement"),
        )

    def test_soft_fail_format(self):
        out = format_result(self._assessment("soft_fail", ["c1"], ["m1"]).to_result_dict())
        assert "Чекапы:" in out
        assert "m1" in out
        assert "Ты сделал часть" not in out

    def test_hard_fail_format(self):
        out = format_result(self._assessment("hard_fail", [], ["m1"]).to_result_dict())
        assert "Чекапы:" in out
        assert "Доказательства:" in out
