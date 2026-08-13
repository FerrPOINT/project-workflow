"""Strict public contracts for workflow-template/v2 and phase-report/v2."""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ActionStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class CheckStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class Decision(str, Enum):
    PASS = "PASS"
    INCOMPLETE = "INCOMPLETE"
    BLOCKED = "BLOCKED"
    ROLLBACK = "ROLLBACK"
    CHANGE_REQUEST = "CHANGE_REQUEST"
    ABORT = "ABORT"


class ActorV2(StrictModel):
    identity: str = Field(min_length=1)
    role: str = Field(min_length=1)
    type: Literal["agent", "human"]


class ActionResultV2(StrictModel):
    instructionId: str = Field(min_length=1)
    status: ActionStatus
    usedTools: list[str] = Field(min_length=1)
    outputRefs: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class CheckResultV2(StrictModel):
    checkId: str = Field(min_length=1)
    status: CheckStatus
    evidenceIds: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    notApplicableReason: str | None = None
    tailoringApprovalRef: str | None = None


class EvidenceV2(StrictModel):
    evidenceId: str = Field(min_length=1)
    requirementId: str = Field(min_length=1)
    checkIds: list[str] = Field(min_length=1)
    type: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    subjectRevision: str = Field(min_length=1)
    producerIdentity: str = Field(min_length=1)
    observedAt: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("observedAt")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observedAt must include a timezone")
        return value


class ApprovalV2(StrictModel):
    approvalId: str = Field(min_length=1)
    role: str = Field(min_length=1)
    identity: str = Field(min_length=1)
    actorType: Literal["human"]
    decision: Literal["approved", "rejected"]
    subjectRevision: str = Field(min_length=1)
    approvedAt: datetime
    externalRef: str = Field(min_length=1)

    @field_validator("approvedAt")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approvedAt must include a timezone")
        return value


class BlockerV2(StrictModel):
    code: str = Field(min_length=1)
    failureClass: str = Field(min_length=1)
    message: str = Field(min_length=1)
    externalDependency: bool = False


class PhaseReportV2(StrictModel):
    schemaVersion: Literal["phase-report/v2"]
    workflowVersion: Literal["agentic-sdlc-v2"]
    catalogRevision: str = Field(pattern=r"^[0-9a-f]{64}$")
    taskKey: str = Field(pattern=r"^AAT-[1-9][0-9]*$")
    runId: str = Field(min_length=1, max_length=128)
    phaseId: str = Field(pattern=r"^[CFBDX][0-9]{2}$")
    actor: ActorV2
    inputRevisions: dict[str, str]
    actionResults: list[ActionResultV2]
    checkResults: list[CheckResultV2]
    evidence: list[EvidenceV2]
    approvals: list[ApprovalV2] = Field(default_factory=list)
    blockers: list[BlockerV2] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_secret_patterns(self) -> PhaseReportV2:
        serialized = json.dumps(self.model_dump(mode="json"), ensure_ascii=False)
        patterns = (
            r"glpat-[A-Za-z0-9_-]{8,}",
            r"(?i)private-token\s*[:=]",
            r"(?i)authorization\s*[:=]\s*bearer",
            r"(?i)openrouter_api_key\s*[:=]",
            r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----",
            r"(?i)password\s*=\s*[^*\s]+",
        )
        for pattern in patterns:
            if re.search(pattern, serialized):
                raise ValueError("phase report contains a credential-like value")
        return self


class PhaseDecisionV2(StrictModel):
    schemaVersion: Literal["phase-decision/v2"] = "phase-decision/v2"
    decision: Decision
    receiptId: str
    currentPhase: str
    nextPhase: str | None
    rollbackTarget: str | None
    missingChecks: list[str] = Field(default_factory=list)
    invalidEvidence: list[str] = Field(default_factory=list)
    invalidatedRevisions: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
