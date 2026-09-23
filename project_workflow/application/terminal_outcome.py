"""Owner boundary between internal phase completion and Business lifecycle."""

from __future__ import annotations

INTERNAL_PHASE_COMPLETION_VERDICT = "PASS"
NON_TERMINAL_INTERNAL_VERDICTS = frozenset({"BLOCKED", "PARTIAL", "ROLLBACK", "DELEGATE"})
BUSINESS_STAGE_COMPLETION_OPERATION = "completeAssignedStage"
BUSINESS_STAGE_OUTCOMES = frozenset({"passed", "needs_rework"})

__all__ = [
    "BUSINESS_STAGE_COMPLETION_OPERATION",
    "BUSINESS_STAGE_OUTCOMES",
    "INTERNAL_PHASE_COMPLETION_VERDICT",
    "NON_TERMINAL_INTERNAL_VERDICTS",
]
