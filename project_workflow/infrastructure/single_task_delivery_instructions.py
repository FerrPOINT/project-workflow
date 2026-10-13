"""Tracker producer instructions; publication does not complete a stage."""

FIRST_STEP = (
    "Your first working operation is terminal -> project-workflow --json step --task <workflow-task-key> "
    "--operation-key <original-key> --runtime-request <private-request-json> "
    "--execution-token-file <private-token-file> without --report. Use only the supplied namespace, "
    "assignment/run fence and report=null request. Verify the admitted returned Workflow step before any "
    "Tracker read, dialogue, file edit or CI/CD action. Tracker task UUID equals root UUID; the Workflow key "
    "is its local session mapping. An installed profile is not execution admission: pending API registration "
    "or authorization is a blocker. Never downgrade to human CLI/local DB mode or modify native Hermes."
)

RESULTS = {
    "analyst": "result.role=analyst with analysis ArtifactReceipt",
    "architect": "result.role=architect with design ArtifactReceipt for this task's architecture/plan only",
    "developer": "result.role=developer with exact commit_sha, changes ArtifactReceipt and checks ArtifactReceipts",
    "reviewer": "result.role=reviewer with verdict approved|rework and report ArtifactReceipt",
    "tester": "result.role=tester with verdict passed|rework and report ArtifactReceipt",
    "devops": (
        "result.role=devops with deployment and verification ArtifactReceipts; verification must cover exact "
        "artifact provenance, deployed health and acceptance, not only build success"
    ),
}
TARGETS = {
    "analyst": "Architecture / Ready",
    "architect": "Development / Ready",
    "developer": "Review / Ready for both initial and rework, followed by fresh Testing",
    "reviewer": "Testing / Ready for approved; Rework / Ready for rework",
    "tester": "Deployment / Ready for passed; Rework / Ready for rework",
    "devops": "Deployment / Completed",
}

PM_PHASE_REPORT = (
    "Report only this completed preparation phase via terminal -> project-workflow --json step "
    "--task <workflow-task-key> --report <report-text> with the supplied --operation-key, --runtime-request "
    "and --execution-token-file. body.report must equal --report; retain exact key/body for uncertain-effect "
    "readback. Stop at the returned next phase: owner confirmation belongs to phase 3 in this SAME execution. "
    "Do not complete the PM Workflow or create another assignment/cycle to wait for consent."
)
PM_CONFIRMATION_INSTRUCTIONS = [
    "Present the FULL server-saved requirements document to the human owner, including exact revision and "
    "content_hash, scope/non-goals, acceptance criteria, choices/tradeoffs and unresolved contradictions. "
    "Request explicit confirmation of this exact revision/hash; a summary alone, silence, preselection "
    "or a yes to a clarification question is not consent. PM never confirms as the owner.",
    "Checkpoint while awaiting actual owner confirmation with phase 3 unfinished and PM Workflow NOT "
    "completed. Waiting is separate from Tracker stage/status. Keep the same execution/assignment/cycle; "
    "never resume a completed execution or multiply PM assignment cycles to work around ordering. "
    "Checkpoint/resume needs typed input_kind answer|feedback|confirmation. The existing answer-only "
    "checkpoint/resume contract does not support free feedback or consent: until the typed extension is "
    "integrated, report that explicit dependency and leave this phase unfinished. Do not invent CLI commands.",
    "Handle feedback by revising and publishing the document within the SAME execution, then present the "
    "FULL new saved revision/content_hash and checkpoint again. Any document change invalidates earlier "
    "consent. Only input_kind=answer may reference a real question and answer_event_ref; free feedback and "
    "input_kind=confirmation must not fabricate an answer ID, question or clarification request. Confirmation "
    "input must reference the existing real owner confirmation receipt, not a conversational assertion. "
    "Unresolved feedback keeps phase 3 unfinished; no final Workflow report is permitted yet.",
    "AFTER actual owner confirmation, read its real receipt using task-tracker sdlc confirmation read "
    "--task <task-uuid> --revision <confirmed-revision>. --revision is required. Match task UUID, exact latest "
    "revision/content_hash, owner_subject and confirmation ID against the saved document and actual owner "
    "confirmation. Dependency: the inspected CLI still reads analysis-intent/outbox, unavailable to the PM "
    "grant; the Tracker worker is preparing direct GET requirements/{revision}/confirmation under this same "
    "CLI. Until that direct readback is available and authorized, leave phase 3 unfinished. Do not borrow "
    "scheduler/owner credentials, require PM to read an Analysis intent, or accept a missing/stale receipt.",
]
PM_CONFIRMATION_CHECKS = [
    "The FULL latest server-saved requirements document and exact revision/content_hash were presented to the owner.",
    "Actual owner confirmation has a real authorized readback receipt matching task, latest revision/hash and owner.",
    "Feedback was resolved within the same execution; no stale consent, fake answer IDs or extra PM cycles were used.",
    "Typed checkpoint/resume and direct PM confirmation readback dependencies are satisfied; no blockers remain.",
    "PM finalizes only; allowed next stage/status are Backlog / Ready then Analysis / Ready, not PM dispatch.",
]
PM_CONFIRMATION_EVIDENCE = [
    "FULL saved requirements document, exact revision/content_hash and owner presentation reference.",
    "Actual owner confirmation receipt ID/reference and readback matching task/revision/hash/owner_subject.",
    "Same-execution typed checkpoint/input references and feedback-to-revision history without fabricated answers.",
]


def terminal_instruction(role: str) -> str:
    if role == "project_manager":
        return (
            "ONLY AFTER the preceding exact owner confirmation receipt readback succeeds and all feedback "
            "is resolved, submit the FINAL phase report via terminal -> project-workflow --json step "
            "--task <workflow-task-key> --report <report-text> with the supplied --operation-key, --runtime-request "
            "and --execution-token-file. body.report must equal --report. Include actual saved document and "
            "confirmation receipt refs, revision/content_hash, owner_subject and check/evidence coverage; "
            "never invent authority fields. Reconcile uncertain effects using the exact original key/body "
            "before retry. Verify accepted Workflow complete=true, then finalize the PM run. The allowed next "
            "stage AND status are Backlog / Ready, then Analysis / Ready through Tracker/Fleet pickup. "
            "Tracker may create an Analysis / Ready intent at consent, but Analyst reserve remains blocked "
            "until PM actual completion is observed. PM does not dispatch Analyst or create another PM cycle. "
            "API/policy integration remains pending parent; installed instructions do not authorize live routing. "
            "Generic patch/issue transition/board move are forbidden substitutes."
        )
    return (
        f"After accepted Workflow complete=true, the allowed next stage AND status are {TARGETS[role]} "
        "on this same task=root. While the assigned run is still alive, prepare the actual existing "
        "SubmitDeliveryProposal JSON with exactly fence, workflow_receipt, result, idempotency_key. "
        f"Use {RESULTS[role]}. ArtifactReceipt has reference and sha256. "
        "Use the supplied DeliveryFence assignment_id/execution_id/fencing_token/lease_id/expected_lease_version "
        "and real accepted Workflow receipt reference/hash; never invent evidence or authority fields. "
        "If complete=true supplies no usable immutable Workflow receipt, report that dependency and do not submit. "
        "Run task-tracker sdlc result propose --task <task-uuid> --from-file <proposal.json> using the authorized "
        "producer, then task-tracker sdlc result operation --task <task-uuid> --key <original-key>. Match the "
        "actual proposal receipt to this task/assignment/execution/result/evidence and original operation. "
        "Unknown submission acceptance requires operation readback before any retry with exact same key/body. "
        "A proposal receipt DOES NOT transition the stage or prove stage completion. Return its actual "
        "proposal_id/output_sha256, original operation key and outcome in the final agent report and end the run; "
        "do not wait or poll for stage transition while "
        "keeping the run alive. After actual terminal, Fleet verifies the proposal and invokes schedulerComplete; "
        "Fleet/operator reads the resulting stage/status through the registered Tracker lifecycle readback. "
        "There is no lifecycle CLI command in the inspected parser, so do not invent one. Reviewer/Tester "
        "rework includes frozen actionable findings; repaired candidates repeat Review and Testing. "
        "Workflow assessment passed/needs_rework is report language; serialize only the role-specific verdict "
        "values listed above, never needs_rework in a proposal verdict. "
        "Wire role is devops; only the Fleet boundary explicitly maps it to dev_ops. "
        "API registration remains pending parent: 404/403 or absent capability is a blocker, not permission "
        "to fabricate a receipt, manually schedulerComplete, generic Task patch, issue transition or board move."
    )
