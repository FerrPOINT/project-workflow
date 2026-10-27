"""Opt-in instruction preset for one Tracker task; no installation or dispatch.

The existing CLI catalog supplies identities only. Its pinned source is never
rewritten or claimed as the source of these Workflow-owned instructions.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from project_workflow.infrastructure.db.managed_catalog import ManagedMode
from project_workflow.infrastructure.single_task_delivery_instructions import (
    CRITICAL_BUSINESS_REVIEW,
    FIRST_STEP,
    PM_CONFIRMATION_CHECKS,
    PM_CONFIRMATION_EVIDENCE,
    PM_CONFIRMATION_INSTRUCTIONS,
    PM_CRITICAL_REVIEW,
    PM_DRAFT_CHECKS,
    PM_DRAFT_EVIDENCE,
    PM_DRAFT_INSTRUCTIONS,
    PM_PHASE_REPORT,
    PM_PUBLISH_INSTRUCTION,
    artifact_instruction,
    context_instruction,
    terminal_instruction,
)

PROFILE_KEY = "single-task-v1"
IDENTITY_CATALOG = Path(__file__).resolve().parents[1] / "references/base_sdlc_catalog_cli_v4.json"
ACTIVE_MODES = {
    "project_manager": ("draft",),
    "analyst": ("analysis",),
    "architect": ("decomposition",),
    "developer": ("initial", "rework"),
    "reviewer": ("delivery",),
    "tester": ("delivery",),
    "devops": ("delivery",),
}

SINGLE_TASK = (
    "This preset works on ONE Tracker task throughout. Never create children, decomposition cards, "
    "parent/dependency links for a delivery DAG, aggregate work or integration barriers. Do not activate "
    "integration or integration_rework modes. The Architect mode key decomposition means architecture and "
    "an implementation plan inside this task only. Stages are Draft, Backlog, Analysis, Architecture, "
    "Development, Review, Testing, Rework, Deployment. Status is separately Ready, InProgress or Completed; "
    "waiting_reason and runtime/agent state are separate observations, never substitute statuses. "
    "Only a real Tracker receipt establishes a business transition; do not set InProgress yourself on startup. "
    "Use the ordinary terminal with project-workflow, task-tracker and cicd-cli as actually installed and "
    "authorized. Do not modify original Hermes, install skills or infer capabilities from their names. "
    "Existing skill names are references, not authorization to execute legacy multi-task instructions."
)
REPORT = (
    "Submit only actual completed phase work with project-workflow --json step --task <workflow-task-key>"
    " --operation-key <stable-key> --expected-version <last-returned-version> --report -. Supply report "
    "text on stdin. Before submission, check EVERY required_check against actual evidence and include the"
    " required_evidence: reference saved alternatives/tradeoffs when they exist, actual blockers and the "
    "no-additional-tasks check; do not invent alternatives, checks or evidence. Inspect the returned "
    "verdict, missing, blockers, phase and version. A known PARTIAL is not phase acceptance: do the "
    "missing work or correct its report in the SAME execution, using the returned version and a NEW "
    "operation key ONLY for a new corrected report body. Do not request owner consent or claim "
    "preparation complete while preparation remains PARTIAL. After an unknown response retain exactly "
    "that key, version and report; read back history for the operation. Provider/transport failure or "
    "unknown acceptance is NOT a known PARTIAL and does not permit automatic resubmission. Do not select "
    "a replacement key merely because acceptance is unknown. Follow the returned current phase."
)
ACTIONS = {
    ("analyst", "analysis"): [
        "Analyze the owner's confirmed requirements and sources for this task. Separate facts from assumptions; "
        "describe actors, glossary, data ownership, invariants and permission boundaries without expanding scope.",
        "Review ambiguities and contradictions; map each requirement to measurable positive, negative, boundary, "
        "permission and failure acceptance cases. Resolve routine analysis decisions independently; a material "
        "business change goes back to PM for a new exact owner-confirmed revision.",
        "Produce the analysis report and requirement/criterion/verification coverage matrix for this "
        "task=root. Freeze architecture input references without creating more tasks. Prepare "
        "result.role=analyst with a real analysis ArtifactReceipt for the existing delivery proposal; "
        "do not borrow scheduler credentials or use scheduler Analysis submit as the agent producer.",
    ],
    ("architect", "decomposition"): [
        "Inspect the existing implementation and reuse suitable components. Trace producer, storage, API, "
        "consumer and failure paths against the analysis and confirmed acceptance criteria of this one task.",
        "Record architecture decisions, interfaces/dataflow, compatibility, security boundaries, migration "
        "needs if any, risks and rollback. Compare meaningful options and tradeoffs; choose within approved "
        "requirements and flag contradictions rather than silently changing business scope.",
        "The existing decomposition mode outputs ONLY an architecture and ordered implementation plan inside "
        "this same task: affected modules/paths, verification steps and criterion coverage. Plan steps are text, "
        "not child creation. No delivery DAG, materialization, aggregate run or child completion barrier. "
        "Save architecture/plan evidence for the Developer initial mode on this task.",
    ],
    ("developer", "initial"): [
        "Read the approved architecture/plan and repository rules in the authorized checkout. Verify source "
        "SHA, branch, allowed paths and input revisions; implement the acceptance criteria of this one task.",
        "Make the smallest coherent change using existing project patterns. Add meaningful focused tests for "
        "behavior and failure paths; reproduce the failure before fixing where practical. Run relevant checks "
        "and inspect the diff. Never weaken checks to obtain a pass.",
        "Preserve unrelated work and provide the exact candidate SHA/artifact, changed files, test results, "
        "criterion coverage and known limitations for independent Review. Do not claim completion of the task "
        "or deployment from implementation success.",
    ],
    ("developer", "rework"): [
        "Read the immutable findings from Review or Testing and the current Rework cycle on this same task. "
        "Match findings to the rejected candidate and approved requirements; reproduce each defect first.",
        "Fix every accepted finding in the permitted checkout, add regression coverage and rerun affected "
        "checks. Record a finding -> change -> verification matrix and explain any unresolved finding as a blocker.",
        "Publish the exact new candidate and evidence. Successful Rework always returns to Review / Ready, "
        "then a fresh Testing run, including defects originally discovered in Testing. Previous Review/Testing "
        "passes do not qualify a changed candidate; never skip directly to Testing or Deployment.",
    ],
    ("reviewer", "delivery"): [
        "Independently inspect the exact candidate diff, architecture, approved criteria, contracts, security "
        "and test evidence. Follow dataflow and failure paths; run proportionate checks when needed.",
        "For defects record immutable findings with severity, exact location/ref, reproduction, expected vs "
        "actual result and acceptance criterion. Choose needs_rework with at least one actionable defect, or "
        "passed with evidence. Do not repair the candidate in the Reviewer role or hide defects in a passed report.",
        "Defects go to Rework / Ready on the same task. After Developer rework perform Review again against "
        "the new candidate; a pass goes to Testing / Ready for a fresh test run. Do not reuse old candidate approval.",
    ],
    ("tester", "delivery"): [
        "Test the exact independently reviewed candidate against the approved acceptance matrix. Exercise "
        "positive, negative, boundary, permission and failure/recovery scenarios; distinguish executed, failed "
        "and untested cases. Missing test environment or evidence is a blocker, not a product pass.",
        "For defects record immutable findings with severity, exact location/ref, reproduction, expected vs "
        "actual result and criterion. Choose needs_rework with actionable findings, or passed with actual results "
        "and evidence covering acceptance. Do not fix code in the Tester role.",
        "Defects go to Rework / Ready on the same task; the repaired candidate must pass Review and Testing "
        "again before Deployment. A previous Testing pass or selective retest of findings cannot replace the "
        "required acceptance checks for the new candidate.",
    ],
    ("devops", "delivery"): [
        "Verify the exact candidate SHA/artifact accepted by Review and Testing and the authorized deployment "
        "target. Through the installed cicd-cli inspect actual help and supported operations before invoking "
        "them; this preset does not invent build/deploy/health commands. Record immutable artifact provenance.",
        "Build/release and deploy the approved artifact through the authorized existing CI/CD procedure. "
        "Read actual deployment receipt/target/revision, verify health and run deployed acceptance for this "
        "task. Preserve rollback references and report failed/unknown operations without claiming success.",
        "Terminal evidence is limited to this task's exact artifact, deployment, health and acceptance. "
        "Do not implement features, perform architecture decomposition or aggregate child outputs. Complete "
        "only when artifact/deployment/health/acceptance evidence all match the accepted candidate and target.",
    ],
}

ROLE_CHECKS = {
    "analyst": [
        "Every approved requirement has a source and positive/negative/boundary verification coverage.",
        "Analysis assumptions and permission/failure cases are explicit; material contradictions are resolved.",
    ],
    "architect": [
        "Architecture traces existing components, interfaces, dataflow, risks and rollback for this task.",
        "An ordered implementation plan covers every criterion without child cards or integration barriers.",
    ],
    "developer": [
        "The exact candidate implements approved criteria and relevant checks passed with recorded outputs.",
        "For rework, every finding has a verified fix or explicit blocker; new Review and Testing are required.",
    ],
    "reviewer": [
        "The decision covers the exact candidate, contracts, failure paths and approved acceptance criteria.",
        "passed has no unresolved defects; needs_rework includes at least one immutable actionable finding.",
    ],
    "tester": [
        "Results identify actual candidate/environment and executed, failed and untested acceptance cases.",
        "passed covers required acceptance; needs_rework includes immutable reproduction and expected/actual results.",
    ],
    "devops": [
        "Artifact provenance and deployment receipt match the exact reviewed and tested candidate and target.",
        "Health and deployed acceptance passed with actual evidence; rollback references are preserved.",
    ],
}
ROLE_EVIDENCE = {
    "analyst": ["Analysis report, input references and requirement/criterion/verification coverage matrix."],
    "architect": ["Architecture decisions, dataflow, ordered plan, criterion coverage and rollback references."],
    "developer": ["Exact candidate SHA, diff/files and test outputs; rework finding/change/verification matrix."],
    "reviewer": ["Independent review of exact SHA and passed decision or frozen actionable findings."],
    "tester": ["Acceptance matrix with candidate/environment/results and passed decision or frozen defects."],
    "devops": ["Exact artifact provenance, deployment receipt/target, health results and deployed acceptance."],
}


def load_single_task_professions() -> list[dict[str, Any]]:
    """Return fresh opt-in definitions using existing mode/phase shapes.

    This is intentionally not a ManagedCatalog: that public contract requires
    eleven modes and pins a different terminal policy. Activation is integrator-owned.
    """
    donor = json.loads(IDENTITY_CATALOG.read_text(encoding="utf-8"))
    result = []
    for original in donor["workflows"]:
        role = original["role_key"]
        workflow = copy.deepcopy(original)
        workflow.pop("terminal_contract", None)
        workflow["description"] = f"{PROFILE_KEY}: {role} for one Tracker task; opt-in instructions."
        workflow["modes"] = []
        for original_mode in original["modes"]:
            if original_mode["key"] not in ACTIVE_MODES[role]:
                continue
            mode = copy.deepcopy(original_mode)
            mode_key = mode["key"]
            if role == "architect":
                mode["name"] = "Architecture and plan"
            mode["execution_scopes"] = [
                "business"
                if role
                in {
                    "project_manager",
                    "analyst",
                    "architect",
                }
                else "delivery"
            ]
            opening = (
                "Workflow step and task context",
                [FIRST_STEP, context_instruction(role), SINGLE_TASK, REPORT],
                ["The returned Workflow step is admitted in the assigned namespace.",
                 "The one Tracker task, current stage/status and input references match."],
                ["Actual first Workflow step response and task/input references."],
            )
            if role == "project_manager":
                contents = [
                    (opening[0], [FIRST_STEP, context_instruction(role), SINGLE_TASK,
                                  PM_CRITICAL_REVIEW, PM_PHASE_REPORT], opening[2], opening[3]),
                    ("Role work on one task",
                     [*PM_DRAFT_INSTRUCTIONS, PM_PUBLISH_INSTRUCTION,
                      "Prepare the FULL saved requirements document and its exact revision/content_hash for "
                      "owner review in phase 3. Include scope, acceptance criteria, choices/tradeoffs and open "
                      "issues. This preparation is not consent and does not complete the PM execution.",
                      PM_PHASE_REPORT], PM_DRAFT_CHECKS, PM_DRAFT_EVIDENCE),
                    ("Owner confirmation before final Workflow report",
                     [*PM_CONFIRMATION_INSTRUCTIONS, terminal_instruction(role)],
                     PM_CONFIRMATION_CHECKS, PM_CONFIRMATION_EVIDENCE),
                ]
            else:
                contents = [
                    opening,
                    ("Role work on one task", ACTIONS[(role, mode_key)] + [CRITICAL_BUSINESS_REVIEW, REPORT],
                     ROLE_CHECKS[role] + [
                         "Unresolved blockers remain explicit; no additional Tracker tasks were created."],
                     ROLE_EVIDENCE[role]),
                    ("Workflow report and Tracker handoff",
                     [REPORT, artifact_instruction(role), terminal_instruction(role)],
                     ROLE_CHECKS[role] + ["The role result is ready for Workflow evaluation with actual evidence.",
                                         "The proposed outcome and next stage/status comply with this single-task role."
                                         ],
                     ROLE_EVIDENCE[role] + ["Final role report and explicit handoff dependencies."]),
                ]
            for phase, (name, instructions, checks, evidence) in zip(mode["phases"], contents, strict=True):
                phase.update(
                    name=name,
                    description=f"{PROFILE_KEY}: {role}/{mode_key}; {name}.",
                    instructions=[
                        {"description": text, "skills": ["project-workflow-executor", "tracker-operator"]}
                        for text in instructions
                    ],
                    checks=list(checks),
                    evidence=list(evidence),
                )
            ManagedMode.model_validate(mode)
            workflow["modes"].append(mode)
        result.append(workflow)
    return result
