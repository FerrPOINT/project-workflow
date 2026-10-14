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

SEALED_ARTIFACTS = (
    "For the six technical roles, only sealed assignment artifacts are authorized on the narrow attachment "
    "routes under the supplied current delivery grant. Ordinary comments remain unauthorized; do not borrow "
    "owner/scheduler credentials, use an ordinary human token or broaden permissions. Read permitted own "
    "artifacts and accepted predecessor references using task-tracker attachment list --issue <task-uuid> "
    "and task-tracker attachment download <attachment-uuid> --out <private-artifact-path>. Match issue_id to "
    "task=root and the exact supplied reference/hash; match expected assignment_id, execution_id and role "
    "from artifact.binding to the actual producer/predecessor, not a guessed current assignment for old evidence. "
    "Verify SHA256 of the raw downloaded bytes; CLI download success alone is not an ArtifactReceipt. "
    "After role work and BEFORE the FINAL Workflow phase report, publish the actual structured JSON role "
    "reports/checks/deployment evidence through task-tracker attachment upload --issue <task-uuid> "
    "--file <role-artifact.json> --content-type application/json. Use only the current supplied "
    "assignment/execution/agent/fence and run context. Tracker enforces exact routing, Running/InProgress "
    "and a live lease; the lease holder is the scheduler, not the agent. Do not renew it as scheduler or set "
    "status yourself. Preserve the exact uploaded bytes, filename and MIME for replay. "
    "Use the actual server-returned artifact.receipt {reference,sha256}, with "
    "reference=tracker-attachment:<UUID> and SHA256 of raw bytes, and artifact.binding "
    "{assignment_id,execution_id,role}. Read the saved metadata back with attachment list, download by the "
    "actual attachment UUID and verify raw SHA256 and size against that receipt. New role outputs must match "
    "this current task/assignment/execution/role, including Developer rework. Never fabricate an attachment "
    "UUID, reference, SHA or a receipt from a local path, comment, Forge URL/job ID or Workflow terminal hash. "
    "Workflow terminal receipt and role artifact contents are separate evidence. Unknown upload acceptance "
    "requires authorized metadata/byte readback: locate the actual saved entry by exact current binding, "
    "filename, MIME, size and raw SHA; if found, download its returned UUID and retain the verified receipt "
    "without another upload. If no matching saved entry exists, only an exact-file replay with the original "
    "filename/MIME under the still-current grant is permitted; never overwrite sealed bytes, delete evidence, "
    "change identity/fence or declare success from uncertainty. "
    "404/403, missing artifact capability, stale binding, checksum mismatch or unavailable readback is a "
    "concrete blocker: leave the phase unfinished, report it and do not fake Workflow/business completion. "
)


def artifact_instruction(role: str) -> str:
    return SEALED_ARTIFACTS + (
        f"Prepare {RESULTS[role]} using only those verified actual artifact.receipt values. "
        "Require the exact supplied proposal.idempotency_key from runtime guidance/template before the FINAL "
        "Workflow report; do not generate or derive a key, even from a known session/run UUID. A missing "
        "supplied key is a blocker, not permission to invent one. Include artifact references/hashes, provenance "
        "and role evidence in the final Workflow phase report, then use the actual accepted Workflow receipt "
        "for the delivery proposal; no new artifact envelope or producer protocol is introduced. "
    )


def context_instruction(role: str) -> str:
    common = (
        "After the Workflow step, read task-tracker sdlc context --task <task-uuid> and "
        "task-tracker sdlc requirements --task <task-uuid> with the supplied own-task grant. Verify task=root, "
        "assigned role/mode, stage/status, exact input revision/hash and predecessor evidence. Read supplied "
        "immutable source/evidence references only through authorized access. "
    )
    if role == "project_manager":
        return common + (
            "Ordinary comments/attachments are not authorized by the inspected PM or delivery task grants; "
            "do not borrow owner/scheduler credentials or call their ordinary endpoints. Parent must supply "
            "required source snapshots or an explicitly authorized read capability; missing required "
            "input/access is a blocker, not permission to invent sources or broaden authority. "
            "Also read task-tracker sdlc input --task <task-uuid> and task-tracker sdlc questions "
            "--task <task-uuid> under the PM grant. An absent requirements revision is normal during "
            "pre-document brainstorming; do not publish a placeholder merely to obtain a revision."
        )
    return common + artifact_instruction(role) + (
        "The delivery task grant does not authorize clarifications/questions; use supplied immutable "
        "requirements and predecessor evidence, and route material business contradictions back to PM. "
        "Missing required source/input/access is a blocker; request an authorized snapshot from parent, "
        "never invent sources or broaden authority."
    )


PM_PHASE_REPORT = (
    "During pre-document brainstorming the current phase may stay unfinished while the trusted Fleet "
    "adapter checkpoints with requirements_revision=null and requirements_sha256=null. Only "
    "input_kind=feedback may resume that checkpoint, using actual PmFeedbackReceipt.message_id and its "
    "input_receipt reference/sha256 after old run terminal readback; no placeholder document or fake "
    "question/answer is needed. Keep the same execution/assignment/cycle. "
    "Report only this completed preparation phase via terminal -> project-workflow --json step "
    "--task <workflow-task-key> --report <report-text> with the supplied --operation-key, --runtime-request "
    "and --execution-token-file. body.report must equal --report; retain exact key/body for uncertain-effect "
    "readback. Stop at the returned next phase: owner confirmation belongs to phase 3 in this SAME execution. "
    "Do not complete the PM Workflow or create another assignment/cycle to wait for consent."
)
PM_PUBLISH_INSTRUCTION = (
    "Brainstorm in small free-form iterations before a document exists; never create a placeholder revision "
    "or question solely for checkpointing. When the agreed draft is ready, publish the real requirements "
    "using task-tracker sdlc revision publish --task <task-uuid> --from-file <revision.json>. Formal "
    "clarification requires an existing requirements revision: only then publish a focused question using "
    "task-tracker sdlc question publish --task <task-uuid> --from-file <question.json>. Use actual strict "
    "MachineFence, revision/version and idempotency fields from the supplied context; never invent IDs. "
    "Read questions/requirements back and match the actual server revision/content_hash. Reconcile "
    "uncertain publication through those supported reads before retry with the exact original key/body."
)
PM_CONFIRMATION_INSTRUCTIONS = [
    "Present the FULL server-saved requirements document to the human owner, including exact revision and "
    "content_hash, scope/non-goals, acceptance criteria, choices/tradeoffs and unresolved contradictions. "
    "Request explicit confirmation of this exact revision/hash; a summary alone, silence, preselection "
    "or a yes to a clarification question is not consent. PM never confirms as the owner.",
    "Checkpoint while awaiting actual owner confirmation with phase 3 unfinished and PM Workflow NOT "
    "completed. Waiting is separate from Tracker stage/status. Keep the same execution/assignment/cycle; "
    "never resume a completed execution or multiply PM assignment cycles to work around ordering. "
    "Use the existing profile checkpoint/resume through the trusted Fleet adapter with typed input_kind "
    "answer|feedback|confirmation and unified input {input_kind,input_id} plus input_receipt {reference,sha256}. "
    "The adapter validates actual Tracker input and old run terminal readback before resume; the agent "
    "does not choose the observed owner/lease or call scheduler resume itself. Missing authorized adapter "
    "capability is a blocker; leave the phase unfinished and do not invent CLI commands.",
    "Handle feedback by revising and publishing the document within the SAME execution, then present the "
    "FULL new saved revision/content_hash and checkpoint again. Any document change invalidates earlier "
    "consent. input_id is actual Answer.id, PmFeedbackReceipt.message_id or Confirmation.id according to "
    "input_kind; only answer carries a real clarification reference/version pair. Free feedback and "
    "input_kind=confirmation must not fabricate an answer ID, question or clarification request. Answer "
    "and confirmation require an existing exact requirements revision/hash; only feedback can use the "
    "pre-document null/null pair. Confirmation input must reference the existing real owner confirmation "
    "receipt, not a conversational assertion. "
    "Unresolved feedback keeps phase 3 unfinished; no final Workflow report is permitted yet.",
    "AFTER actual owner confirmation, read its real receipt using task-tracker sdlc confirmation read "
    "--task <task-uuid> --revision <confirmed-revision>. --revision is required. Match task UUID, exact latest "
    "revision/content_hash, owner_subject and confirmation ID against the saved document and actual owner "
    "confirmation. The inspected CLI uses direct GET requirements/{revision}/confirmation under the own-task "
    "PM grant and checks the actual receipt ID/task/revision/content_hash/owner_subject/created_at and "
    "stage=Backlog. This historical confirmation receipt is not current lifecycle completion. Missing "
    "capability, denied access or a stale/mismatched receipt leaves phase 3 unfinished. Do not borrow "
    "scheduler/owner credentials or require PM to read an Analysis intent.",
]
PM_CONFIRMATION_CHECKS = [
    "The FULL latest server-saved requirements document and exact revision/content_hash were presented to the owner.",
    "Actual owner confirmation has a real authorized readback receipt matching task, latest revision/hash and owner.",
    "Feedback was resolved within the same execution; no stale consent, fake answer IDs or extra PM cycles were used.",
    "Authorized typed checkpoint/resume and direct PM confirmation readback dependencies are satisfied; "
    "no blockers remain.",
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
            "is resolved, reconcile task-tracker sdlc confirmation read --task <task-uuid> "
            "--revision <confirmed-revision>, then submit the FINAL phase report via terminal -> "
            "project-workflow --json step "
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
    return artifact_instruction(role) + (
        f"After accepted Workflow complete=true, the allowed next stage AND status are {TARGETS[role]} "
        "on this same task=root. While the assigned run is still alive, prepare the actual existing "
        "SubmitDeliveryProposal JSON with exactly fence, workflow_receipt, result, idempotency_key. "
        "Set proposal.idempotency_key to the exact supplied value from runtime guidance/template; "
        "original-key below means that supplied proposal.idempotency_key, never an agent-generated key. "
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
