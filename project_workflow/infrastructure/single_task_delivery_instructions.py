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


def terminal_instruction(role: str) -> str:
    if role == "project_manager":
        return (
            "After accepted Workflow complete=true, the allowed next stage AND status are Backlog / Ready "
            "only after the human owner's exact revision/content_hash confirmation, then Tracker pickup "
            "Analysis / Ready. PM never confirms for the owner or dispatches Analyst. Read the real receipt "
            "with task-tracker sdlc confirmation read --task <task-uuid> --revision <confirmed-revision>; "
            "--revision is required by the current CLI parser. Match task UUID, revision/content_hash, "
            "owner_subject and confirmation ID to task-tracker sdlc intent --task <task-uuid>. A prior receipt "
            "does not confirm changed requirements. Missing/rejected receipt remains unconfirmed. "
            "Tracker API registration is pending parent; do not activate live routing or infer readiness "
            "from installed CLI. Generic patch/issue transition/board move are forbidden substitutes."
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
