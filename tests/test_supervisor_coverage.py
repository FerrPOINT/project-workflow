"""Coverage for live phase-contract helpers."""

from __future__ import annotations

import pytest

from project_workflow.supervisor import SupervisorEngine
from project_workflow.supervisor.models import Phase, PhaseCheck, PhaseEvidence
from project_workflow.supervisor.types import VERDICT_LABELS

pytestmark = [pytest.mark.supervisor]


class TestBuildChecklist:
    def _make_engine(self) -> SupervisorEngine:
        return SupervisorEngine("TASK-1")

    def test_deduplicates_and_preserves_order(self):
        engine = self._make_engine()
        phase = Phase(
            id=1,
            code="0",
            name="Test",
            checks=[PhaseCheck(description="  Run tests  ")],
            evidence=[PhaseEvidence(item="run tests"), PhaseEvidence(item="Attach report")],
        )

        assert engine._build_checklist(phase) == ["Run tests", "Attach report"]

    def test_skips_empty_items(self):
        engine = self._make_engine()
        phase = Phase(
            id=1,
            code="0",
            name="Test",
            checks=[PhaseCheck(description="")],
            evidence=[PhaseEvidence(item="  ")],
        )

        assert engine._build_checklist(phase) == []


def test_all_runtime_verdicts_have_labels():
    for verdict in ("pass", "partial", "blocked", "rollback", "delegate"):
        assert VERDICT_LABELS[verdict].isupper()
