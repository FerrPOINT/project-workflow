"""Runtime-only protocol projection; never rewrite the installed legacy catalog."""

from copy import deepcopy

from project_workflow.infrastructure import single_task_catalog as catalog
from project_workflow.infrastructure import single_task_delivery_instructions as delivery
from project_workflow.supervisor.models import Phase

FIRST = (
    "If only the Tracker task UUID is known, read task-tracker sdlc context --task <task-uuid> and take its "
    "server-issued workflow_task_key (SDLC-N); never guess the key or create another task. "
    "Read this task's current Workflow instructions using project-workflow --json step --task <workflow-task-key>. "
    "Use the permanently configured namespace and agent credential. Missing configuration or denied access is a "
    "blocker; never use a human token or local database fallback. No native binding or temporary files are required. "
    "Before reporting this phase, include an 'Actual first Workflow step response' block in the report evidence: "
    "copy the actual scalar fields from the successful no-report command's parsed stdout JSON: "
    "interaction_protocol, task, namespace_id, concrete_agent_ref, assignment_ref, execution_ref, "
    "business_task_ref, phase_code, version and status. The CLI prints these fields at top level, not inside "
    "an HTTP response envelope. Record the terminal command's exit status separately when available; it is not "
    "a Workflow JSON field. Compare these with the server-issued Workflow key and assigned task/namespace/agent; "
    "include the Tracker task/root UUID, stage/status and actual input references from the authorized Tracker "
    "reads. Validate identity fields by their own authority: Tracker context.assignment.assignment_id equals "
    "Workflow assignment_ref; Tracker context.assignment.agent_id equals Workflow concrete_agent_ref; "
    "Tracker context.task_id and root_task_id equal Workflow business_task_ref; Tracker workflow_task_key "
    "equals Workflow task. Tracker context.assignment.execution_id is the retained tracker_execution_id, "
    "NOT Workflow execution_ref. Workflow execution_ref is independently generated at enrollment; these "
    "two execution IDs are intentionally separate and are not required to be equal. Record both with their "
    "authority names; compare execution_ref only with the same Workflow enrollment/history, never with "
    "Tracker execution_id. A difference between these two IDs alone is not a blocker and does not authorize "
    "rebind, replacement IDs or another execution. Assignment version and Workflow cursor version are also "
    "separate counters; validate each against its own authority. Actual task/assignment/agent mismatches "
    "remain blockers. State an absent requirements revision as absent, not as invented evidence. The evidence is this "
    "already returned instruction read, not a future PASS verdict from the report being submitted. Never invent "
    "response values or substitute instruction text for the actual response; failed or mismatched reads remain "
    "blockers. Omit credentials from the report."
)
REPORT = (
    "Submit only actual completed phase work with project-workflow --json step --task <workflow-task-key> "
    "--operation-key <stable-key> --expected-version <last-returned-version> --report -. Supply report text on stdin. "
    "Before submission, check EVERY required_check against actual evidence and include the required_evidence: "
    "reference saved alternatives/tradeoffs when they exist, actual blockers and the no-additional-tasks check; "
    "do not invent alternatives, checks or evidence. Inspect the returned verdict, missing, blockers, phase and "
    "version. A known PARTIAL is not phase acceptance: do the missing work or correct its report in the SAME "
    "execution, using the returned version and a NEW operation key ONLY for a new corrected report body. "
    "Do not request owner consent or claim preparation complete while preparation remains PARTIAL. "
    "After an unknown response retain exactly that key, version and report; read back history for the operation. "
    "Provider/transport failure or unknown acceptance is NOT a known PARTIAL and does not permit automatic "
    "resubmission. Do not select a replacement key merely because acceptance is unknown. "
    "Follow the returned current phase."
)
WAIT = (
    "Wait for missing human input or final owner consent in the same conversation with this phase unfinished. "
    "An already saved answer or feedback may be applied to the Draft without final owner consent. "
    "Feedback is not confirmation. "
    "Revise and republish the whole document when needed; only explicit owner consent to the latest revision/hash "
    "permits PM completion. No checkpoint, native readback or Fleet rebind is required by this protocol."
)
PREPARATION_WAIT = WAIT.replace(
    "Wait for missing human input or final owner consent in the same conversation with this phase unfinished.",
    "Wait only for genuinely missing requirements input, leaving this phase unfinished. "
    "Report completed preparation with the FULL saved Draft revision/hash; "
    "do not wait for final owner consent in preparation. Request that exact confirmation in phase 3."
)
PREPARATION_REPORT = (
    "Brainstorming and owner feedback keep this same execution/assignment/cycle; no placeholder document or "
    "invented question is required. Apply saved answers and relevant feedback to the Draft. When substantive "
    "facts are sufficient, publish the next FULL requirements revision without asking for separate permission "
    "to save the draft. 'Not confirmation of the final revision' does not prohibit updating the Draft. "
    "Do not invent unresolved business choices; clarify only actual remaining gaps. " + REPORT +
    " Report only this completed preparation phase. After an accepted report, continue with the returned next "
    "phase in this SAME execution; do not stop merely because the phase changed. "
    "Wait only for genuinely missing input or owner confirmation required by the current phase. "
    "Actual owner confirmation belongs to phase 3 in this SAME execution. "
    "Never complete the PM Workflow or create another assignment/cycle merely to wait for consent."
)
FEEDBACK = (
    "Handle feedback by revising and publishing the document within the SAME execution, then present the FULL "
    "new saved revision/content_hash. Apply saved answers and relevant feedback without asking for separate "
    "permission to save the draft; publishing a Draft revision is NOT owner confirmation or PM completion. "
    "Any document change invalidates earlier consent. Free feedback and "
    "confirmation must not fabricate an answer ID, question or clarification request. Only actual unresolved "
    "gaps require clarification. Confirmation must be the real owner's saved receipt for the latest exact "
    "revision/hash, not a conversational assertion. Unresolved feedback keeps phase 3 unfinished; no final "
    "Workflow report is permitted yet. No native checkpoint or rebind is required."
)
# Retain the business-critical-review restrictions; only its legacy transport wording changes.
CRITICAL_REVIEW = delivery.PM_CRITICAL_REVIEW.replace(
    "including pre-document null/null checkpoints.", "including feedback before a saved document exists."
).replace(
    "Use the existing typed checkpoint/feedback/answer/confirmation path, then the normal guarded final PM Workflow "
    "report only after actual receipt readback.",
    "Use actual feedback and owner confirmation, then the normal guarded final PM Workflow report only after "
    "actual receipt readback. No native checkpoint/rebind is introduced by this protocol."
)
FINAL = (
    "Only after the human owner's actual confirmation, read task-tracker sdlc confirmation read --task <task-uuid> "
    "--revision <confirmed-revision>. Match latest revision/hash, owner and task. " + REPORT + " "
    "For this final report add --requirements-revision <confirmed-revision> "
    "--requirements-sha256 <confirmed-content-hash>; these exact values are frozen in the committed receipt. "
    "Owner confirmation leaves the task in Draft. Workflow verifies that exact Draft confirmation and returns its "
    "authoritative terminal receipt without moving Tracker. Only then submit "
    "task-tracker sdlc pm completion submit --task <task-uuid> --from-file - with JSON on stdin. "
    "Use ONLY these fields: interaction_protocol='configured-cli-v1'; fence={assignment_id,execution_id,agent_id,"
    "assignment_version} from fresh Tracker context.assignment, matched exactly to the Workflow terminal receipt; "
    "requirement_revision=terminal_receipt.requirements_revision; content_hash=terminal_receipt.requirements_sha256; "
    "namespace_id=terminal_receipt.namespace_id; workflow_execution_ref=terminal_receipt.execution_ref; "
    "workflow_operation_key=terminal_receipt.operation_key; workflow_result_version=terminal_receipt.result_version; "
    "idempotency_key=<one-stable-completion-key>. requirement_revision is singular in this Tracker request. "
    "Match fence.assignment_id to terminal_receipt.assignment_ref, fence.execution_id to "
    "terminal_receipt.tracker_execution_id (NOT Workflow execution_ref), fence.agent_id to "
    "terminal_receipt.concrete_agent_ref and fence.assignment_version to terminal_receipt.assignment_version. "
    "Do not paste a fabricated receipt or add native/lease fields. Tracker reads the terminal receipt "
    "server-to-server and performs atomic Draft -> Backlog / Ready. Read the exact operation using "
    "task-tracker sdlc pm completion operation --task <task-uuid> --key <same-completion-key>, then "
    "task-tracker sdlc pm completion read --task <task-uuid> and task-tracker sdlc context --task <task-uuid>. "
    "Verify the operation.result, completion read.current and fresh context agree on the same task/root and "
    "revision/hash, with stage=Backlog and status=Ready after completion. "
    "After unknown POST acceptance use original-key readback, never a new key or blind resubmit. "
    "Do not require Backlog before Workflow completion. A pasted receipt alone is not authority. "
    "Business completion requires a valid saved document, resolved questions and actual owner consent, not an "
    "external verifier checklist. Configured CLI readiness is a separate runtime check. Stop at Backlog / Ready; "
    "do not create Analysis intent, dispatch Analyst or confirm requirements as the owner."
)

# Retained preparation must not turn a complete brief into a mandatory questionnaire.
PM_PREPARATION_REPLACEMENTS = {
    "Offer a few meaningful alternatives with tradeoffs; surface contradictions and test assumptions together. "
    "Ask one useful question at a time and accept free-form answers.":
        "Offer alternatives with tradeoffs only when meaningful unresolved choices exist. "
        "Ask one useful question at a time only for actual incomplete or contradictory input; "
        "accept free-form answers. For a complete, consistent brief, proceed directly to requirements "
        "without clarification questions or invented alternatives.",
    "Brainstorm in small free-form iterations before a document exists;":
        "When clarification is needed, brainstorm in small free-form iterations before a document exists;",
    "Formal clarification requires an existing requirements revision:":
        "Formal clarification is conditional on an actual unresolved gap and requires an existing "
        "requirements revision:",
}
PM_PREPARATION_CHECK_REPLACEMENTS = {
    "Alternatives, tradeoffs and contradictions were reviewed without preselection or implied consent.":
        delivery.PM_DRAFT_CHECKS[1] + " Alternatives and tradeoffs were reviewed only when meaningful unresolved "
        "choices existed, without preselection or implied consent.",
    "Unanswered business questions remain explicit; owner confirmation is a separate exact action.":
        delivery.PM_DRAFT_CHECKS[2],
}
PM_PREPARATION_EVIDENCE_REPLACEMENTS = {
    "Saved Draft revision/hash, agreed choices, open questions and owner review presentation.":
        " ".join(delivery.PM_DRAFT_EVIDENCE) + " Choices/tradeoffs evidence is required only when meaningful "
        "unresolved choices existed; never invent questions, answers or alternatives.",
}

# Stored PM catalogs predate the current terminal policy. Replace only their known
# transport/routing clauses, so appended or interleaved security constraints survive.
PM_FINAL_REPLACEMENTS = {
    delivery.terminal_instruction("project_manager").split(" Verify accepted Workflow complete=true,")[0]: FINAL,
    " Verify accepted Workflow complete=true, then finalize the PM run. The allowed next "
    "stage AND status are Backlog / Ready, then Analysis / Ready through Tracker/Fleet pickup. "
    "Tracker may create an Analysis / Ready intent at consent, but Analyst reserve remains blocked "
    "until PM actual completion is observed. PM does not dispatch Analyst or create another PM cycle. ": " ",
    " Verify accepted Workflow complete=true, then finalize the PM run. The allowed next "
    "stage AND status are Backlog / Ready only. Stop at Backlog / Ready; do not request an Analysis "
    "intent, wait for Analyst pickup or treat either as a PM completion prerequisite. "
    "PM does not dispatch Analyst or create another PM cycle. ": " ",
}
PM_READBACK_CHECK = (
    "Direct authorized owner confirmation readback matches the latest task/revision/hash/owner in Draft; "
    "all actual feedback is resolved and no blockers remain."
)
PM_FINAL_CHECK = (
    "The FULL latest saved requirements document is valid, actual feedback and blocking questions are resolved, "
    "and real human owner confirmation matches the exact task/revision/hash/owner while Tracker remains in Draft."
)
PM_FINAL_PRECOMMIT = (
    "PRECOMMIT ASSESSMENT ONLY: evaluate the FULL latest saved requirements document, actual resolved feedback "
    "and blocking questions, and the real authorized human owner confirmation readback matching the exact "
    "task/revision/content_hash/owner while Tracker remains in Draft. Missing, stale, mismatched or fabricated "
    "document/consent/evidence must not pass. Preserve every additional security constraint. "
    "The server generates the terminal receipt only AFTER an accepted final verdict and commit. Tracker PM "
    "completion and its Backlog / Ready readback are SUBSEQUENT actions, NOT prerequisites or required evidence "
    "for this verdict. Do not require proof of those future actions or mark their absence as missing. "
    "This boundary does not grant PASS: judge every current required check/evidence against the actual report."
)
PM_FINAL_CHECK_REPLACEMENTS = {
    delivery.PM_CONFIRMATION_CHECKS[3]: PM_READBACK_CHECK,
    "Authorized typed checkpoint/resume and direct PM confirmation readback dependencies are satisfied; "
    "no blockers remain.": PM_READBACK_CHECK,
    delivery.PM_CONFIRMATION_CHECKS[4]: PM_FINAL_CHECK,
    "PM finalizes only; allowed next stage/status are Backlog / Ready then Analysis / Ready, not PM dispatch.":
        PM_FINAL_CHECK,
}
PM_FEEDBACK_EVIDENCE = (
    "Actual same-execution answer/feedback-to-revision references only when they occurred; "
    "no fabricated answers or mandatory clarification history for a complete brief."
)
PM_FINAL_EVIDENCE_REPLACEMENTS = {
    delivery.PM_CONFIRMATION_EVIDENCE[2]: PM_FEEDBACK_EVIDENCE,
    "Same-execution typed checkpoint/input references and feedback-to-revision history without fabricated answers.":
        PM_FEEDBACK_EVIDENCE,
}


def precommit_phase(source: Phase) -> Phase:
    """Keep the configured worker's post-commit commands out of the judge contract."""
    if source.code != "PM-DRAFT-03" or not any(FINAL in item.step for item in source.instructions):
        return source
    projected = deepcopy(source)
    for item in projected.instructions:
        item.step = item.step.replace(FINAL, PM_FINAL_PRECOMMIT)
    return projected


def phases(source: list[Phase]) -> list[Phase]:
    replacements = {
        catalog.FIRST_STEP: FIRST, delivery.FIRST_STEP: FIRST,
        catalog.REPORT: REPORT, delivery.PM_PHASE_REPORT: PREPARATION_REPORT,
        catalog.WAITING: WAIT,
        delivery.PM_CRITICAL_REVIEW: CRITICAL_REVIEW,
        delivery.PM_CONFIRMATION_INSTRUCTIONS[1]: WAIT,
        delivery.PM_CONFIRMATION_INSTRUCTIONS[2]: FEEDBACK,
        delivery.PM_CONFIRMATION_INSTRUCTIONS[3]: delivery.PM_CONFIRMATION_INSTRUCTIONS[3].replace(
            "stage=Backlog", "stage=Draft"
        ).replace("the own-task PM grant", "the configured per-agent service identity"),
        delivery.terminal_instruction("project_manager"): FINAL,
    }
    projected = deepcopy(source)
    for phase in projected:
        for item in phase.instructions:
            if phase.code == "PM-DRAFT-02":
                item.step = item.step.replace(catalog.WAITING, PREPARATION_WAIT)
                for old, new in PM_PREPARATION_REPLACEMENTS.items():
                    item.step = item.step.replace(old, new)
            if phase.code == "PM-DRAFT-03":
                for old, new in PM_FINAL_REPLACEMENTS.items():
                    item.step = item.step.replace(old, new)
            for old, new in replacements.items():
                item.step = item.step.replace(old, new)
        if phase.code == "PM-DRAFT-02":
            for check in phase.checks:
                for old, new in PM_PREPARATION_CHECK_REPLACEMENTS.items():
                    check.description = check.description.replace(old, new)
            for evidence in phase.evidence:
                for old, new in PM_PREPARATION_EVIDENCE_REPLACEMENTS.items():
                    evidence.item = evidence.item.replace(old, new)
        if phase.code == "PM-DRAFT-03":
            for check in phase.checks:
                for old, new in PM_FINAL_CHECK_REPLACEMENTS.items():
                    check.description = check.description.replace(old, new)
            for evidence in phase.evidence:
                for old, new in PM_FINAL_EVIDENCE_REPLACEMENTS.items():
                    evidence.item = evidence.item.replace(old, new)
    return projected
