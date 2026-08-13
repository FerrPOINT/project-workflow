"""Read-only dashboard projections for agentic-sdlc-v2 runs."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select

from project_workflow.infrastructure.db.models import (
    EvidenceVerificationReceiptV2,
    HumanApprovalV2,
    PhaseAttemptV2,
    WorkflowRunV2,
)
from project_workflow.infrastructure.db.session import get_session
from project_workflow.v2.catalog import load_default_catalog


def load_v2_runs() -> list[dict[str, Any]]:
    catalog = load_default_catalog()
    with get_session() as session:
        count_rows = session.execute(
            select(PhaseAttemptV2.workflow_run_id, func.count(PhaseAttemptV2.id)).group_by(
                PhaseAttemptV2.workflow_run_id
            )
        ).all()
        counts: dict[int, int] = {int(run_id): int(count) for run_id, count in count_rows}
        runs = session.scalars(select(WorkflowRunV2).order_by(WorkflowRunV2.updated_at.desc())).all()
        rows: list[dict[str, Any]] = []
        for run in runs:
            path = catalog.path(run.profile)
            current_index = path.index(run.current_phase)
            completed = current_index + (1 if run.status == "done" else 0)
            phase = catalog.phase(run.current_phase)
            rows.append(
                {
                    "taskKey": run.task_key,
                    "profile": run.profile,
                    "status": run.status,
                    "currentPhase": run.current_phase,
                    "currentPhaseName": phase["name"],
                    "completed": completed,
                    "total": len(path),
                    "progress": round(completed / len(path) * 100),
                    "lastDecision": run.last_decision,
                    "attempts": int(counts.get(run.id, 0)),
                    "catalogRevision": run.catalog_revision,
                    "updatedAt": run.updated_at.isoformat() if run.updated_at else None,
                }
            )
        return rows


def load_v2_run(task_key: str) -> dict[str, Any] | None:
    catalog = load_default_catalog()
    with get_session() as session:
        run = session.scalar(select(WorkflowRunV2).where(WorkflowRunV2.task_key == task_key))
        if run is None:
            return None
        attempts = session.scalars(
            select(PhaseAttemptV2)
            .where(PhaseAttemptV2.workflow_run_id == run.id)
            .order_by(PhaseAttemptV2.id)
        ).all()
        attempt_ids = [item.id for item in attempts]
        receipt_rows = (
            session.scalars(
                select(EvidenceVerificationReceiptV2)
                .where(EvidenceVerificationReceiptV2.attempt_id.in_(attempt_ids))
                .order_by(EvidenceVerificationReceiptV2.id)
            ).all()
            if attempt_ids
            else []
        )
        receipts: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for receipt in receipt_rows:
            receipts[receipt.attempt_id].append(
                {
                    "evidenceId": receipt.evidence_id,
                    "verifierType": receipt.verifier_type,
                    "status": receipt.status,
                    "details": json.loads(receipt.details_json),
                }
            )
        approvals = session.scalars(
            select(HumanApprovalV2)
            .where(HumanApprovalV2.workflow_run_id == run.id)
            .order_by(HumanApprovalV2.id)
        ).all()
        path = catalog.path(run.profile)
        current_index = path.index(run.current_phase)
        passed_phases = {item.phase_id for item in attempts if item.decision == "PASS"}
        path_rows = []
        for index, phase_id in enumerate(path):
            phase = catalog.phase(phase_id)
            if phase_id in passed_phases:
                state = "passed"
            elif index == current_index and run.status == "active":
                state = "current"
            elif index <= current_index and run.status in {"done", "aborted"}:
                state = run.status
            else:
                state = "pending"
            path_rows.append(
                {
                    "phaseId": phase_id,
                    "name": phase["name"],
                    "ownerRole": phase["ownerRole"],
                    "state": state,
                    "isGate": bool(phase.get("approvalRule")),
                }
            )
        return {
            "taskKey": run.task_key,
            "profile": run.profile,
            "status": run.status,
            "currentPhase": run.current_phase,
            "lastDecision": run.last_decision,
            "catalogRevision": run.catalog_revision,
            "workflowVersion": run.workflow_version,
            "path": path_rows,
            "attempts": [
                {
                    "phaseId": item.phase_id,
                    "submissionId": item.submission_id,
                    "decision": item.decision,
                    "receiptId": item.receipt_id,
                    "createdAt": item.created_at.isoformat() if item.created_at else None,
                    "verificationReceipts": receipts[item.id],
                }
                for item in attempts
            ],
            "approvals": [
                {
                    "phaseId": item.phase_id,
                    "role": item.role,
                    "identity": item.identity,
                    "decision": item.decision,
                    "subjectRevision": item.subject_revision,
                    "externalRef": item.external_ref,
                    "approvedAt": item.approved_at.isoformat(),
                }
                for item in approvals
            ],
        }
