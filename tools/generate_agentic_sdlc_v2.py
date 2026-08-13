# ruff: noqa: E501
"""Generate the canonical Agentic SDLC v2 workflow catalog.

The catalog is generated from compact phase definitions so phase counts and
stable identifiers cannot drift through hand-edited JSON. Runtime code only
reads the generated artifact; it never calls this generator implicitly.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "project_workflow" / "references" / "agentic_sdlc_v2.json"


COMMON = [
    ("C01", "Task Intake", "Business Analyst", "Capture the requested outcome, problem, requester and source links."),
    (
        "C02",
        "Systems & Identity Readiness",
        "Architect Security",
        "Verify Jira, GitLab, repository, runner, Hermes and service identities.",
    ),
    (
        "C03",
        "Workspace & Repository Baseline",
        "Architect Security",
        "Create an isolated workspace and pin the repository baseline.",
    ),
    (
        "C04",
        "Task Classification",
        "Business Analyst",
        "Classify the task as feature or bug and identify the affected component.",
    ),
    (
        "C05",
        "Risk, Data & Compliance Classification",
        "Architect Security",
        "Classify risk, data, privacy, security and compliance applicability.",
    ),
    (
        "C06",
        "Stakeholder, Value & Impact",
        "Business Analyst",
        "Define the measurable outcome, affected consumers and accountable owner.",
    ),
    (
        "C07",
        "Workflow Tailoring",
        "Architect Security",
        "Select the profile and approve every conditional verification lane.",
    ),
    ("C08", "Jira Start", "Business Analyst", "Move the Jira issue to in progress and read the transition back."),
]

FEATURE = [
    ("F01", "Source-of-Truth Research", "Business Analyst", "Collect authoritative business and product sources."),
    (
        "F02",
        "Repository & Dataflow Research",
        "Architect Security",
        "Trace the current implementation, owners and dataflow.",
    ),
    (
        "F03",
        "Dependency & Supplier Research",
        "Architect Security",
        "Assess dependencies, suppliers, versions and support constraints.",
    ),
    ("F04", "Research Synthesis", "Business Analyst", "Reconcile findings, conflicts, constraints and open decisions."),
    ("F05", "Scope Baseline", "Business Analyst", "Publish the approved in-scope and out-of-scope baseline."),
    (
        "F06",
        "Functional Specification",
        "Business Analyst",
        "Specify actors, inputs, outputs, behavior and failure semantics.",
    ),
    (
        "F07",
        "Non-Functional Requirements",
        "Architect Security",
        "Define measurable performance, reliability and capacity requirements.",
    ),
    (
        "F08",
        "Security, Privacy & Compliance Requirements",
        "Architect Security",
        "Define applicable security, privacy and compliance controls.",
    ),
    (
        "F09",
        "Acceptance, Negative & Abuse Cases",
        "QA",
        "Derive positive, negative, misuse and abuse acceptance cases.",
    ),
    (
        "F10",
        "UX, API & Data Contracts",
        "Architect Security",
        "Version applicable UX, API, compatibility and data contracts.",
    ),
    (
        "F11",
        "Requirements Traceability Baseline",
        "Business Analyst",
        "Link requirements to acceptance cases and planned evidence.",
    ),
    (
        "F12",
        "Architecture & ADR",
        "Architect Security",
        "Select the design and publish an approved architecture decision.",
    ),
    (
        "F13",
        "Threat Model",
        "Architect Security",
        "Model assets, trust boundaries, threats, mitigations and residual risk.",
    ),
    (
        "F14",
        "Operability, Observability & Rollback Design",
        "Release Ops",
        "Design telemetry, support, rollback and recovery before coding.",
    ),
    ("F15", "Test Strategy", "QA", "Define test levels, fixtures, environments, ownership and evidence."),
    (
        "F16",
        "Plan, Estimate & Baseline Approval",
        "Architect Security",
        "Approve the decision-complete implementation and verification plan.",
    ),
]

BUG = [
    ("B01", "Reproduction", "QA", "Reproduce the defect or approve a diagnostic cannot-reproduce record."),
    (
        "B02",
        "Severity & Affected Versions",
        "Business Analyst",
        "Classify impact, urgency and affected versions or environments.",
    ),
    ("B03", "Regression Scope", "QA", "Identify adjacent behavior and the required regression boundary."),
    ("B04", "Root Cause Analysis", "Developer", "Trace the defect to its owning component and causal mechanism."),
    (
        "B05",
        "Security & Incident Classification",
        "Architect Security",
        "Determine whether the defect is a vulnerability or incident.",
    ),
    (
        "B06",
        "Expected Behaviour & Acceptance",
        "Business Analyst",
        "Baseline corrected behavior and acceptance criteria.",
    ),
    ("B07", "Regression Test Design", "QA", "Design a test that fails for the defect and guards recurrence."),
    (
        "B08",
        "Fix, Rollback & Compatibility Risk",
        "Architect Security",
        "Assess fix risk, compatibility, rollback and roll-forward.",
    ),
    (
        "B09",
        "Change Impact",
        "Architect Security",
        "Evaluate consumers, dependencies and required documentation changes.",
    ),
    ("B10", "Fix Plan & Approval", "Architect Security", "Approve the bounded fix and verification plan."),
]

DELIVERY = [
    ("D01", "Workspace Refresh", "Developer", "Refresh the isolated workspace against the approved baseline."),
    ("D02", "Red Test Evidence", "Developer", "Produce a failing test with the expected failure reason."),
    ("D03", "Implementation", "Developer", "Implement the smallest change that satisfies the approved contract."),
    ("D04", "Refactoring", "Developer", "Improve structure without changing approved behavior."),
    (
        "D05",
        "Static, Type & Lint Validation",
        "Developer",
        "Run applicable static, type, formatting and lint policies.",
    ),
    ("D06", "Unit & Component Tests", "Developer", "Verify isolated domain and component behavior."),
    ("D07", "Integration & Contract Tests", "Developer", "Verify integration boundaries and versioned contracts."),
    ("D08", "Diff Scope & Self Review", "Developer", "Review scope, security, compatibility and unintended changes."),
    (
        "D09",
        "Commit & Source Integrity",
        "Developer",
        "Create an atomic commit with traceability and source integrity.",
    ),
    (
        "D10",
        "Push & Branch Verification",
        "Developer",
        "Push the branch and verify the remote head and protection boundary.",
    ),
    ("D11", "CI Build", "Developer", "Build from the exact Git revision in the approved CI environment."),
    ("D12", "CI Functional Tests", "QA", "Verify the required CI functional job matrix on the exact SHA."),
    (
        "D13",
        "CI Security & Supply Chain",
        "Architect Security",
        "Verify security, dependency, secret, license and SBOM jobs.",
    ),
    ("D14", "Draft Merge Request", "Developer", "Create a traceable merge request on the verified head SHA."),
    ("D15", "Independent Code Review", "Reviewer", "Perform independent review and close must-fix findings."),
    ("D16", "QA Functional & Regression", "QA", "Execute acceptance, negative and regression scenarios independently."),
    (
        "D17",
        "Independent Security Verification",
        "Architect Security",
        "Independently verify required security controls and findings.",
    ),
    (
        "D18",
        "Conditional NFR Verification",
        "QA",
        "Execute every applicable performance, resilience and accessibility lane.",
    ),
    (
        "D19",
        "Defect Resolution & Reverification",
        "Developer",
        "Resolve review defects and repeat invalidated verification.",
    ),
    ("D20", "MR Approval on Exact SHA", "Reviewer", "Bind technical approval to the current merge request head."),
    (
        "D21",
        "Immutable Release Candidate Build",
        "Release Ops",
        "Build and publish one immutable OCI release candidate.",
    ),
    (
        "D22",
        "Provenance, SBOM & Signature Verification",
        "Architect Security",
        "Verify provenance, SBOM, signature and artifact policy.",
    ),
    ("D23", "Staging Deploy", "Release Ops", "Deploy the approved digest to isolated staging without rebuilding."),
    ("D24", "Staging Acceptance", "QA", "Verify functional and operational acceptance against staging."),
    (
        "D25",
        "Operational Readiness",
        "Release Ops",
        "Verify runbooks, alerts, support, migration and recovery readiness.",
    ),
    ("D26", "Human Release Go/No-Go", "Release Ops", "Obtain business and technical decisions for the exact digest."),
    (
        "D27",
        "Merge & Release Baseline",
        "Release Ops",
        "Merge the approved SHA and pin the immutable release baseline.",
    ),
    ("D28", "Canary Deploy", "Release Ops", "Deploy the approved digest to the bounded canary target."),
    ("D29", "Canary Observation & Promotion", "Release Ops", "Evaluate canary thresholds and record promote or abort."),
    ("D30", "Full Deployment", "Release Ops", "Promote the same digest under a deployment resource lock."),
    ("D31", "Post-Deploy Verification", "Release Ops", "Verify runtime and restore the previous digest on failure."),
    (
        "D32",
        "Operation Observation, Value & Feedback",
        "Release Ops",
        "Observe runtime, outcome and feedback before closure.",
    ),
]

CLOSURE = [
    ("X01", "Jira Done & Handoff", "Release Ops", "Complete Jira only after verified operation evidence."),
    ("X02", "Lifecycle Metrics", "Process Improver", "Calculate lifecycle, quality, recovery and cost metrics."),
    ("X03", "Retro or Postmortem", "Process Improver", "Run a retro or mandatory postmortem from verified history."),
    (
        "X04",
        "Improvement & Feedback Tasks",
        "Process Improver",
        "Create owned follow-up tasks without rewriting history.",
    ),
]

HUMAN_GATES = {
    "C06": {"roles": ["business-owner"], "revisionBinding": "businessOutcomeRevision"},
    "F05": {"roles": ["business-owner"], "revisionBinding": "scopeRevision"},
    "F16": {
        "roles": ["business-owner", "technical-owner"],
        "revisionBinding": "baselineRevision",
    },
    "B06": {"roles": ["business-owner"], "revisionBinding": "scopeRevision"},
    "B10": {"roles": ["technical-owner"], "revisionBinding": "baselineRevision"},
    "D20": {"roles": ["technical-owner"], "revisionBinding": "mrHeadSha"},
    "D26": {
        "roles": ["business-owner", "technical-owner"],
        "revisionBinding": "artifactDigest",
    },
}

REQUIRED_REVISION_BINDINGS = {
    "D11": ["gitSha"],
    "D12": ["gitSha", "pipelineId"],
    "D13": ["gitSha", "pipelineId"],
    "D14": ["gitSha", "mrHeadSha"],
    "D15": ["mrHeadSha"],
    "D16": ["mrHeadSha"],
    "D17": ["mrHeadSha"],
    "D18": ["mrHeadSha"],
    "D19": ["mrHeadSha"],
    "D20": ["mrHeadSha"],
    "D21": ["mrHeadSha", "artifactDigest"],
    "D22": ["mrHeadSha", "artifactDigest"],
    "D23": ["artifactDigest"],
    "D24": ["artifactDigest"],
    "D25": ["artifactDigest"],
    "D26": ["artifactDigest"],
    "D27": ["mrHeadSha", "mergeCommitSha", "artifactDigest"],
    "D28": ["artifactDigest", "previousStableDigest"],
    "D29": ["artifactDigest", "previousStableDigest"],
    "D30": ["artifactDigest", "previousStableDigest"],
    "D31": ["artifactDigest", "previousStableDigest"],
    "D32": ["artifactDigest"],
    "X01": ["artifactDigest", "jiraRevision"],
}

# Extra controls turn release-critical prose into independently verifiable rules.
# Tuple: suffix, description, verifier, subject type, revision binding, failure class.
EXTRA_CONTROLS = {
    "C02": [
        ("jira-access", "Jira service identity can read the exact task.", "jira", "jira-access", "jiraRevision", "external-unavailable"),
        ("git-baseline", "The configured repository and pinned Git baseline are readable.", "git", "git-revision", "gitSha", "external-unavailable"),
        ("tool-identities", "Runner, Hermes and deployment identities match the allowlist.", "file", "identity-readiness", "baselineRevision", "verification-failed"),
    ],
    "D02": [
        ("red-test", "The new test fails for the expected defect or missing behavior.", "file", "red-test-report", "gitSha", "test-design-defect"),
    ],
    "D13": [
        ("required-jobs", "Every required CI security job exists on the exact pipeline SHA.", "gitlab-pipeline", "required-job-manifest", "pipelineId", "external-evidence-invalid"),
        ("sast", "SAST has no unapproved blocking findings.", "gitlab-pipeline", "sast-report", "pipelineId", "security-implementation-defect"),
        ("dependencies", "Dependency and license policies pass.", "gitlab-pipeline", "dependency-policy-report", "pipelineId", "security-implementation-defect"),
        ("secrets", "Secret scanning has no verified leak.", "gitlab-pipeline", "secret-scan-report", "pipelineId", "security-implementation-defect"),
        ("container", "Container scanning has no unapproved blocking finding.", "gitlab-pipeline", "container-scan-report", "pipelineId", "security-implementation-defect"),
    ],
    "D20": [
        ("approval-head", "GitLab approval is bound to the current MR HEAD SHA.", "gitlab-approval", "mr-approval", "mrHeadSha", "stale-revision"),
        ("discussions", "All resolvable merge request discussions are resolved.", "gitlab-mr", "mr-discussions", "mrHeadSha", "verification-failed"),
    ],
    "D21": [
        ("immutable-manifest", "The release candidate manifest resolves to one immutable OCI digest.", "oci-registry", "oci-manifest", "artifactDigest", "external-evidence-invalid"),
        ("source-binding", "The release candidate is built from the approved MR HEAD.", "oci-registry", "artifact-source-binding", "artifactDigest", "stale-revision"),
    ],
    "D22": [
        ("sbom", "The release candidate has a complete machine-readable SBOM.", "file", "sbom", "artifactDigest", "security-implementation-defect"),
        ("provenance", "Provenance binds source, builder, build policy and artifact digest.", "file", "slsa-provenance", "artifactDigest", "security-implementation-defect"),
        ("signature", "The OCI signature verifies against the allowed signer identity.", "file", "artifact-signature", "artifactDigest", "security-implementation-defect"),
        ("policy-versions", "Scanner, policy and tool versions are recorded.", "file", "supply-chain-policy", "artifactDigest", "verification-failed"),
        ("vulnerabilities", "No unapproved blocking vulnerability remains.", "file", "vulnerability-policy-report", "artifactDigest", "security-implementation-defect"),
    ],
    "D25": [
        ("release-notes", "Release notes and known issues are complete.", "file", "release-notes", "artifactDigest", "operational-readiness-defect"),
        ("recovery-plan", "Rollback and roll-forward procedures identify exact digests.", "file", "recovery-plan", "artifactDigest", "operational-readiness-defect"),
        ("telemetry", "Dashboard, alerts and runtime ownership are ready.", "file", "telemetry-readiness", "artifactDigest", "operational-readiness-defect"),
        ("support", "Support owner and handoff are recorded.", "file", "support-handoff", "artifactDigest", "operational-readiness-defect"),
        ("migration", "Applicable migration and backup/restore evidence is verified.", "file", "migration-readiness", "artifactDigest", "operational-readiness-defect"),
    ],
    "D28": [
        ("canary-contract", "Canary target, percentage, duration, thresholds and abort criteria are pinned.", "deployment", "canary-contract", "artifactDigest", "staging-defect"),
        ("previous-digest", "The previous stable digest is deployable before canary starts.", "oci-registry", "previous-stable-artifact", "previousStableDigest", "operational-readiness-defect"),
        ("resource-lock", "The environment deployment resource lock is held.", "deployment", "deployment-lock", "artifactDigest", "staging-defect"),
    ],
    "D29": [
        ("observation-window", "The minimum canary observation window completed.", "observation", "canary-window", "artifactDigest", "post-deploy-failure"),
        ("thresholds", "Health, error and latency promotion thresholds pass.", "observation", "canary-thresholds", "artifactDigest", "post-deploy-failure"),
        ("newer-deployment", "No newer deployment supersedes this promotion decision.", "deployment", "deployment-order", "artifactDigest", "stale-revision"),
    ],
    "D30": [
        ("same-digest", "Full deployment promotes the exact canary digest without rebuilding.", "deployment", "deployment-digest", "artifactDigest", "stale-revision"),
        ("deployment-lock", "Full deployment owns the environment resource lock.", "deployment", "deployment-lock", "artifactDigest", "staging-defect"),
        ("not-outdated", "Outdated deployment protection accepts this deployment ID.", "deployment", "deployment-order", "artifactDigest", "stale-revision"),
    ],
    "D31": [
        ("runtime-version", "Runtime health and version expose the deployed digest and source SHA.", "runtime", "runtime-version", "artifactDigest", "post-deploy-failure"),
        ("runtime-errors", "Post-deploy logs and metrics contain no blocking regression.", "observation", "postdeploy-observation", "artifactDigest", "post-deploy-failure"),
        ("rollback-ready", "The previous stable digest and restoration procedure remain executable.", "deployment", "rollback-readiness", "previousStableDigest", "operational-readiness-defect"),
        ("rollback-restored", "After a post-deploy failure, restore the previous stable digest and prove runtime recovery before routing the defect.", "runtime", "runtime-restoration", "previousStableDigest", "rollback-recovery-failed", "failure-only"),
    ],
    "D32": [
        ("observation", "The configured operation observation window completes successfully.", "observation", "operation-window", "artifactDigest", "post-deploy-failure"),
        ("value", "Measured outcome and production feedback are recorded without inventing ROI.", "file", "value-observation", "artifactDigest", "verification-failed"),
    ],
}


def phase_profile(phase_id: str) -> str:
    return {"C": "common", "F": "feature", "B": "bug", "D": "delivery", "X": "closure"}[phase_id[0]]


def verifier_for(phase_id: str) -> tuple[str, str, str]:
    if phase_id in {
        "C01",
        "C04",
        "C05",
        "C06",
        "C07",
        "F01",
        "F04",
        "F05",
        "F06",
        "F07",
        "F08",
        "F09",
        "F10",
        "F11",
        "F12",
        "F13",
        "F14",
        "F15",
        "F16",
        "B02",
        "B03",
        "B04",
        "B05",
        "B06",
        "B07",
        "B08",
        "B09",
        "B10",
        "D02",
        "D03",
        "D04",
        "D08",
        "D15",
        "D16",
        "D17",
        "D18",
        "D19",
        "D25",
        "X02",
        "X03",
        "X04",
    }:
        return "file", "document", "baselineRevision"
    if phase_id in {"C02", "C08", "X01"}:
        return "jira", "jira-issue", "jiraRevision"
    if phase_id in {"C03", "F02", "D01", "D09", "D10"}:
        return "git", "git-revision", "gitSha"
    if phase_id == "F03":
        return "file", "dependency-inventory", "baselineRevision"
    if phase_id == "B01":
        return "file", "reproduction-record", "baselineRevision"
    if phase_id in {"D05", "D06", "D07"}:
        return "file", "test-report", "gitSha"
    if phase_id in {"D11", "D12", "D13"}:
        return "gitlab-pipeline", "pipeline", "pipelineId"
    if phase_id in {"D14", "D20", "D27"}:
        return "gitlab-mr", "merge-request", "mrHeadSha"
    if phase_id == "D26":
        return "human-approval", "release-approval-set", "artifactDigest"
    if phase_id == "D21":
        return "oci-registry", "oci-artifact", "artifactDigest"
    if phase_id == "D22":
        return "file", "attestation", "artifactDigest"
    if phase_id in {"D23", "D28", "D30"}:
        return "deployment", "deployment", "artifactDigest"
    if phase_id in {"D24", "D31"}:
        return "runtime", "runtime", "artifactDigest"
    if phase_id in {"D29", "D32"}:
        return "observation", "observation", "artifactDigest"
    raise ValueError(f"No verifier mapping for {phase_id}")


def allowed_tools(role: str, verifier: str) -> list[str]:
    by_role = {
        "Business Analyst": ["jira-read", "file-read", "file-write"],
        "Architect Security": ["jira-read", "git-read", "gitlab-read", "file-read", "file-write"],
        "Developer": ["git-read", "git-write", "terminal", "file-read", "file-write"],
        "QA": ["terminal", "runtime-read", "gitlab-read", "file-read", "file-write"],
        "Reviewer": ["git-read", "gitlab-read", "file-read", "file-write"],
        "Release Ops": ["gitlab-read", "deployment", "runtime-read", "file-read", "file-write"],
        "Process Improver": ["jira-read", "file-read", "file-write"],
    }
    tools = list(by_role[role])
    if verifier not in {"report", "file"}:
        tools.append(f"{verifier}-read")
    return sorted(set(tools))


def make_phase(definition: tuple[str, str, str, str], order: int) -> dict[str, Any]:
    phase_id, name, role, purpose = definition
    verifier, subject_type, revision_binding = verifier_for(phase_id)
    prefix = phase_id.lower()
    check_ids = [f"{prefix}-action-complete", f"{prefix}-evidence-verified", f"{prefix}-revision-bound"]
    instructions = [
        {
            "instructionId": f"{prefix}-01-inputs",
            "description": f"Read and pin every approved input required to: {purpose}",
            "allowedTools": allowed_tools(role, verifier),
            "requiredInputs": ["current phase contract", "pinned task revision"],
            "expectedOutputs": ["input revision set"],
            "sideEffectClass": "read-only",
            "timeoutSeconds": 300,
            "retryPolicy": {"maxAttempts": 2, "retryOn": ["transient-unavailable"]},
        },
        {
            "instructionId": f"{prefix}-02-execute",
            "description": purpose,
            "allowedTools": allowed_tools(role, verifier),
            "requiredInputs": ["input revision set"],
            "expectedOutputs": [subject_type],
            "sideEffectClass": "controlled-write",
            "timeoutSeconds": 1800,
            "retryPolicy": {"maxAttempts": 1, "retryOn": []},
        },
        {
            "instructionId": f"{prefix}-03-verify",
            "description": f"Verify the {subject_type} with the configured {verifier} verifier.",
            "allowedTools": allowed_tools(role, verifier),
            "requiredInputs": [subject_type, revision_binding],
            "expectedOutputs": ["deterministic verification result"],
            "sideEffectClass": "read-only",
            "timeoutSeconds": 600,
            "retryPolicy": {"maxAttempts": 2, "retryOn": ["transient-unavailable"]},
        },
        {
            "instructionId": f"{prefix}-04-report",
            "description": "Build phase-report/v2 using only the current contract IDs and verified evidence.",
            "allowedTools": ["file-read", "file-write", "project-workflow-submit"],
            "requiredInputs": ["deterministic verification result"],
            "expectedOutputs": ["phase-report/v2"],
            "sideEffectClass": "controller-write",
            "timeoutSeconds": 300,
            "retryPolicy": {"maxAttempts": 1, "retryOn": []},
        },
    ]
    checks = [
        {
            "checkId": check_ids[0],
            "description": "Every required instruction completed under the current phase contract.",
            "verifierType": "report",
            "subjectType": "action-set",
            "requiredStatus": "passed",
            "revisionBinding": "catalogRevision",
            "applicability": "required",
            "failureClass": "phase-incomplete",
        },
        {
            "checkId": check_ids[1],
            "description": f"The required {subject_type} exists and passes deterministic verification.",
            "verifierType": verifier,
            "subjectType": subject_type,
            "requiredStatus": "passed",
            "revisionBinding": revision_binding,
            "applicability": "conditional" if phase_id in {"F07", "F08", "F10", "D18"} else "required",
            "failureClass": "external-evidence-invalid"
            if verifier not in {"file", "report"}
            else "verification-failed",
        },
        {
            "checkId": check_ids[2],
            "description": "Evidence and decisions are bound to the current immutable subject revision.",
            "verifierType": "report",
            "subjectType": "revision-set",
            "requiredStatus": "passed",
            "revisionBinding": revision_binding,
            "applicability": "required",
            "failureClass": "stale-revision",
        },
    ]
    evidence = [
        {
            "requirementId": f"{prefix}-e01-primary",
            "description": f"Primary verified {subject_type} for {name}.",
            "type": subject_type,
            "checkIds": [check_ids[1]],
            "required": True,
            "revisionBinding": revision_binding,
            "maxAgeSeconds": 86400,
        },
        {
            "requirementId": f"{prefix}-e02-audit",
            "description": "Machine-readable audit record for actions, policy versions and revisions.",
            "type": "audit-record",
            "checkIds": [check_ids[0], check_ids[2]],
            "required": True,
            "revisionBinding": "catalogRevision",
            "maxAgeSeconds": 86400,
        },
    ]
    for index, control in enumerate(EXTRA_CONTROLS.get(phase_id, []), start=5):
        suffix, description, control_verifier, control_subject, control_binding, failure_class, *flags = control
        applicability = flags[0] if flags else "required"
        instruction_id = f"{prefix}-{index:02d}-{suffix}"
        check_id = f"{prefix}-{suffix}"
        requirement_id = f"{prefix}-e-{suffix}"
        instructions.append(
            {
                "instructionId": instruction_id,
                "description": description,
                "allowedTools": allowed_tools(role, control_verifier),
                "requiredInputs": [control_binding, "current phase contract"],
                "expectedOutputs": [control_subject],
                "sideEffectClass": "compensating-write" if applicability == "failure-only" else "read-only",
                "applicability": applicability,
                "timeoutSeconds": 600,
                "retryPolicy": {"maxAttempts": 2, "retryOn": ["transient-unavailable"]},
            }
        )
        checks.append(
            {
                "checkId": check_id,
                "description": description,
                "verifierType": control_verifier,
                "subjectType": control_subject,
                "requiredStatus": "passed",
                "revisionBinding": control_binding,
                "applicability": applicability,
                "failureClass": failure_class,
            }
        )
        evidence.append(
            {
                "requirementId": requirement_id,
                "description": f"Deterministic evidence: {description}",
                "type": control_subject,
                "checkIds": [check_id],
                "required": True,
                "revisionBinding": control_binding,
                "maxAgeSeconds": 86400,
            }
        )
    approval = HUMAN_GATES.get(phase_id)
    if approval:
        approval = {**approval, "allowSamePersonAcrossRoles": True, "decision": "approved"}
    return {
        "phaseId": phase_id,
        "name": name,
        "order": order,
        "profile": phase_profile(phase_id),
        "ownerRole": role,
        "purpose": purpose,
        "entryCriteria": ["task run is pinned to this catalog revision", "previous path phase passed"],
        "instructions": instructions,
        "checks": checks,
        "evidenceRequirements": evidence,
        "approvalRule": approval,
        "applicabilityRules": {"default": "required", "tailoringPhase": "C07"},
        "requiredRevisionBindings": sorted(
            {"catalogRevision", revision_binding, *REQUIRED_REVISION_BINDINGS.get(phase_id, [])}
        ),
        "transitionRules": {"PASS": "next-profile-path-phase", "ABORT": None},
        "failureRoutes": {
            "phase-incomplete": phase_id,
            "external-unavailable": phase_id,
            "change-scope": (
                {"feature": "F05", "bug": "B06"}
                if phase_id.startswith(("D", "X"))
                else ("F05" if phase_id.startswith("F") else "B06")
            ),
            "architecture-defect": "F12",
            "threat-model-defect": "F13",
            "test-design-defect": "F15" if phase_id.startswith(("F", "D")) else "B07",
            "implementation-defect": "D03",
            "security-implementation-defect": "D03",
            "build-defect": "D11",
            "staging-defect": "D23",
            "operational-readiness-defect": "D25",
            "verification-failed": "D03" if phase_id.startswith("D") else phase_id,
            "stale-revision": phase_id,
            "external-evidence-invalid": phase_id,
            "post-deploy-failure": "D28" if phase_id == "D29" else "D31",
        },
        "rollbackActions": ["preserve failed attempt", "execute configured compensating action before transition"],
        "metricsEvents": ["phase_started", "phase_decided"],
    }


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_catalog() -> dict[str, Any]:
    definitions = COMMON + FEATURE + BUG + DELIVERY + CLOSURE
    phases = [make_phase(definition, index) for index, definition in enumerate(definitions, start=1)]
    feature_path = [item[0] for item in COMMON + FEATURE + DELIVERY + CLOSURE]
    bug_path = [item[0] for item in COMMON + BUG + DELIVERY + CLOSURE]
    payload: dict[str, Any] = {
        "schemaVersion": "workflow-template/v2",
        "workflowVersion": "agentic-sdlc-v2",
        "catalogRevision": "",
        "profiles": {"feature": feature_path, "bug": bug_path},
        "phases": phases,
        "policy": {
            "taskKeyPattern": "^AAT-[1-9][0-9]*$",
            "allowedActorTypes": ["agent", "human"],
            "samePersonMayApproveMultipleRoles": True,
            "controllerOwnsDecision": True,
        },
    }
    payload["catalogRevision"] = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    return payload


def validate_counts(payload: dict[str, Any]) -> None:
    phases = payload["phases"]
    assert len(phases) == 70
    assert len(payload["profiles"]["feature"]) == 60
    assert len(payload["profiles"]["bug"]) == 54
    assert sum(len(item["instructions"]) for item in phases) >= 260
    assert sum(len(item["checks"]) for item in phases) >= 190
    assert sum(len(item["evidenceRequirements"]) for item in phases) >= 130
    assert len({item["phaseId"] for item in phases}) == 70
    phase_map = {item["phaseId"]: item for item in phases}
    for profile, path in payload["profiles"].items():
        gates = [phase_id for phase_id in path if phase_map[phase_id]["approvalRule"]]
        assert len(gates) == 5, (profile, gates)


def main() -> None:
    payload = build_catalog()
    validate_counts(payload)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "path": str(OUTPUT),
                "catalogRevision": payload["catalogRevision"],
                "phases": len(payload["phases"]),
                "featurePath": len(payload["profiles"]["feature"]),
                "bugPath": len(payload["profiles"]["bug"]),
            }
        )
    )


if __name__ == "__main__":
    main()
