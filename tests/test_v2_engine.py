from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.v2 import PolicyEngineV2, WorkflowCatalogV2, load_default_catalog
from project_workflow.v2.engine import ContractViolation, IdentityPolicy, ReplayConflict
from project_workflow.v2.schemas import Decision, PhaseReportV2
from project_workflow.v2.verifiers import VerificationResult, VerifierRegistry


class PassingVerifier:
    def verify(self, evidence, context):
        return VerificationResult.passed(subjectRevision=context.expected_revision)

    def verify_approval(self, approval, context):
        if approval.subjectRevision != context.expected_revision:
            return VerificationResult.failed("revision mismatch")
        return VerificationResult.passed(externalRef=approval.externalRef)


@pytest.fixture
def engine():
    uow = SAUnitOfWork()
    uow.init()
    passing = PassingVerifier()
    registry = VerifierRegistry(
        verifiers={
            name: passing
            for name in {
                "file",
                "git",
                "jira",
                "gitlab-mr",
                "gitlab-pipeline",
                "gitlab-approval",
                "oci-registry",
                "deployment",
                "runtime",
                "observation",
                "human-approval",
            }
        },
        approval_verifier=passing,
    )
    identities = IdentityPolicy(
        agent_identities=frozenset({"analyst", "security", "developer", "qa", "reviewer", "ops", "improver"}),
        human_identities=frozenset({"owner"}),
    )
    yield PolicyEngineV2(uow.session, registry=registry, identity_policy=identities)
    uow.close()


def identity_for_role(role: str) -> str:
    return {
        "Business Analyst": "analyst",
        "Architect Security": "security",
        "Developer": "developer",
        "QA": "qa",
        "Reviewer": "reviewer",
        "Release Ops": "ops",
        "Process Improver": "improver",
    }[role]


def revision_value(binding: str, catalog_revision: str) -> str:
    return {
        "catalogRevision": catalog_revision,
        "gitSha": "1" * 40,
        "mrHeadSha": "2" * 40,
        "artifactDigest": "sha256:" + "3" * 64,
        "pipelineId": "pipeline-42",
        "jiraRevision": "jira-7",
        "businessOutcomeRevision": "outcome-v1",
        "scopeRevision": "scope-v1",
        "baselineRevision": "baseline-v1",
    }.get(binding, f"{binding}-v1")


def build_report(engine: PolicyEngineV2, task_key: str, run_id: str) -> dict:
    current = engine.current(task_key)
    phase = current["contract"]
    catalog_revision = current["catalogRevision"]
    bindings = {"catalogRevision"}
    bindings.update(item["revisionBinding"] for item in phase["checks"])
    bindings.update(item["revisionBinding"] for item in phase["evidenceRequirements"])
    bindings.update(phase["requiredRevisionBindings"])
    if phase["approvalRule"]:
        bindings.add(phase["approvalRule"]["revisionBinding"])
    input_revisions = {binding: revision_value(binding, catalog_revision) for binding in bindings}
    evidences = []
    check_evidence: dict[str, list[str]] = {item["checkId"]: [] for item in phase["checks"]}
    for requirement in phase["evidenceRequirements"]:
        requirement_checks = [
            item for item in phase["checks"] if item["checkId"] in requirement["checkIds"]
        ]
        if requirement_checks and all(item["applicability"] == "failure-only" for item in requirement_checks):
            continue
        evidence_id = "ev-" + requirement["requirementId"]
        for check_id in requirement["checkIds"]:
            check_evidence[check_id].append(evidence_id)
        evidences.append(
            {
                "evidenceId": evidence_id,
                "requirementId": requirement["requirementId"],
                "checkIds": requirement["checkIds"],
                "type": requirement["type"],
                "uri": f"memory://{task_key}/{phase['phaseId']}/{evidence_id}",
                "sha256": "0" * 64,
                "subjectRevision": input_revisions[requirement["revisionBinding"]],
                "producerIdentity": identity_for_role(phase["ownerRole"]),
                "observedAt": datetime.now(timezone.utc).isoformat(),
                "metadata": {},
            }
        )
    approvals = []
    if phase["approvalRule"]:
        subject = input_revisions[phase["approvalRule"]["revisionBinding"]]
        for role in phase["approvalRule"]["roles"]:
            approvals.append(
                {
                    "approvalId": f"{phase['phaseId']}-{role}-{run_id}",
                    "role": role,
                    "identity": "owner",
                    "actorType": "human",
                    "decision": "approved",
                    "subjectRevision": subject,
                    "approvedAt": datetime.now(timezone.utc).isoformat(),
                    "externalRef": f"jira://{task_key}/approval/{phase['phaseId']}/{role}",
                }
            )
    return {
        "schemaVersion": "phase-report/v2",
        "workflowVersion": "agentic-sdlc-v2",
        "catalogRevision": catalog_revision,
        "taskKey": task_key,
        "runId": run_id,
        "phaseId": phase["phaseId"],
        "actor": {
            "identity": identity_for_role(phase["ownerRole"]),
            "role": phase["ownerRole"],
            "type": "agent",
        },
        "inputRevisions": input_revisions,
        "actionResults": [
            {
                "instructionId": item["instructionId"],
                "status": "not_applicable" if item.get("applicability") == "failure-only" else "completed",
                "usedTools": [item["allowedTools"][0]],
            }
            for item in phase["instructions"]
        ],
        "checkResults": [
            {
                "checkId": item["checkId"],
                "status": "not_applicable" if item["applicability"] == "failure-only" else "passed",
                "evidenceIds": check_evidence[item["checkId"]],
                **(
                    {"notApplicableReason": "No post-deploy failure occurred."}
                    if item["applicability"] == "failure-only"
                    else {}
                ),
            }
            for item in phase["checks"]
        ],
        "evidence": evidences,
        "approvals": approvals,
        "blockers": [],
    }


def test_pass_advances_exactly_one_phase_and_replay_returns_receipt(engine):
    engine.start("AAT-101", "feature")
    payload = build_report(engine, "AAT-101", "run-c01")

    first = engine.submit(payload)
    replay = engine.submit(payload)

    assert first.decision == Decision.PASS
    assert first.currentPhase == "C01"
    assert first.nextPhase == "C02"
    assert engine.current("AAT-101")["currentPhase"] == "C02"
    assert replay.receiptId == first.receiptId
    assert len(engine.history("AAT-101")) == 1
    assert engine.history("AAT-101")[0]["nextPhase"] == "C02"
    assert engine.history("AAT-101")[0]["missingChecks"] == []


def test_evidence_export_contains_only_sanitized_verified_records(engine):
    engine.start("AAT-109", "feature")
    payload = build_report(engine, "AAT-109", "export-c01")
    payload["evidence"][0]["uri"] = "https://reader:password@example.test/evidence?access_token=hidden#fragment"
    payload["evidence"][0]["metadata"] = {
        "deploymentId": "deploy-17",
        "requiredJobs": ["build", "test"],
        "authorization": "Bearer hidden",
        "nested": {"secret": "hidden"},
    }
    decision = engine.submit(payload)

    exported = engine.evidence_export("AAT-109")

    assert exported["schemaVersion"] == "evidence-export/v1"
    assert exported["catalogRevision"] == engine.catalog.revision
    assert exported["attempts"][0]["controllerReceiptId"] == decision.receiptId
    item = exported["verifiedEvidence"][0]
    assert item["uri"] == "https://example.test/evidence"
    assert item["metadata"] == {"deploymentId": "deploy-17", "requiredJobs": ["build", "test"]}
    assert item["verificationReceiptId"].startswith("evr-")
    assert "hidden" not in json.dumps(exported)


@pytest.mark.parametrize(("profile", "expected_count"), [("feature", 60), ("bug", 54)])
def test_evidence_export_v2_owns_expected_phase_path(engine, profile, expected_count):
    task_key = "AAT-209" if profile == "feature" else "AAT-210"
    engine.start(task_key, profile)

    exported = engine.evidence_export(task_key, schema_version=2)

    assert exported["schemaVersion"] == "evidence-export/v2"
    assert len(exported["expectedPhasePath"]) == expected_count
    assert exported["expectedPhasePath"] == engine.catalog.path(profile)


def test_evidence_export_v2_exposes_sanitized_transition_shape_without_changing_v1(engine):
    engine.start("AAT-212", "feature")
    engine.submit(build_report(engine, "AAT-212", "export-transition-c01"))

    legacy = engine.evidence_export("AAT-212")
    versioned = engine.evidence_export("AAT-212", schema_version=2)

    assert "nextPhase" not in legacy["attempts"][0]
    assert "rollbackTarget" not in legacy["attempts"][0]
    assert versioned["attempts"][0]["nextPhase"] == "C02"
    assert versioned["attempts"][0]["rollbackTarget"] is None


def test_evidence_export_rejects_unknown_schema_version(engine):
    engine.start("AAT-211", "feature")

    with pytest.raises(ContractViolation, match="schema version"):
        engine.evidence_export("AAT-211", schema_version=3)


def test_evidence_export_does_not_promote_failed_receipts():
    uow = SAUnitOfWork()
    uow.init()
    identities = IdentityPolicy(frozenset({"analyst"}), frozenset({"owner"}))
    failing = PolicyEngineV2(uow.session, identity_policy=identities)
    failing.start("AAT-110", "feature")
    result = failing.submit(build_report(failing, "AAT-110", "failed-export"))

    exported = failing.evidence_export("AAT-110")

    assert result.decision != Decision.PASS
    assert exported["attempts"][0]["verificationReceipts"]
    assert exported["verifiedEvidence"] == []
    uow.close()


def test_evidence_export_replay_does_not_duplicate_attempts(engine):
    engine.start("AAT-111", "feature")
    payload = build_report(engine, "AAT-111", "same-export")
    engine.submit(payload)
    engine.submit(payload)

    exported = engine.evidence_export("AAT-111")

    assert len(exported["attempts"]) == 1
    assert len({item["evidenceId"] for item in exported["verifiedEvidence"]}) == len(
        exported["verifiedEvidence"]
    )


def test_evidence_export_supports_started_run_without_attempts(engine):
    engine.start("AAT-112", "bug")

    exported = engine.evidence_export("AAT-112")

    assert exported["attempts"] == []
    assert exported["verifiedEvidence"] == []


def test_evidence_uri_sanitizer_drops_invalid_or_sensitive_authority_parts():
    from project_workflow.v2.engine import _safe_evidence_metadata, _sanitize_evidence_uri

    assert _sanitize_evidence_uri("https://user:secret@example.test:bad/path?q=token") == (
        "https://example.test/path"
    )
    assert _sanitize_evidence_uri("https://user:secret@[::1]:8443/path#secret") == (
        "https://[::1]:8443/path"
    )
    assert _sanitize_evidence_uri("Authorization: Bearer hidden") == (
        "redacted:ef9ca4ea1b108d3d"
    )
    assert _safe_evidence_metadata(
        {"runtimeBaseUrl": "https://user:secret@runtime.test/health?token=hidden"}
    ) == {"runtimeBaseUrl": "https://runtime.test/health"}


def test_evidence_export_unknown_task_is_rejected(engine):
    with pytest.raises(ContractViolation, match="not found"):
        engine.evidence_export("AAT-999")


def test_active_run_continues_on_its_pinned_catalog_after_packaged_revision_changes(engine):
    started = engine.start("AAT-199", "feature")
    old_revision = started["catalogRevision"]
    old_purpose = engine.current("AAT-199")["contract"]["purpose"]

    payload = deepcopy(engine.catalog.payload)
    payload["phases"][0]["purpose"] = "new catalog revision"
    payload["catalogRevision"] = ""
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    payload["catalogRevision"] = hashlib.sha256(canonical).hexdigest()
    new_catalog = WorkflowCatalogV2(payload)
    new_catalog.validate()
    upgraded = PolicyEngineV2(
        engine.session,
        catalog=new_catalog,
        registry=engine.registry,
        identity_policy=engine.identity_policy,
        now=engine.now,
    )

    current = upgraded.current("AAT-199")
    assert current["catalogRevision"] == old_revision
    assert current["contract"]["purpose"] == old_purpose
    assert upgraded.start("AAT-199", "feature")["catalogRevision"] == old_revision
    decision = upgraded.submit(build_report(upgraded, "AAT-199", "old-catalog-c01"))
    assert decision.decision == Decision.PASS
    assert upgraded.current("AAT-199")["currentPhase"] == "C02"


def test_conflicting_replay_is_rejected(engine):
    engine.start("AAT-102", "feature")
    payload = build_report(engine, "AAT-102", "same-run")
    engine.submit(payload)
    payload["checkResults"][0]["details"] = {"changed": True}

    with pytest.raises(ReplayConflict):
        engine.submit(payload)


def test_unknown_or_duplicate_contract_ids_are_rejected(engine):
    engine.start("AAT-103", "feature")
    payload = build_report(engine, "AAT-103", "bad-contract")
    payload["actionResults"][0]["instructionId"] = "unknown-instruction"

    with pytest.raises(ContractViolation, match="coverage mismatch"):
        engine.submit(payload)


def test_actor_role_and_allowlist_are_fail_closed(engine):
    engine.start("AAT-104", "feature")
    payload = build_report(engine, "AAT-104", "bad-actor")
    payload["actor"]["identity"] = "untrusted-agent"

    with pytest.raises(ContractViolation, match="not allowlisted"):
        engine.submit(payload)


def test_instruction_tool_allowlist_is_enforced(engine):
    engine.start("AAT-106", "feature")
    payload = build_report(engine, "AAT-106", "bad-tool")
    payload["actionResults"][0]["usedTools"] = ["unlisted-root-shell"]

    with pytest.raises(ContractViolation, match="outside its allowlist"):
        engine.submit(payload)


def test_blocked_dependency_does_not_advance(engine):
    engine.start("AAT-107", "feature")
    payload = build_report(engine, "AAT-107", "blocked")
    payload["blockers"] = [
        {
            "code": "jira-unavailable",
            "failureClass": "external-unavailable",
            "message": "Jira timed out",
            "externalDependency": True,
        }
    ]

    result = engine.submit(payload)

    assert result.decision == Decision.BLOCKED
    assert engine.current("AAT-107")["currentPhase"] == "C01"


def test_failed_check_rolls_back_without_advancing(engine):
    engine.start("AAT-108", "feature")
    payload = build_report(engine, "AAT-108", "failed-check")
    payload["checkResults"][0]["status"] = "failed"

    result = engine.submit(payload)

    assert result.decision == Decision.ROLLBACK
    assert result.rollbackTarget == "C01"
    assert engine.current("AAT-108")["currentPhase"] == "C01"


def test_missing_external_verifier_blocks_instead_of_trusting_report():
    uow = SAUnitOfWork()
    uow.init()
    identities = IdentityPolicy(frozenset({"analyst", "security"}), frozenset({"owner"}))
    default_engine = PolicyEngineV2(uow.session, identity_policy=identities)
    default_engine.start("AAT-105", "feature")
    first = build_report(default_engine, "AAT-105", "c01")
    # The file verifier fails C01 (fabricated URI), proving report status cannot
    # pass by assertion alone. Move to C02 with the passing engine is unnecessary:
    # a failed verifier must deterministically route away from PASS.
    result = default_engine.submit(first)

    assert result.decision != Decision.PASS
    assert default_engine.current("AAT-105")["currentPhase"] == "C01"
    uow.close()


@pytest.mark.parametrize("profile,task_key,expected_phases", [("feature", "AAT-201", 60), ("bug", "AAT-202", 54)])
def test_complete_profile_happy_paths(engine, profile, task_key, expected_phases):
    engine.start(task_key, profile)

    for index in range(expected_phases):
        payload = build_report(engine, task_key, f"attempt-{index:02d}")
        decision = engine.submit(payload)
        assert decision.decision == Decision.PASS

    state = engine.current(task_key)
    assert state["status"] == "done"
    assert state["currentPhase"] == "X04"
    assert len(engine.history(task_key)) == expected_phases


def test_postdeploy_failure_requires_proven_recovery_without_creating_linked_bug(engine):
    engine.start("AAT-401", "feature")
    attempt = 0
    while engine.current("AAT-401")["currentPhase"] != "D31":
        result = engine.submit(build_report(engine, "AAT-401", f"before-d31-{attempt:02d}"))
        assert result.decision == Decision.PASS
        attempt += 1

    incomplete = build_report(engine, "AAT-401", "d31-recovery-missing")
    next(item for item in incomplete["checkResults"] if item["checkId"] == "d31-runtime-version")[
        "status"
    ] = "failed"
    pending = engine.submit(incomplete)

    assert pending.decision == Decision.INCOMPLETE
    assert engine.current("AAT-401")["currentPhase"] == "D31"

    recovered = build_report(engine, "AAT-401", "d31-recovery-proven")
    next(item for item in recovered["checkResults"] if item["checkId"] == "d31-runtime-version")[
        "status"
    ] = "failed"
    recovery_check = next(
        item for item in recovered["checkResults"] if item["checkId"] == "d31-rollback-restored"
    )
    recovery_check["status"] = "passed"
    recovery_check.pop("notApplicableReason")
    recovery_action = next(
        item for item in recovered["actionResults"] if item["instructionId"] == "d31-08-rollback-restored"
    )
    recovery_action["status"] = "completed"
    evidence_id = "ev-d31-e-rollback-restored"
    recovery_check["evidenceIds"] = [evidence_id]
    recovered["evidence"].append(
        {
            "evidenceId": evidence_id,
            "requirementId": "d31-e-rollback-restored",
            "checkIds": ["d31-rollback-restored"],
            "type": "runtime-restoration",
            "uri": "memory://AAT-401/D31/runtime-restoration",
            "sha256": "4" * 64,
            "subjectRevision": recovered["inputRevisions"]["previousStableDigest"],
            "producerIdentity": "ops",
            "observedAt": datetime.now(timezone.utc).isoformat(),
            "metadata": {"health": "UP"},
        }
    )
    rolled_back = engine.submit(recovered)

    assert rolled_back.decision == Decision.ROLLBACK
    assert rolled_back.rollbackTarget == "D31"
    assert engine.current("AAT-401")["status"] == "aborted"
    with pytest.raises(ContractViolation, match="v2 task run not found"):
        engine.current("AAT-402")


def test_same_person_can_fill_two_roles_only_as_separate_records(engine):
    engine.start("AAT-301", "feature")
    while engine.current("AAT-301")["currentPhase"] != "F16":
        phase_id = engine.current("AAT-301")["currentPhase"]
        engine.submit(build_report(engine, "AAT-301", f"to-f16-{phase_id}"))
    payload = build_report(engine, "AAT-301", "f16-gate")

    assert {item["identity"] for item in payload["approvals"]} == {"owner"}
    assert {item["role"] for item in payload["approvals"]} == {"business-owner", "technical-owner"}
    assert engine.submit(payload).decision == Decision.PASS


def test_missing_one_role_bound_approval_is_incomplete(engine):
    engine.start("AAT-302", "feature")
    while engine.current("AAT-302")["currentPhase"] != "C06":
        phase_id = engine.current("AAT-302")["currentPhase"]
        engine.submit(build_report(engine, "AAT-302", f"to-c06-{phase_id}"))
    payload = build_report(engine, "AAT-302", "missing-approval")
    payload["approvals"] = []

    result = engine.submit(payload)

    assert result.decision == Decision.INCOMPLETE
    assert result.missingChecks == ["approval:business-owner"]
    assert engine.current("AAT-302")["currentPhase"] == "C06"
    assert engine.current("AAT-302")["revisions"]["businessOutcomeRevision"] == "outcome-v1"


def test_schema_rejects_agent_created_approval():
    catalog = load_default_catalog()
    payload = {
        "approvalId": "a1",
        "role": "business-owner",
        "identity": "hermes",
        "actorType": "agent",
        "decision": "approved",
        "subjectRevision": "scope-v1",
        "approvedAt": datetime.now(timezone.utc).isoformat(),
        "externalRef": "jira://AAT-1/comment/1",
    }

    with pytest.raises(ValidationError):
        PhaseReportV2.model_validate(
            {
                "schemaVersion": "phase-report/v2",
                "workflowVersion": "agentic-sdlc-v2",
                "catalogRevision": catalog.revision,
                "taskKey": "AAT-1",
                "runId": "run",
                "phaseId": "C06",
                "actor": {"identity": "analyst", "role": "Business Analyst", "type": "agent"},
                "inputRevisions": {},
                "actionResults": [],
                "checkResults": [],
                "evidence": [],
                "approvals": [payload],
                "blockers": [],
            }
        )
