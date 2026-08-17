from __future__ import annotations

import pytest
from pydantic import ValidationError

from project_workflow.v2.schemas import PhaseReportV2


def minimal_payload() -> dict:
    return {
        "schemaVersion": "phase-report/v2",
        "workflowVersion": "agentic-sdlc-v2",
        "catalogRevision": "0" * 64,
        "taskKey": "AAT-1",
        "attemptId": "attempt-1",
        "runId": "run-1",
        "phaseId": "C01",
        "actor": {"identity": "hermes", "role": "Business Analyst", "type": "agent"},
        "inputRevisions": {},
        "actionResults": [],
        "checkResults": [],
        "evidence": [],
        "approvals": [],
        "blockers": [],
    }


@pytest.mark.parametrize("field", ["result", "verdict", "nextPhase", "rollbackTarget"])
def test_agent_cannot_submit_authoritative_decision_fields(field):
    payload = minimal_payload()
    payload[field] = "PASS"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PhaseReportV2.model_validate(payload)


def test_dates_require_real_iso_timezone():
    payload = minimal_payload()
    payload["evidence"] = [
        {
            "evidenceId": "ev-1",
            "requirementId": "c01-e01-primary",
            "checkIds": ["c01-evidence-verified"],
            "type": "document",
            "uri": "evidence.json",
            "sha256": "0" * 64,
            "subjectRevision": "rev",
            "producerIdentity": "hermes",
            "observedAt": "2026-08-13 12:00:00",
            "metadata": {},
        }
    ]

    with pytest.raises(ValidationError, match="timezone"):
        PhaseReportV2.model_validate(payload)


def test_secret_patterns_are_rejected():
    payload = minimal_payload()
    payload["blockers"] = [
        {
            "code": "bad-log",
            "failureClass": "verification-failed",
            "message": "Authorization: Bearer should-not-be-here",
        }
    ]

    with pytest.raises(ValidationError, match="credential-like"):
        PhaseReportV2.model_validate(payload)
