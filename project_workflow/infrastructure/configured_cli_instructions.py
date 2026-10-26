"""Runtime-only protocol projection; never rewrite the installed legacy catalog."""

from copy import deepcopy

from project_workflow.infrastructure import single_task_catalog as catalog
from project_workflow.infrastructure import single_task_delivery_instructions as delivery
from project_workflow.supervisor.models import Phase

FIRST = (
    "Read this task's current Workflow instructions using project-workflow --json step --task <workflow-task-key>. "
    "Use the permanently configured namespace and agent credential. Missing configuration or denied access is a "
    "blocker; never use a human token or local database fallback. No native binding or temporary files are required."
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
    "authoritative terminal receipt without moving Tracker. Only then use the supported Tracker PM completion, "
    "which reads this receipt server-to-server and performs atomic Draft -> Backlog / Ready. "
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
