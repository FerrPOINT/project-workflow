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

FIRST_STEP = (
    "Your first working operation is terminal -> project-workflow --json step --task <workflow-task-key> "
    "without --report, in the assigned profession namespace. Use the returned first/current Workflow step "
    "before reading Tracker, discussing requirements, editing files or invoking CI/CD. The launcher supplies "
    "the namespace and Workflow task key mapped to the one canonical Tracker task UUID; never guess either. "
    "If issued a scoped runtime context, use the existing --operation-key <original-key> "
    "--runtime-request <private-request-json> --execution-token-file <private-token-file> options, preserving "
    "the supplied assignment/fence and report=null; never downgrade to human or local DB mode. "
    "An unavailable or rejected step is a blocker, not permission to continue."
)
CONTEXT = (
    "After the Workflow step, read task-tracker sdlc context --task <task-uuid>, "
    "task-tracker sdlc requirements --task <task-uuid> and task-tracker sdlc questions --task <task-uuid> "
    "with the authorized task identity. Read all available comments and attachments using permitted existing "
    "task-tracker comment list <issue-id> and task-tracker attachment list --issue <issue-id>; follow attachment "
    "references only with authorized access. Missing required input/access is an explicit blocker. "
    "Verify the same task UUID, approved revision/hash, assigned role/mode, current stage/status and predecessor "
    "evidence. An absent requirements revision is normal only while PM creates the first Draft."
)
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
    "Submit each completed phase report via terminal -> project-workflow --json step --task <workflow-task-key> "
    "--report <report-text> in the same assigned namespace. Include executed instruction/check coverage, "
    "actual outputs, immutable evidence refs, exact input/candidate revisions and limitations. With issued "
    "runtime context include the existing --operation-key, --runtime-request and --execution-token-file options; "
    "request body.report must equal --report. Use distinct keys for distinct read/report operations, retain "
    "exact key/body for reconciliation, and never invent authority fields. Follow the returned current phase "
    "until an accepted complete=true; process exit or narrative success is insufficient. An uncertain effect "
    "requires authorized readback of the original operation before retry, not a fresh key. Workflow history "
    "can show progress but is not a Tracker transition receipt."
)
WAITING = (
    "If work is blocked, leave the phase unfinished and record the concrete missing input/capability and "
    "waiting_reason through an actually available checkpoint mechanism; if none exists, report that dependency "
    "to the operator. PM owns ordinary business clarification; other roles decide routine technical details "
    "within approved scope, sending critical business contradictions to PM and infrastructure blockers to the "
    "operator. Do not manufacture a checkpoint command, approval, transition or receipt."
)
RECEIPT = (
    "Read back the real Tracker operation receipt using the supported CLI for that operation, then reconcile "
    "task-tracker sdlc context --task <task-uuid>. Match task UUID, original operation key/request, input "
    "revision/hash, stage/cycle and evidence to the accepted result and its explicitly allowed next stage AND "
    "status. A historical operation receipt and a subsequently changed context must be reported separately; "
    "never replay a transition to force the old state. Unknown acceptance remains unconfirmed. "
    "Generic Task patch, issue transition, board move and status edit are forbidden handoff substitutes."
)

# These are instruction targets, not a new lifecycle implementation or wire DTO.
TARGETS = {
    "project_manager": "Backlog / Ready after exact owner confirmation, then Analysis / Ready by Tracker pickup",
    "analyst": "Architecture / Ready",
    "architect": "Development / Ready of this same task",
    "developer": "Review / Ready of this same task (both initial and rework)",
    "reviewer": "Testing / Ready on passed; Rework / Ready on needs_rework",
    "tester": "Deployment / Ready on passed; Rework / Ready on needs_rework",
    "devops": "Deployment / Completed of this same task",
}

ACTIONS = {
    ("project_manager", "draft"): [
        "Be a full brainstorming partner within Draft / InProgress: start from the owner's idea, reflect the "
        "goal and explore in small iterations. Offer a few meaningful alternatives with tradeoffs; surface "
        "contradictions and test assumptions together. Ask one useful question at a time and accept free-form "
        "answers. No long mandatory questionnaire, preselection, default selected answer or implied consent.",
        "Brainstorming, clarification and requirements review all remain inside draft mode and Draft stage. "
        "Do not advance the task to Analysis merely because a question was answered. Read the immutable initial "
        "request through task-tracker sdlc input --task <task-uuid>; distinguish facts, preferences and open choices.",
        "Converge on the business result, actors, scope/non-goals, constraints and measurable acceptance "
        "criteria at the owner's pace. Keep a concise evolving Draft with a clear title. Record agreed choices "
        "and unresolved contradictions without selecting a solution on the owner's behalf.",
        "When clarification is needed, publish a focused question using task-tracker sdlc question publish "
        "--task <task-uuid> --from-file <question.json>. Publish the evolving requirements revision using "
        "task-tracker sdlc revision publish "
        "--task <task-uuid> --from-file <revision.json>. Use the actual existing strict payloads and authorized "
        "ownership/version/idempotency fields; do not invent IDs or JSON fields. Read questions/requirements "
        "back and match the server revision/hash. After an uncertain publish, reconcile before another write.",
        "Review the exact saved requirements with the human owner: show the revision and content_hash, "
        "scope and acceptance criteria, alternatives rejected and any open issue. Request explicit confirmation "
        "of that exact revision/hash before handoff; silence, a conversational yes to another question or an "
        "agent's approval is not confirmation. Any content change invalidates the prior confirmation. "
        "PM must never confirm as the owner or use the owner's credentials.",
    ],
    ("analyst", "analysis"): [
        "Analyze the owner's confirmed requirements and sources for this task. Separate facts from assumptions; "
        "describe actors, glossary, data ownership, invariants and permission boundaries without expanding scope.",
        "Review ambiguities and contradictions; map each requirement to measurable positive, negative, boundary, "
        "permission and failure acceptance cases. Resolve routine analysis decisions independently; a material "
        "business change goes back to PM for a new exact owner-confirmed revision.",
        "Produce one analysis report and requirement -> criterion -> verification coverage matrix on this task. "
        "Freeze the input references for architecture; do not create additional Tracker tasks. Prepare the "
        "actual existing Analysis result payload only from supplied assignment, lease/fence, Workflow terminal "
        "receipt and architecture input hash. Missing authority/evidence fields remain blockers.",
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
    "project_manager": [
        "Draft has a server-saved exact revision/hash, clear scope and measurable acceptance criteria.",
        "Alternatives, tradeoffs and contradictions were reviewed without preselection or implied consent.",
        "Unanswered business questions remain explicit; owner confirmation is a separate exact action.",
    ],
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
    "project_manager": ["Saved Draft revision/hash, agreed choices, open questions and owner review presentation."],
    "analyst": ["Analysis report, input references and requirement/criterion/verification coverage matrix."],
    "architect": ["Architecture decisions, dataflow, ordered plan, criterion coverage and rollback references."],
    "developer": ["Exact candidate SHA, diff/files and test outputs; rework finding/change/verification matrix."],
    "reviewer": ["Independent review of exact SHA and passed decision or frozen actionable findings."],
    "tester": ["Acceptance matrix with candidate/environment/results and passed decision or frozen defects."],
    "devops": ["Exact artifact provenance, deployment receipt/target, health results and deployed acceptance."],
}


def terminal_instruction(role: str) -> str:
    common = (
        f"After accepted Workflow complete=true, the explicitly allowed next stage AND status are {TARGETS[role]}. "
    )
    if role == "project_manager":
        action = (
            "Wait for the human owner's exact revision/hash confirmation, then verify its real confirmation "
            "receipt and server-created Analysis intent via the supported owner readback and task-tracker sdlc "
            "intent --task <task-uuid>. Current Tracker CLI has no owner confirm or exact confirmation receipt "
            "command: report this missing capability immediately; do not fabricate a command. Context/intent "
            "are supporting readbacks, not substitutes for that receipt. No Analyst dispatch by PM."
        )
    elif role == "analyst":
        action = (
            "Use the existing task-tracker sdlc analysis result submit --task <task-uuid> --from-file <result.json> "
            "only with an explicitly authorized producer identity, then task-tracker sdlc analysis result "
            "operation --task <task-uuid> --key <original-key> to read its actual receipt. Current producer requires "
            "the scheduler identity; never borrow scheduler credentials or change identity to call it. Without "
            "an authorized caller, give the prepared typed result to the operator and report the credential "
            "dependency immediately; handoff remains incomplete. Validate actual server status vocabulary too; "
            "the existing Analysis endpoint is not acceptance of a new single-task status contract."
        )
    else:
        action = (
            "Request outcome passed"
            + (" or needs_rework with frozen findings" if role in {"reviewer", "tester"} else "")
            + " through a supported guarded Tracker terminal CLI, carrying the supplied assignment/revision/fence, "
            "original operation key, accepted Workflow result and exact evidence. Current Tracker CLI has no "
            "guarded terminal producer or operation receipt readback for this role: report the missing capability "
            "immediately and leave the business handoff incomplete. Do not print hypothetical CLI commands."
        )
    return common + action + " " + RECEIPT


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
            mode["execution_scopes"] = ["business" if role in {
                "project_manager", "analyst", "architect",
            } else "delivery"]
            contents = [
                ("Workflow step and task context", [FIRST_STEP, CONTEXT, SINGLE_TASK, REPORT],
                 ["The returned Workflow step is admitted in the assigned namespace.",
                  "The one Tracker task, current stage/status and input references match."],
                 ["Actual first Workflow step response and task/input references."]),
                ("Role work on one task", ACTIONS[(role, mode_key)] + [WAITING, REPORT],
                 ROLE_CHECKS[role] + ["Unresolved blockers remain explicit; no additional Tracker tasks were created."],
                 ROLE_EVIDENCE[role]),
                ("Workflow report and Tracker handoff", [REPORT, terminal_instruction(role)],
                 ROLE_CHECKS[role] + ["The role result is ready for Workflow evaluation with actual evidence.",
                  "The proposed outcome and next stage/status comply with this single-task role."],
                 ROLE_EVIDENCE[role] + ["Final role report and explicit handoff dependencies."]),
            ]
            for phase, (name, instructions, checks, evidence) in zip(mode["phases"], contents, strict=True):
                phase.update(
                    name=name, description=f"{PROFILE_KEY}: {role}/{mode_key}; {name}.",
                    instructions=[{"description": text, "skills": ["project-workflow-executor", "tracker-operator"]}
                                  for text in instructions], checks=list(checks), evidence=list(evidence),
                )
            ManagedMode.model_validate(mode)
            workflow["modes"].append(mode)
        result.append(workflow)
    return result
