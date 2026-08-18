"""FSM verdict labels stay aligned with the Wizard contract."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.wizard]

from project_workflow.domain.fsm import PhaseFSM
from project_workflow.wizard.types import VERDICT_LABELS

CORE_VERDICT_LABELS = VERDICT_LABELS


class TestVerdictLabels:
    def test_all_contract_verdicts_have_labels(self):
        for v in ("pass", "partial", "blocked", "rollback", "delegate"):
            assert v in VERDICT_LABELS
            assert v in CORE_VERDICT_LABELS


class TestFSMAcceptsPartial:
    def test_partial_stays_in_progress(self):
        fsm = PhaseFSM("in_progress")
        assert fsm.apply_verdict("partial") == "in_progress"
