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
    "copy the successful no-report response's ok=true, exit_code=0 and actual scalar fields "
    "result.interaction_protocol, result.task, result.namespace_id, result.concrete_agent_ref, "
    "result.assignment_ref, result.execution_ref, result.business_task_ref, result.phase_code, result.version "
    "and result.status. Compare these with the server-issued Workflow key and assigned task/namespace/agent; "
    "include the Tracker task/root UUID, stage/status and actual input references from the authorized Tracker "
    "reads. State an absent requirements revision as absent, not as invented evidence. The evidence is this "
    "already returned instruction read, not a future PASS verdict from the report being submitted. Never invent "
    "response values or substitute instruction text for the actual response; failed or mismatched reads remain "
    "blockers. Omit credentials from the report."
)
REPORT = (
    "Submit only actual completed phase work with project-workflow --json step --task <workflow-task-key> "
    "--operation-key <stable-key> --expected-version <last-returned-version> --report -. Supply report text on stdin. "
    "After an unknown response retain exactly that key, version and report; read back history for the operation. "
    "Do not select a replacement key merely because acceptance is unknown. Follow the returned current phase."
)
WAIT = (
    "Wait for actual human input in the same conversation with this phase unfinished. Feedback is not confirmation. "
    "Revise and republish the whole document when needed; only explicit owner consent to the latest revision/hash "
    "permits PM completion. No checkpoint, native readback or Fleet rebind is required by this protocol."
)
PREPARATION_REPORT = (
    "Brainstorming and owner feedback keep this same execution/assignment/cycle; no placeholder document or "
    "invented question is required. " + REPORT + " Report only this completed preparation phase, then stop at "
    "the returned next phase. Actual owner confirmation belongs to phase 3 in this SAME execution. "
    "Never complete the PM Workflow or create another assignment/cycle merely to wait for consent."
)
FEEDBACK = (
    "Handle feedback by revising and publishing the document within the SAME execution, then present the FULL "
    "new saved revision/content_hash. Any document change invalidates earlier consent. Free feedback and "
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
            for old, new in replacements.items():
                item.step = item.step.replace(old, new)
        for check in phase.checks:
            if check.description == delivery.PM_CONFIRMATION_CHECKS[4]:
                check.description = (
                    "Exact owner confirmation is saved while Tracker remains in Draft. Workflow completes first; "
                    "only subsequent Tracker PM completion may atomically move Draft to Backlog / Ready using "
                    "the authoritative terminal receipt. No external business verifier checklist or Analyst "
                    "is required."
                )
    return projected
