"""RED-GREEN for the refined verdict contract: pass/soft_fail/hard_fail/blocked/rollback/delegate."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.wizard]

from project_workflow.domain.fsm import PhaseFSM
from project_workflow.wizard.checks import build_verdict_message, determine_verdict
from project_workflow.wizard.core import VERDICT_LABELS as CORE_VERDICT_LABELS
from project_workflow.wizard.core import format_result
from project_workflow.wizard.types import VERDICT_LABELS, PhaseContract, WizardAssessment


class TestDeterministicVerdictContract:
    def test_pass_when_nothing_missing(self):
        assert determine_verdict(covered=["c1"], missing=[], blockers=[], report="done") == "pass"

    def test_soft_fail_when_covered_but_missing(self):
        assert determine_verdict(covered=["c1"], missing=["m1"], blockers=[], report="did part") == "soft_fail"

    def test_hard_fail_when_nothing_covered(self):
        assert determine_verdict(covered=[], missing=["m1"], blockers=[], report="nothing") == "hard_fail"

    def test_blocked_takes_precedence_over_missing(self):
        assert determine_verdict(covered=[], missing=["m1"], blockers=["b1"], report="blocked") == "blocked"

    def test_rollback_when_target_and_signal(self):
        assert (
            determine_verdict(covered=[], missing=["m1"], blockers=[], report="rollback", rollback_target="0")
            == "rollback"
        )

    def test_rollback_when_blockers_and_target(self):
        assert (
            determine_verdict(covered=["c1"], missing=["m1"], blockers=["b1"], report="x", rollback_target="0")
            == "rollback"
        )

    def test_delegate_verdict_unchanged(self):
        assert (
            determine_verdict(covered=[], missing=["m1"], blockers=[], report="delegate this", is_delegated=True)
            == "delegate"
        )


class TestVerdictLabels:
    def test_all_contract_verdicts_have_labels(self):
        for v in ("pass", "soft_fail", "hard_fail", "blocked", "rollback", "delegate"):
            assert v in VERDICT_LABELS
            assert v in CORE_VERDICT_LABELS


class TestVerdictMessages:
    def test_soft_fail_message(self):
        msg = build_verdict_message("soft_fail", "Plan", "1", [], ["missing item"], None, None)
        assert "Incomplete" in msg
        assert "missing item" in msg

    def test_hard_fail_message(self):
        msg = build_verdict_message("hard_fail", "Plan", "1", [], ["missing item"], None, None)
        assert "Cannot proceed" in msg or "missing item" in msg


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
