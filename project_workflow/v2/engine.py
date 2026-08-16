"""Deterministic policy engine and atomic transition receipts for v2."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from project_workflow.infrastructure.db.models import (
    ArtifactDeploymentLinkV2,
    BaselineRevisionV2,
    EvidenceVerificationReceiptV2,
    HumanApprovalV2,
    PhaseAttemptV2,
    WorkflowRunV2,
)
from project_workflow.infrastructure.db.models import (
    WorkflowCatalogV2 as WorkflowCatalogRecordV2,
)

from .catalog import CatalogError, WorkflowCatalogV2, load_default_catalog
from .schemas import (
    ActionStatus,
    CheckStatus,
    Decision,
    PhaseDecisionV2,
    PhaseReportV2,
)
from .verifiers import VerificationContext, VerificationResult, VerifierRegistry


class V2PolicyError(ValueError):
    """Base error for rejected v2 operations."""


class ContractViolation(V2PolicyError):
    """A report does not conform to the current immutable phase contract."""


class ReplayConflict(V2PolicyError):
    """The same idempotency key was reused with different content."""


@dataclass(frozen=True)
class IdentityPolicy:
    agent_identities: frozenset[str]
    human_identities: frozenset[str]

    @classmethod
    def from_env(cls) -> IdentityPolicy:
        def values(name: str) -> frozenset[str]:
            return frozenset(item.strip() for item in os.getenv(name, "").split(",") if item.strip())

        return cls(
            agent_identities=values("PROJECT_WORKFLOW_AGENT_IDENTITIES"),
            human_identities=values("PROJECT_WORKFLOW_HUMAN_IDENTITIES"),
        )

    def permits(self, actor_type: str, identity: str) -> bool:
        allowed = self.agent_identities if actor_type == "agent" else self.human_identities
        return identity in allowed


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_EXPORTED_METADATA_KEYS = frozenset(
    {
        "artifactDigest",
        "builderIdentity",
        "deploymentId",
        "environment",
        "health",
        "gitSha",
        "linkedBugRunId",
        "linkedBugTaskKey",
        "mediaType",
        "mrIid",
        "pipelineId",
        "policyVersion",
        "previousStableDigest",
        "registryBaseUrl",
        "repository",
        "requiredJobs",
        "runtimeBaseUrl",
        "restoredDigest",
        "sourceSha",
        "state",
        "status",
        "successfulSamples",
        "sampleCount",
    }
)
_EXPORTED_URI_SCHEMES = frozenset(
    {
        "deployment",
        "file",
        "git",
        "gitlab",
        "gitlab-approval",
        "http",
        "https",
        "jira",
        "jira-comment",
        "observation",
        "oci",
        "runtime",
        "workflow",
    }
)
_URI_METADATA_KEYS = frozenset({"registryBaseUrl", "runtimeBaseUrl"})


def _sanitize_evidence_uri(value: str) -> str:
    """Remove request credentials and mutable query data from exported refs."""

    parsed = urlsplit(value)
    if parsed.scheme.lower() not in _EXPORTED_URI_SCHEMES:
        return "redacted:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None:
        hostname = f"{hostname}:{port}"
    return urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))


def _safe_evidence_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key in sorted(_EXPORTED_METADATA_KEYS & metadata.keys()):
        value = metadata[key]
        if key in _URI_METADATA_KEYS and isinstance(value, str):
            safe[key] = _sanitize_evidence_uri(value)
            continue
        if isinstance(value, str | int | float | bool) or value is None:
            if not isinstance(value, str) or len(value) <= 512:
                safe[key] = value
        elif (
            isinstance(value, list)
            and len(value) <= 100
            and all(isinstance(item, str) and len(item) <= 256 for item in value)
        ):
            safe[key] = value
    return safe


def _unique_ids(values: list[Any], attribute: str, label: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        key = getattr(value, attribute)
        if key in result:
            raise ContractViolation(f"duplicate {label} ID: {key}")
        result[key] = value
    return result


class PolicyEngineV2:
    def __init__(
        self,
        session: Session,
        catalog: WorkflowCatalogV2 | None = None,
        registry: VerifierRegistry | None = None,
        identity_policy: IdentityPolicy | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.session = session
        self.catalog = catalog or load_default_catalog()
        self.registry = registry or VerifierRegistry()
        self.identity_policy = identity_policy or IdentityPolicy.from_env()
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _persist_catalog(self) -> None:
        existing = self.session.scalar(
            select(WorkflowCatalogRecordV2).where(WorkflowCatalogRecordV2.catalog_revision == self.catalog.revision)
        )
        serialized = _canonical_json(self.catalog.payload)
        if existing:
            if existing.catalog_json != serialized:
                raise ContractViolation("stored catalog revision has different content")
            return
        self.session.add(
            WorkflowCatalogRecordV2(
                workflow_version=self.catalog.workflow_version,
                catalog_revision=self.catalog.revision,
                catalog_json=serialized,
            )
        )
        self.session.flush()

    def start(self, task_key: str, profile: str) -> dict[str, Any]:
        pattern = self.catalog.payload["policy"]["taskKeyPattern"]
        import re

        if not re.fullmatch(pattern, task_key):
            raise ContractViolation(f"task key does not match catalog policy: {task_key}")
        path = self.catalog.path(profile)
        self._persist_catalog()
        existing = self.session.scalar(select(WorkflowRunV2).where(WorkflowRunV2.task_key == task_key))
        if existing:
            if existing.profile != profile:
                raise ReplayConflict("task is already pinned to a different profile")
            return self._run_dict(existing)
        run = WorkflowRunV2(
            task_key=task_key,
            profile=profile,
            workflow_version=self.catalog.workflow_version,
            catalog_revision=self.catalog.revision,
            current_phase=path[0],
            status="active",
        )
        self.session.add(run)
        self.session.commit()
        return self._run_dict(run)

    def current(self, task_key: str) -> dict[str, Any]:
        run = self._get_run(task_key)
        catalog = self._catalog_for_run(run)
        latest_attempt = self.session.scalar(
            select(PhaseAttemptV2)
            .where(
                PhaseAttemptV2.workflow_run_id == run.id,
                PhaseAttemptV2.phase_id == run.current_phase,
            )
            .order_by(PhaseAttemptV2.id.desc())
        )
        revisions = {
            item.revision_kind: item.revision_value
            for item in self.session.scalars(
                select(BaselineRevisionV2)
                .where(
                    BaselineRevisionV2.workflow_run_id == run.id,
                    BaselineRevisionV2.invalidated_at.is_(None),
                )
                .order_by(BaselineRevisionV2.id)
            ).all()
        }
        if latest_attempt:
            revisions.update(json.loads(latest_attempt.report_json).get("inputRevisions", {}))
        return {
            **self._run_dict(run),
            "revisions": revisions,
            "contract": catalog.phase_contract(run.profile, run.current_phase) if run.status == "active" else None,
        }

    def history(self, task_key: str) -> list[dict[str, Any]]:
        run = self._get_run(task_key)
        attempts = self.session.scalars(
            select(PhaseAttemptV2).where(PhaseAttemptV2.workflow_run_id == run.id).order_by(PhaseAttemptV2.id)
        ).all()
        history: list[dict[str, Any]] = []
        for attempt in attempts:
            decision = json.loads(attempt.decision_json)
            history.append(
                {
                    **decision,
                    "submissionId": attempt.submission_id,
                    "phaseId": attempt.phase_id,
                    "createdAt": attempt.created_at.isoformat() if attempt.created_at else None,
                }
            )
        return history

    def evidence_export(self, task_key: str, *, schema_version: int = 1) -> dict[str, Any]:
        """Export verified audit facts without exposing raw reports or verifier secrets."""

        if schema_version not in {1, 2}:
            raise ContractViolation("evidence export schema version must be 1 or 2")
        run = self._get_run(task_key)
        catalog = self._catalog_for_run(run)
        attempts = self.session.scalars(
            select(PhaseAttemptV2)
            .where(PhaseAttemptV2.workflow_run_id == run.id)
            .order_by(PhaseAttemptV2.id)
        ).all()
        attempt_by_id = {attempt.id: attempt for attempt in attempts}
        receipts = self.session.scalars(
            select(EvidenceVerificationReceiptV2)
            .where(EvidenceVerificationReceiptV2.attempt_id.in_(attempt_by_id))
            .order_by(EvidenceVerificationReceiptV2.id)
        ).all()
        receipts_by_attempt: dict[int, list[EvidenceVerificationReceiptV2]] = {}
        for receipt in receipts:
            receipts_by_attempt.setdefault(receipt.attempt_id, []).append(receipt)

        verified_evidence: list[dict[str, Any]] = []
        exported_attempts: list[dict[str, Any]] = []
        for attempt in attempts:
            report = PhaseReportV2.model_validate_json(attempt.report_json)
            evidence_by_id = {item.evidenceId: item for item in report.evidence}
            attempt_receipts = receipts_by_attempt.get(attempt.id, [])
            for receipt in attempt_receipts:
                evidence = evidence_by_id.get(receipt.evidence_id)
                if receipt.status != "passed" or evidence is None:
                    continue
                verified_evidence.append(
                    {
                        "evidenceId": evidence.evidenceId,
                        "requirementId": evidence.requirementId,
                        "phaseId": attempt.phase_id,
                        "type": evidence.type,
                        "uri": _sanitize_evidence_uri(evidence.uri),
                        "sha256": evidence.sha256,
                        "subjectRevision": evidence.subjectRevision,
                        "producerIdentity": evidence.producerIdentity,
                        "observedAt": evidence.observedAt.isoformat(),
                        "metadata": _safe_evidence_metadata(evidence.metadata),
                        "controllerReceiptId": attempt.receipt_id,
                        "verificationReceiptId": f"evr-{receipt.id}",
                        "verifierType": receipt.verifier_type,
                        "verifiedAt": (
                            receipt.observed_at.isoformat()
                            if receipt.observed_at
                            else attempt.created_at.isoformat() if attempt.created_at else None
                        ),
                    }
                )
            exported_attempt = {
                "submissionId": attempt.submission_id,
                "phaseId": attempt.phase_id,
                "decision": attempt.decision,
                "reportSha256": attempt.report_sha256,
                "controllerReceiptId": attempt.receipt_id,
                "createdAt": attempt.created_at.isoformat() if attempt.created_at else None,
                "verificationReceipts": [
                    {
                        "verificationReceiptId": f"evr-{receipt.id}",
                        "evidenceId": receipt.evidence_id,
                        "verifierType": receipt.verifier_type,
                        "status": receipt.status,
                        "observedAt": receipt.observed_at.isoformat()
                        if receipt.observed_at
                        else None,
                    }
                    for receipt in attempt_receipts
                ],
            }
            if schema_version == 2:
                stored_decision = json.loads(attempt.decision_json)
                exported_attempt.update(
                    {
                        "nextPhase": stored_decision.get("nextPhase"),
                        "rollbackTarget": stored_decision.get("rollbackTarget"),
                    }
                )
            exported_attempts.append(exported_attempt)

        approvals = self.session.scalars(
            select(HumanApprovalV2)
            .where(HumanApprovalV2.workflow_run_id == run.id)
            .order_by(HumanApprovalV2.id)
        ).all()
        baselines = self.session.scalars(
            select(BaselineRevisionV2)
            .where(BaselineRevisionV2.workflow_run_id == run.id)
            .order_by(BaselineRevisionV2.id)
        ).all()
        deployments = self.session.scalars(
            select(ArtifactDeploymentLinkV2)
            .where(ArtifactDeploymentLinkV2.workflow_run_id == run.id)
            .order_by(ArtifactDeploymentLinkV2.id)
        ).all()

        exported = {
            "schemaVersion": f"evidence-export/v{schema_version}",
            "taskKey": run.task_key,
            "profile": run.profile,
            "workflowVersion": run.workflow_version,
            "catalogRevision": run.catalog_revision,
            "status": run.status,
            "currentPhase": run.current_phase,
            "attempts": exported_attempts,
            "verifiedEvidence": verified_evidence,
            "approvals": [
                {
                    "approvalId": item.approval_id,
                    "phaseId": item.phase_id,
                    "role": item.role,
                    "identity": item.identity,
                    "decision": item.decision,
                    "subjectRevision": item.subject_revision,
                    "externalRef": _sanitize_evidence_uri(item.external_ref),
                    "approvedAt": item.approved_at.isoformat(),
                    "controllerReceiptId": attempt_by_id[item.attempt_id].receipt_id,
                }
                for item in approvals
            ],
            "baselines": [
                {
                    "phaseId": item.phase_id,
                    "kind": item.revision_kind,
                    "value": item.revision_value,
                    "invalidatedAt": item.invalidated_at.isoformat() if item.invalidated_at else None,
                    "createdAt": item.created_at.isoformat() if item.created_at else None,
                }
                for item in baselines
            ],
            "deploymentLinks": [
                {
                    "artifactDigest": item.artifact_digest,
                    "environment": item.environment,
                    "deploymentId": item.deployment_id,
                    "status": item.status,
                    "evidenceId": item.evidence_id,
                    "createdAt": item.created_at.isoformat() if item.created_at else None,
                }
                for item in deployments
            ],
        }
        if schema_version == 2:
            exported["expectedPhasePath"] = list(catalog.path(run.profile))
        return exported

    def submit(self, report: PhaseReportV2 | dict[str, Any]) -> PhaseDecisionV2:
        if not isinstance(report, PhaseReportV2):
            report = PhaseReportV2.model_validate(report)
        report_payload = report.model_dump(mode="json")
        report_json = _canonical_json(report_payload)
        report_hash = hashlib.sha256(report_json.encode("utf-8")).hexdigest()
        run = self._get_run(report.taskKey, for_update=True)
        catalog = self._catalog_for_run(run)

        replay = self.session.scalar(
            select(PhaseAttemptV2).where(
                PhaseAttemptV2.workflow_run_id == run.id,
                PhaseAttemptV2.submission_id == report.runId,
                PhaseAttemptV2.phase_id == report.phaseId,
            )
        )
        if replay:
            if replay.report_sha256 != report_hash:
                raise ReplayConflict("same task/run/phase key was reused with different report content")
            return PhaseDecisionV2.model_validate_json(replay.decision_json)

        phase = catalog.phase(report.phaseId)
        self._validate_envelope(run, report, phase)
        self._validate_actor(run, report, phase)
        self._validate_revision_continuity(run, report, catalog)
        actions, checks, evidence = self._validate_contract_coverage(report, phase)
        verification_results, missing_checks, invalid_evidence = self._verify_evidence(
            run, report, phase, checks, evidence
        )
        approval_results, missing_approvals, rejected_approvals = self._verify_approvals(run, report, phase)
        verification_results.extend(approval_results)

        decision, failure_class, blockers = self._decide(
            report,
            phase,
            actions,
            checks,
            verification_results,
            missing_checks,
            invalid_evidence,
            missing_approvals,
            rejected_approvals,
        )
        old_phase = run.current_phase
        next_phase: str | None = None
        rollback_target: str | None = None
        invalidated: list[str] = []
        if decision == Decision.PASS:
            next_phase = catalog.next_phase(run.profile, old_phase)
            if next_phase is None:
                run.status = "done"
            else:
                run.current_phase = next_phase
        elif decision in {Decision.ROLLBACK, Decision.CHANGE_REQUEST}:
            if old_phase == "D31" and failure_class == "post-deploy-failure":
                rollback_target = "D31"
                run.status = "aborted"
            else:
                rollback_target = catalog.resolve_route(
                    run.profile, old_phase, failure_class or "phase-incomplete"
                )
                run.current_phase = rollback_target
                invalidated = self._invalidate_downstream(run, rollback_target, catalog)
        elif decision == Decision.ABORT:
            run.status = "aborted"
        run.last_decision = decision.value

        receipt_id = hashlib.sha256(
            f"{report.taskKey}\0{report.runId}\0{report.phaseId}\0{report_hash}".encode()
        ).hexdigest()
        result = PhaseDecisionV2(
            decision=decision,
            receiptId=receipt_id,
            currentPhase=old_phase,
            nextPhase=next_phase,
            rollbackTarget=rollback_target,
            missingChecks=sorted(set(missing_checks + missing_approvals)),
            invalidEvidence=sorted(set(invalid_evidence)),
            invalidatedRevisions=invalidated,
            blockers=blockers,
        )
        attempt = PhaseAttemptV2(
            workflow_run_id=run.id,
            submission_id=report.runId,
            phase_id=report.phaseId,
            report_sha256=report_hash,
            report_json=report_json,
            decision=decision.value,
            decision_json=result.model_dump_json(),
            receipt_id=receipt_id,
        )
        self.session.add(attempt)
        self.session.flush()
        self._persist_receipts(attempt, verification_results)
        self._persist_approvals(run, attempt, report, approval_results)
        if decision == Decision.PASS:
            self._persist_baseline_and_deployment(run, report, phase)
        self.session.commit()
        self.session.refresh(run)
        stored = self.session.scalar(select(PhaseAttemptV2).where(PhaseAttemptV2.receipt_id == receipt_id))
        if stored is None or run.last_decision != decision.value:
            raise RuntimeError("atomic transition readback failed")
        return result

    def _validate_envelope(self, run: WorkflowRunV2, report: PhaseReportV2, phase: dict[str, Any]) -> None:
        if run.status != "active":
            raise ContractViolation(f"task run is {run.status}")
        if report.workflowVersion != run.workflow_version:
            raise ContractViolation("workflow version mismatch")
        if report.catalogRevision != run.catalog_revision:
            raise ContractViolation("catalog revision mismatch")
        if report.phaseId != run.current_phase:
            raise ContractViolation(f"current phase is {run.current_phase}, not {report.phaseId}")
        if report.inputRevisions.get("catalogRevision") != run.catalog_revision:
            raise ContractViolation("inputRevisions.catalogRevision must match the pinned catalog")
        missing_bindings = [
            binding for binding in phase.get("requiredRevisionBindings", []) if not report.inputRevisions.get(binding)
        ]
        if missing_bindings:
            raise ContractViolation(f"required revision bindings are missing: {missing_bindings}")

    def _validate_revision_continuity(
        self, run: WorkflowRunV2, report: PhaseReportV2, catalog: WorkflowCatalogV2
    ) -> None:
        path = catalog.path(run.profile)
        current_index = path.index(report.phaseId)
        baselines = self.session.scalars(
            select(BaselineRevisionV2).where(
                BaselineRevisionV2.workflow_run_id == run.id,
                BaselineRevisionV2.invalidated_at.is_(None),
            )
        ).all()
        latest: dict[str, BaselineRevisionV2] = {}
        for baseline in baselines:
            if path.index(baseline.phase_id) < current_index:
                latest[baseline.revision_kind] = baseline
        for revision_kind in ("mrHeadSha", "artifactDigest"):
            current_baseline = latest.get(revision_kind)
            supplied = report.inputRevisions.get(revision_kind)
            if current_baseline and supplied and supplied != current_baseline.revision_value:
                raise ContractViolation(
                    f"{revision_kind} changed after approval/build: "
                    f"expected {current_baseline.revision_value}, got {supplied}"
                )

    def _validate_actor(self, run: WorkflowRunV2, report: PhaseReportV2, phase: dict[str, Any]) -> None:
        if report.actor.role != phase["ownerRole"]:
            raise ContractViolation(f"phase owner role is {phase['ownerRole']}, not {report.actor.role}")
        if not self.identity_policy.permits(report.actor.type, report.actor.identity):
            raise ContractViolation(f"actor identity is not allowlisted: {report.actor.identity}")
        if report.phaseId in {"D15", "D17"}:
            developer = self._last_pass_actor(run.id, "D03")
            if developer and developer == report.actor.identity:
                raise ContractViolation(f"{report.phaseId} must be independent from the D03 developer")

    def _last_pass_actor(self, run_id: int, phase_id: str) -> str | None:
        attempt = self.session.scalar(
            select(PhaseAttemptV2)
            .where(
                PhaseAttemptV2.workflow_run_id == run_id,
                PhaseAttemptV2.phase_id == phase_id,
                PhaseAttemptV2.decision == Decision.PASS.value,
            )
            .order_by(PhaseAttemptV2.id.desc())
        )
        if not attempt:
            return None
        return json.loads(attempt.report_json)["actor"]["identity"]

    def _validate_contract_coverage(
        self, report: PhaseReportV2, phase: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        actions = _unique_ids(report.actionResults, "instructionId", "instruction")
        checks = _unique_ids(report.checkResults, "checkId", "check")
        evidence = _unique_ids(report.evidence, "evidenceId", "evidence")
        expected_actions = {item["instructionId"] for item in phase["instructions"]}
        expected_checks = {item["checkId"] for item in phase["checks"]}
        if set(actions) != expected_actions:
            raise ContractViolation(
                f"instruction ID coverage mismatch; missing={sorted(expected_actions - set(actions))}, "
                f"unknown={sorted(set(actions) - expected_actions)}"
            )
        instruction_contracts = {item["instructionId"]: item for item in phase["instructions"]}
        for instruction_id, action in actions.items():
            applicability = instruction_contracts[instruction_id].get("applicability", "required")
            if action.status == ActionStatus.NOT_APPLICABLE and applicability != "failure-only":
                raise ContractViolation(f"required instruction cannot be not_applicable: {instruction_id}")
            allowed_tools = set(instruction_contracts[instruction_id]["allowedTools"])
            unknown_tools = set(action.usedTools) - allowed_tools
            if unknown_tools:
                raise ContractViolation(
                    f"instruction {instruction_id} used tools outside its allowlist: {sorted(unknown_tools)}"
                )
        if set(checks) != expected_checks:
            raise ContractViolation(
                f"check ID coverage mismatch; missing={sorted(expected_checks - set(checks))}, "
                f"unknown={sorted(set(checks) - expected_checks)}"
            )
        requirements = {item["requirementId"] for item in phase["evidenceRequirements"]}
        supplied_requirements = [item.requirementId for item in report.evidence]
        unknown = set(supplied_requirements) - requirements
        if unknown:
            raise ContractViolation(f"unknown evidence requirement IDs: {sorted(unknown)}")
        if len(supplied_requirements) != len(set(supplied_requirements)):
            raise ContractViolation("duplicate evidence requirement IDs")
        for check_contract in phase["checks"]:
            result = checks[check_contract["checkId"]]
            if result.status == CheckStatus.NOT_APPLICABLE:
                if check_contract["applicability"] not in {"conditional", "failure-only"}:
                    raise ContractViolation(f"required check cannot be not_applicable: {result.checkId}")
                if not result.notApplicableReason:
                    raise ContractViolation(f"not_applicable check lacks a reason: {result.checkId}")
                if check_contract["applicability"] == "conditional" and not result.tailoringApprovalRef:
                    raise ContractViolation(f"not_applicable check lacks tailoring evidence: {result.checkId}")
                if check_contract["applicability"] == "failure-only" and result.tailoringApprovalRef:
                    raise ContractViolation(f"failure-only check must not use tailoring approval: {result.checkId}")
            elif result.notApplicableReason or result.tailoringApprovalRef:
                raise ContractViolation(f"tailoring fields are only valid for not_applicable: {result.checkId}")
        return actions, checks, evidence

    def _verify_evidence(
        self,
        run: WorkflowRunV2,
        report: PhaseReportV2,
        phase: dict[str, Any],
        checks: dict[str, Any],
        evidence: dict[str, Any],
    ) -> tuple[list[tuple[str, str, VerificationResult, datetime | None]], list[str], list[str]]:
        now = self.now()
        requirements = {item["requirementId"]: item for item in phase["evidenceRequirements"]}
        by_requirement = {item.requirementId: item for item in evidence.values()}
        check_contracts = {item["checkId"]: item for item in phase["checks"]}
        results: list[tuple[str, str, VerificationResult, datetime | None]] = []
        missing: list[str] = []
        invalid: list[str] = []
        for requirement_id, requirement in requirements.items():
            linked = [checks[check_id] for check_id in requirement["checkIds"]]
            is_n_a = linked and all(item.status == CheckStatus.NOT_APPLICABLE for item in linked)
            item = by_requirement.get(requirement_id)
            if not item:
                if requirement["required"] and not is_n_a:
                    missing.extend(requirement["checkIds"])
                continue
            if item.type != requirement["type"] or set(item.checkIds) != set(requirement["checkIds"]):
                invalid.append(item.evidenceId)
                results.append(
                    (
                        item.evidenceId,
                        "report",
                        VerificationResult.failed("evidence contract mismatch"),
                        item.observedAt,
                    )
                )
                continue
            binding = requirement["revisionBinding"]
            expected_revision = report.inputRevisions.get(binding)
            if binding == "catalogRevision":
                expected_revision = run.catalog_revision
            if not expected_revision or item.subjectRevision != expected_revision:
                invalid.append(item.evidenceId)
                results.append(
                    (
                        item.evidenceId,
                        "report",
                        VerificationResult.failed(
                            "subject revision mismatch", expected=expected_revision, actual=item.subjectRevision
                        ),
                        item.observedAt,
                    )
                )
                continue
            if item.observedAt > now + timedelta(minutes=5):
                invalid.append(item.evidenceId)
                results.append(
                    (
                        item.evidenceId,
                        "report",
                        VerificationResult.failed("evidence timestamp is in the future"),
                        item.observedAt,
                    )
                )
                continue
            if now - item.observedAt > timedelta(seconds=requirement["maxAgeSeconds"]):
                invalid.append(item.evidenceId)
                results.append(
                    (item.evidenceId, "report", VerificationResult.failed("evidence is stale"), item.observedAt)
                )
                continue
            for check_id in requirement["checkIds"]:
                if item.evidenceId not in checks[check_id].evidenceIds:
                    invalid.append(item.evidenceId)
            verifier_types = [
                check_contracts[check_id]["verifierType"]
                for check_id in requirement["checkIds"]
                if check_contracts[check_id]["verifierType"] != "report"
            ]
            verifier_type = verifier_types[0] if verifier_types else "file"
            context = VerificationContext(
                task_key=report.taskKey,
                phase_id=report.phaseId,
                profile=run.profile,
                expected_revision=expected_revision,
                check_id=requirement["checkIds"][0],
                requirement_id=requirement_id,
                schema_ref=requirement.get("schemaRef"),
                policy_ref=requirement.get("policyRef"),
                artifact_schema=phase.get("artifactSchemas", {}).get(requirement.get("schemaRef")),
                artifact_policy=phase.get("artifactPolicies", {}).get(requirement.get("policyRef")),
            )
            verified = self.registry.verify(verifier_type, item, context)
            if verified.status == "failed":
                invalid.append(item.evidenceId)
            results.append((item.evidenceId, verifier_type, verified, item.observedAt))
        return results, missing, invalid

    def _verify_approvals(
        self, run: WorkflowRunV2, report: PhaseReportV2, phase: dict[str, Any]
    ) -> tuple[list[tuple[str, str, VerificationResult, datetime | None]], list[str], bool]:
        rule = phase.get("approvalRule")
        if not rule:
            if report.approvals:
                raise ContractViolation("approvals are not accepted outside a human gate")
            return [], [], False
        approvals = _unique_ids(report.approvals, "approvalId", "approval")
        required_roles = set(rule["roles"])
        supplied_roles = [item.role for item in approvals.values()]
        unknown_roles = set(supplied_roles) - required_roles
        if unknown_roles or len(supplied_roles) != len(set(supplied_roles)):
            raise ContractViolation("approval roles are unknown or duplicated")
        expected = report.inputRevisions.get(rule["revisionBinding"])
        if not expected:
            raise ContractViolation(f"approval revision binding is missing: {rule['revisionBinding']}")
        results: list[tuple[str, str, VerificationResult, datetime | None]] = []
        missing = [f"approval:{role}" for role in required_roles - set(supplied_roles)]
        rejected = False
        for approval in approvals.values():
            if approval.subjectRevision != expected:
                result = VerificationResult.failed("approval subject revision mismatch")
            else:
                context = VerificationContext(
                    task_key=report.taskKey,
                    phase_id=report.phaseId,
                    profile=run.profile,
                    expected_revision=expected,
                    check_id=f"approval:{approval.role}",
                )
                result = self.registry.verify_approval(approval, context)
            results.append((f"approval:{approval.approvalId}", "human-approval", result, approval.approvedAt))
            if approval.decision == "rejected" and result.status == "passed":
                rejected = True
        return results, missing, rejected

    def _decide(
        self,
        report: PhaseReportV2,
        phase: dict[str, Any],
        actions: dict[str, Any],
        checks: dict[str, Any],
        verification_results: list[tuple[str, str, VerificationResult, datetime | None]],
        missing_checks: list[str],
        invalid_evidence: list[str],
        missing_approvals: list[str],
        rejected_approvals: bool,
    ) -> tuple[Decision, str | None, list[str]]:
        blockers = [item.message for item in report.blockers]
        if rejected_approvals:
            return Decision.ABORT, None, blockers + ["human approval rejected"]
        change = next((item for item in report.blockers if item.failureClass == "change-scope"), None)
        if change:
            return Decision.CHANGE_REQUEST, "change-scope", blockers
        if any(item.externalDependency for item in report.blockers):
            return Decision.BLOCKED, "external-unavailable", blockers
        if any(item.status == ActionStatus.BLOCKED for item in actions.values()):
            return Decision.BLOCKED, "external-unavailable", blockers
        if any(item.status == CheckStatus.BLOCKED for item in checks.values()):
            return Decision.BLOCKED, "external-unavailable", blockers
        if any(item[2].status == "blocked" for item in verification_results):
            messages = [
                str(item[2].details.get("reason", item[0]))
                for item in verification_results
                if item[2].status == "blocked"
            ]
            return Decision.BLOCKED, "external-unavailable", blockers + messages
        if missing_checks or missing_approvals:
            return Decision.INCOMPLETE, "phase-incomplete", blockers
        failed_action = any(item.status == ActionStatus.FAILED for item in actions.values())
        failed_check_id = next(
            (check_id for check_id, item in checks.items() if item.status == CheckStatus.FAILED), None
        )
        post_deploy_failed = any(
            item.status == CheckStatus.FAILED and contract["failureClass"] == "post-deploy-failure"
            for check_id, item in checks.items()
            for contract in phase["checks"]
            if contract["checkId"] == check_id
        )
        if report.phaseId == "D31" and post_deploy_failed:
            recovery = checks.get("d31-rollback-restored")
            recovery_action = actions.get("d31-08-rollback-restored")
            if recovery is None or recovery.status != CheckStatus.PASSED:
                return Decision.INCOMPLETE, "rollback-recovery-pending", blockers + [
                    "previous stable digest recovery is not yet proven"
                ]
            if recovery_action is None or recovery_action.status != ActionStatus.COMPLETED:
                return Decision.INCOMPLETE, "rollback-recovery-pending", blockers + [
                    "previous stable digest compensating action is not complete"
                ]
        if report.phaseId == "D31" and not post_deploy_failed:
            recovery = checks.get("d31-rollback-restored")
            recovery_action = actions.get("d31-08-rollback-restored")
            if recovery is not None and recovery.status != CheckStatus.NOT_APPLICABLE:
                raise ContractViolation("failure-only recovery check must be not_applicable on a healthy deployment")
            if recovery_action is not None and recovery_action.status != ActionStatus.NOT_APPLICABLE:
                raise ContractViolation("failure-only recovery action must be not_applicable on a healthy deployment")
        verifier_failed = any(item[2].status == "failed" for item in verification_results)
        if failed_action or failed_check_id or verifier_failed or invalid_evidence:
            check_contracts = {item["checkId"]: item for item in phase["checks"]}
            failure_class = (
                check_contracts[failed_check_id]["failureClass"]
                if failed_check_id
                else ("verification-failed" if verifier_failed or invalid_evidence else "implementation-defect")
            )
            return Decision.ROLLBACK, failure_class, blockers
        incomplete_actions = any(
            item.status not in {ActionStatus.COMPLETED, ActionStatus.NOT_APPLICABLE} for item in actions.values()
        )
        incomplete_checks = any(
            item.status not in {CheckStatus.PASSED, CheckStatus.NOT_APPLICABLE} for item in checks.values()
        )
        if incomplete_actions or incomplete_checks:
            return Decision.INCOMPLETE, "phase-incomplete", blockers
        return Decision.PASS, None, blockers

    def _invalidate_downstream(
        self, run: WorkflowRunV2, target_phase: str, catalog: WorkflowCatalogV2
    ) -> list[str]:
        path = catalog.path(run.profile)
        target_index = path.index(target_phase)
        baselines = self.session.scalars(
            select(BaselineRevisionV2).where(
                BaselineRevisionV2.workflow_run_id == run.id,
                BaselineRevisionV2.invalidated_at.is_(None),
            )
        ).all()
        invalidated: list[str] = []
        for baseline in baselines:
            if path.index(baseline.phase_id) >= target_index:
                baseline.invalidated_at = self.now()
                invalidated.append(baseline.revision_value)
        return invalidated

    def _persist_receipts(
        self,
        attempt: PhaseAttemptV2,
        results: list[tuple[str, str, VerificationResult, datetime | None]],
    ) -> None:
        for evidence_id, verifier_type, result, observed_at in results:
            self.session.add(
                EvidenceVerificationReceiptV2(
                    attempt_id=attempt.id,
                    evidence_id=evidence_id,
                    verifier_type=verifier_type,
                    status=result.status,
                    details_json=_canonical_json(result.details),
                    observed_at=observed_at,
                )
            )

    def _persist_approvals(
        self,
        run: WorkflowRunV2,
        attempt: PhaseAttemptV2,
        report: PhaseReportV2,
        results: list[tuple[str, str, VerificationResult, datetime | None]],
    ) -> None:
        passed_ids = {
            evidence_id.removeprefix("approval:") for evidence_id, _, result, _ in results if result.status == "passed"
        }
        for approval in report.approvals:
            if approval.approvalId not in passed_ids:
                continue
            existing = self.session.scalar(
                select(HumanApprovalV2).where(
                    HumanApprovalV2.workflow_run_id == run.id,
                    HumanApprovalV2.approval_id == approval.approvalId,
                )
            )
            if existing:
                continue
            self.session.add(
                HumanApprovalV2(
                    workflow_run_id=run.id,
                    attempt_id=attempt.id,
                    approval_id=approval.approvalId,
                    phase_id=report.phaseId,
                    role=approval.role,
                    identity=approval.identity,
                    decision=approval.decision,
                    subject_revision=approval.subjectRevision,
                    external_ref=approval.externalRef,
                    approved_at=approval.approvedAt,
                )
            )

    def _persist_baseline_and_deployment(
        self, run: WorkflowRunV2, report: PhaseReportV2, phase: dict[str, Any]
    ) -> None:
        rule = phase.get("approvalRule")
        if rule:
            kind = rule["revisionBinding"]
            value = report.inputRevisions[kind]
            existing = self.session.scalar(
                select(BaselineRevisionV2).where(
                    BaselineRevisionV2.workflow_run_id == run.id,
                    BaselineRevisionV2.phase_id == report.phaseId,
                    BaselineRevisionV2.revision_kind == kind,
                    BaselineRevisionV2.revision_value == value,
                )
            )
            if not existing:
                self.session.add(
                    BaselineRevisionV2(
                        workflow_run_id=run.id,
                        phase_id=report.phaseId,
                        revision_kind=kind,
                        revision_value=value,
                    )
                )
        if report.phaseId == "D21":
            artifact_digest = report.inputRevisions["artifactDigest"]
            existing_artifact = self.session.scalar(
                select(BaselineRevisionV2).where(
                    BaselineRevisionV2.workflow_run_id == run.id,
                    BaselineRevisionV2.phase_id == "D21",
                    BaselineRevisionV2.revision_kind == "artifactDigest",
                    BaselineRevisionV2.revision_value == artifact_digest,
                )
            )
            if not existing_artifact:
                self.session.add(
                    BaselineRevisionV2(
                        workflow_run_id=run.id,
                        phase_id="D21",
                        revision_kind="artifactDigest",
                        revision_value=artifact_digest,
                    )
                )
        if report.phaseId in {"D23", "D28", "D30"}:
            for item in report.evidence:
                deployment_id = item.metadata.get("deploymentId")
                environment = item.metadata.get("environment")
                if deployment_id and environment:
                    self.session.add(
                        ArtifactDeploymentLinkV2(
                            workflow_run_id=run.id,
                            artifact_digest=report.inputRevisions["artifactDigest"],
                            environment=str(environment),
                            deployment_id=str(deployment_id),
                            status="verified",
                            evidence_id=item.evidenceId,
                        )
                    )

    def _get_run(self, task_key: str, *, for_update: bool = False) -> WorkflowRunV2:
        statement = select(WorkflowRunV2).where(WorkflowRunV2.task_key == task_key)
        if for_update:
            statement = statement.with_for_update()
        run = self.session.scalar(statement)
        if not run:
            raise ContractViolation(f"v2 task run not found: {task_key}")
        return run

    def _catalog_for_run(self, run: WorkflowRunV2) -> WorkflowCatalogV2:
        if run.catalog_revision == self.catalog.revision:
            return self.catalog
        record = self.session.scalar(
            select(WorkflowCatalogRecordV2).where(
                WorkflowCatalogRecordV2.catalog_revision == run.catalog_revision
            )
        )
        if record is None:
            raise ContractViolation("pinned catalog revision is not available")
        try:
            payload = json.loads(record.catalog_json)
            catalog = WorkflowCatalogV2(payload)
            catalog.validate()
        except (json.JSONDecodeError, CatalogError) as exc:
            raise ContractViolation("stored pinned catalog is invalid") from exc
        if catalog.workflow_version != run.workflow_version:
            raise ContractViolation("pinned catalog workflow version mismatch")
        return catalog

    @staticmethod
    def _run_dict(run: WorkflowRunV2) -> dict[str, Any]:
        return {
            "taskKey": run.task_key,
            "profile": run.profile,
            "workflowVersion": run.workflow_version,
            "catalogRevision": run.catalog_revision,
            "currentPhase": run.current_phase,
            "status": run.status,
            "lastDecision": run.last_decision,
        }
