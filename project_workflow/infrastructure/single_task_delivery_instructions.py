"""Tracker producer instructions; publication does not complete a stage."""

FIRST_STEP = (
    "If only the Tracker task UUID is known, read task-tracker sdlc context --task <task-uuid> and take "
    "its server-issued workflow_task_key (SDLC-N); never guess the key or create another task. Read this "
    "task's current Workflow instructions using project-workflow --json step --task <workflow-task-key>. "
    "Use the permanently configured namespace and agent credential. Missing configuration or denied "
    "access is a blocker; never use a human token or local database fallback. No native binding or "
    "temporary files are required. Before reporting this phase, include an 'Actual first Workflow step "
    "response' block in the report evidence: copy the actual scalar fields from the successful no-report "
    "command's parsed stdout JSON: interaction_protocol, task, namespace_id, concrete_agent_ref, "
    "assignment_ref, execution_ref, business_task_ref, phase_code, version and status. The CLI prints "
    "these fields at top level, not inside an HTTP response envelope. Record the terminal command's exit "
    "status separately when available; it is not a Workflow JSON field. Compare these with the "
    "server-issued Workflow key and assigned task/namespace/agent; include the Tracker task/root UUID, "
    "stage/status and actual input references from the authorized Tracker reads. Validate identity fields"
    " by their own authority: Tracker context.assignment.assignment_id equals Workflow assignment_ref; "
    "Tracker context.assignment.agent_id equals Workflow concrete_agent_ref; Tracker context.task_id and "
    "root_task_id equal Workflow business_task_ref; Tracker workflow_task_key equals Workflow task. "
    "Tracker context.assignment.execution_id is the retained tracker_execution_id, NOT Workflow "
    "execution_ref. Workflow execution_ref is independently generated at enrollment; these two execution "
    "IDs are intentionally separate and are not required to be equal. Record both with their authority "
    "names; compare execution_ref only with the same Workflow enrollment/history, never with Tracker "
    "execution_id. A difference between these two IDs alone is not a blocker and does not authorize "
    "rebind, replacement IDs or another execution. Assignment version and Workflow cursor version are "
    "also separate counters; validate each against its own authority. Actual task/assignment/agent "
    "mismatches remain blockers. State an absent requirements revision as absent, not as invented "
    "evidence. The evidence is this already returned instruction read, not a future PASS verdict from the"
    " report being submitted. Never invent response values or substitute instruction text for the actual "
    "response; failed or mismatched reads remain blockers. Omit credentials from the report."
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
    "reviewer": (
        "Testing / Ready for approved; Rework / Ready for rework while cycle < 3; "
        "on rework at cycle 3 preserve Review / Ready with waiting_reason=rework_limit_reached and runtime=Terminal"
    ),
    "tester": (
        "Deployment / Ready for passed; Rework / Ready for rework while cycle < 3; "
        "on rework at cycle 3 preserve Testing / Ready with waiting_reason=rework_limit_reached and runtime=Terminal"
    ),
    "devops": "Deployment / Completed",
}

CRITICAL_BUSINESS_REVIEW = (
    'Decide routine technical details within approved requirements; Review/Test defects use normal rework. '
    'Only requirements_contradiction or missing_business_decision that prevents safe progress requires PM '
    'business review. Read the current task-tracker sdlc context and lifecycle. Publish and read back sealed '
    'evidence for this actual assignment/execution/role using the authorized attachment commands. Submit the '
    'strict SubmitCriticalBlocker body with fence, current requirement_revision/content_hash, kind, question, '
    'rationale, options, recommendation, evidence and idempotency_key using task-tracker sdlc critical-blocker '
    'submit --task <task-uuid> --from-file -. Pass JSON on stdin. Its stable key is '
    'fleet-critical-blocker:<current-Tracker-assignment-uuid>, taken from the verified context assignment_id, '
    'never from a native run or another role result. Keep question <=4096 bytes, rationale <=8192 bytes, at '
    'most 8 options and 1..16 sealed evidence entries. A recommendation references an actual option_id. '
    'Missing current fence/evidence/access is a blocker; do not borrow an identity or fabricate proof. Read '
    'the original operation using task-tracker sdlc critical-blocker operation --task <task-uuid> --key '
    '<exact-original-key>. Verify task/root/project/owner, assignment/execution/agent, role, requirements '
    'revision/hash and blocker ID/hash. Unknown acceptance requires original-key readback; retain the same '
    'exact body/key, without a blind resend or a new key. A held receipt is not a completed stage, PM return '
    'or Workflow completion. Leave the phase unfinished, report the held receipt or unresolved uncertainty and '
    'finish the native run. Fleet and Tracker own actual termination, release and guarded return; the agent '
    'never calls scheduler commands or invents terminal proof. Missing producer capability is an operator '
    'dependency, not permission for a generic status change. '
)

PM_CRITICAL_REVIEW = (
    "Ordinary brainstorming and owner feedback continue under the current business assignment across "
    "messages. Read fresh task-tracker sdlc context --task <task-uuid>. If critical_review is absent, "
    "this is ordinary PM preparation; do not invent a blocker. If present, its blocker_id, blocker_sha256, "
    "blocker_version and requirements identify the server-selected business review. Require the current "
    "PM assignment for this SAME task=root; never allocate an assignment or reopen a completed one yourself. "
    "Read task-tracker sdlc critical-blocker read --task <task-uuid> --blocker <critical_review.blocker_id>. "
    "Match task/root/project/owner, current assignment/execution and the selected blocker ID/version/hash. "
    "Use your permanently configured service identity and current project rights. Read only the sealed "
    "evidence referenced by that blocker with task-tracker attachment download <referenced-attachment-uuid> "
    "--out <private-evidence-path>; verify raw SHA256 and the original technical assignment/execution/role. "
    "An old technical artifact keeps its original producer binding. This does not grant general attachment "
    "list/upload/delete or unrelated blocker access. Never borrow scheduler credentials or replace this "
    "review with the initial Draft input. Discuss the actual business contradiction or decision with the "
    "owner; routine technical decisions stay with technical roles. Publish the changed FULL requirements "
    "in the current assignment, then present the saved exact revision/hash and obtain a NEW human owner "
    "confirmation. Old consent and a held technical receipt cannot resolve the review. Use the same "
    "revision/question/answer/confirmation commands and final Workflow report as ordinary PM. No native "
    "checkpoint, bind, token file or execution lease is required. After the final report is accepted, "
    "follow its ordinary comment and PM completion instructions. Tracker resolves the blocker and saves "
    "Backlog / Ready atomically; PM does not dispatch Analyst. Missing access or inconsistent readback "
    "is an explicit blocker, not permission to invent proof."
)

SOURCE_CONTEXT = (
    "AFTER the admitted first Workflow step and before source/workspace work, require an approved source "
    "context supplied through operator-edited versioned SOUL/config or immutable approved requirements/source "
    "snapshots. There is no automatic project resolver or automatic source-context supplier. Verify the exact "
    "Tracker instance and project UUID, task=root, approved repository URL and repository ID, full base SHA, "
    "allowed branch and selected Forge delivery configuration UUID, which IS the existing Forge projects.id "
    "accepted by CLI --project. There is only one Forge configuration/project UUID, not a second configId. "
    "Keep it distinct from the Tracker project UUID, namespace and repository ID. Verify those coordinates "
    "against authorized readback. A repository name, working-directory name or default main branch is not "
    "an approved mapping. Require the exact candidate SHA whenever consuming an existing candidate; initial "
    "analysis/design/implementation must not invent a future candidate SHA. Missing/mismatched coordinates, "
    "checkout, permissions or source access are infrastructure blockers for the operator, not business "
    "questions for PM, consent, permission to guess names or permission to default to main. Existing env_json/"
    "secret_ref configuration supplies authorized CLI access; never print credentials or borrow a different "
    "identity. Ordinary tool/effect approval remains required and is not granted by these instructions. "
)

FORGE_TASK_WORKSPACE = (
    'Use permanently configured Forge access. Verify installed cicd-cli pipeline run --help exposes '
    '--task-intent and pipeline task-workspace exists; CLI help does not prove server support or authority. '
    'Read the current Tracker lifecycle, source binding and authorized Forge project/repository metadata. Use '
    'the exact approved configuration UUID, repository UUID, source SHA and branch; never infer a mapping from '
    'a display name. Prepare the existing TaskWorkspaceIntent from that actual assignment/routing/lease. Use '
    'operationKey=task-workspace:<current-Tracker-assignment-uuid> and pipeline Idempotency-Key equal to that '
    'assignment UUID. These are stable business keys, independent of Fleet native run IDs. The intent '
    'binding.workflowTaskRef is the technical assignment execution.key from lifecycle, distinct from the root '
    'Workflow workflow_task_key. holderSubject is the actual lease holder, not the agent. Forge allocates '
    'runner lease, attempt and workspace IDs; do not fabricate them or substitute the Tracker lease. Run '
    'cicd-cli pipeline run --project <approved-forge-project-uuid> --git-ref <exact-source-sha> '
    '--idempotency-key <assignment-uuid> --task-intent - with the strict JSON on stdin. No request/token '
    'files, credential-context or per-message shell environment are needed. Server-side current task, '
    'repository mapping, native/lease and source guards remain mandatory. Unknown trigger acceptance permits '
    'no blind resend, fresh key or replacement body; use the original readback or retain the unresolved '
    'operation for authorized reconciliation. Read the actual returned pipeline ID through pipeline show --id '
    'and pipeline task-workspace --project <uuid> --id <pipeline-uuid>. Require successful repository CI for '
    'the exact candidate commit and the real original task-workspace receipt. Null means pending, not success. '
    'A read-only Forge runner workspace does not authorize a writable agent checkout. Developer uses its '
    'preconfigured authorized checkout and candidate branch, performs the real commit and push, and starts '
    'this task pipeline only for the final candidate. Include the actual successful PipelineDetail JSON from '
    'pipeline show as one of the sealed checks artifacts; other check artifacts may contain test logs. Fleet '
    'independently reads the approved repository/branch, original pipeline and task workspace before '
    'completion. For candidate evidence, use the existing workspace candidate-evidence command with the '
    'original operation key and real WorkspaceOperationLookup on stdin. Missing access, capability or source '
    'is an operator blocker; never substitute an ordinary unbound pipeline, default-success template, guessed '
    'receipt or different credential. '
)

FORGE_IMAGE_BUILD = (
    "For an OCI application, the approved repository .forge-ci.yml v1 uses a typed image_build job, "
    "not docker build in commands. The existing pipeline run --task-intent transport carries task intent; "
    "there is no new image-build CLI flag. The configured Forge server must separately support and be "
    "qualified for this backend build action; working CLI help or a preloaded image does not prove that. "
    "The image_build fields are context, dockerfile, optional target, descriptor_artifact and "
    "readable_schema_versions. Use actual portable relative paths, a Dockerfile inside context, an existing "
    "target stage if selected, and the application's actual supported positive schema versions; never "
    "invent a stage or data compatibility. A job cannot mix image_build with commands, image, tags, secrets, "
    "artifacts or allow_failure=true, and default tags must be empty. descriptor_artifact declares the "
    "server-produced descriptor artifact automatically. Forge's backend uses the sealed Git source and "
    "its configured verified daemon under the current task/attempt/lease. Docker authority and TLS "
    "credentials stay on the backend, never in agent/job env, mounts, secrets or commands. Do not request "
    "a socket, run HostShell/docker/dind as a workaround, or grant new authority. The successful build "
    "produces forge/oci-candidate/v1 with imageId, sourceCommit, dataProtocol, readableSchemaVersions and "
    "migrations. Require the actual immutable sha256: image ID, exact candidate sourceCommit, "
    "dataProtocol=readonly_snapshot_v1 and empty migrations for the current owner delivery adapter. "
    "Do not author this descriptor by hand, substitute a mutable tag or equate it with deployed acceptance. "
    "Read the actual original pipeline/job/artifact metadata; use installed cicd-cli artifact list "
    "--job <actual-job-uuid> and cicd-cli artifact download --id <actual-artifact-uuid> "
    "--output <private-descriptor-path> under the approved Forge credential. Verify raw descriptor SHA256 "
    "against actual artifact metadata and the original workspace/candidate evidence. Missing server "
    "capability, descriptor or authorized readback is an operator dependency, not permission to fabricate "
    "evidence. Unknown/timeout retains the original attempt/key/body for authorized readback; no blind "
    "rebuild, fresh key or second pipeline. "
)

ROLE_IMAGE_BUILD = {
    "developer": FORGE_IMAGE_BUILD
    + (
        "In Developer initial AND rework, author the real application Dockerfile and typed build recipe "
        "only in the approved writable checkout/branch, then freeze their actual candidate commit SHA. "
        "Use the current assignment UUID as the original task pipeline key for that frozen candidate; "
        "do not spend it on a "
        "preliminary base-SHA build and later change the original intent/body to another commit. Retain "
        "the server-produced descriptor artifact ID/raw SHA, exact pipeline/job/attempt and original "
        "workspace receipt in sealed changes/checks. Build success is not Review, Testing or deployment. "
    ),
    "devops": FORGE_IMAGE_BUILD
    + (
        "DevOps consumes the actual descriptor from the accepted Developer candidate's original pipeline "
        "and verifies it against the accepted Developer result/SHA propagated through Review and Testing. "
        "Do not edit the accepted candidate, replace its descriptor with an independently preloaded image, "
        "or substitute a new DevOps workspace/pipeline for the saved build provenance. The configured "
        "delivery owner must observe that exact image on its verified daemon; image transfer or daemon "
        "substitution is not authorized. Use the existing guarded workspace delivery/readback commands "
        "and current DevOps taskFence, then verify actual deployment, health, application acceptance and "
        "rollback evidence before the unchanged final Workflow/Tracker handoff. "
    ),
}

ROLE_SOURCE_EVIDENCE = {
    "analyst": (
        "In the sealed analysis artifact retain the verified approved source coordinates and immutable "
        "requirements/source snapshot references, distinguishing observed facts from missing inputs. "
    ),
    "architect": (
        "In the sealed design artifact retain the same verified source coordinates and analysis references, "
        "approved branch/base SHA and permitted checkout/verification plan for this task only. "
    ),
    "developer": (
        "In Developer initial AND rework sealed changes/checks retain the actual candidate commit SHA, "
        "approved repository/branch/base coordinates, real build pipeline ID, original pipeline/workspace "
        "operation keys and actual workspace receipt reference/hash or exact receipt bytes with their SHA. "
        "Record actual artifact/check provenance; a local filename or guessed Forge URL is not a receipt. "
        "Developer CANNOT embed its own acceptedDeveloperResultId: Tracker allocates that accepted result "
        "only AFTER native terminal and Fleet scheduler Complete. Do not invent the UUID, wait for your own "
        "future accepted result/transition inside the active run, or make it a precondition of sealing "
        "changes/checks or final Workflow completion. Publish current artifacts, complete Workflow, submit "
        "the real proposal with the supplied key and finish the native run using the existing final instructions. "
    ),
    "reviewer": (
        "Reviewer obtains actual acceptedDeveloperResultId from this assignment's supplied previous_result_id "
        "AFTER Developer Complete. Read task-tracker sdlc result read --task <task-uuid> --result "
        "<accepted-developer-result-uuid>; require source=delivery, matching task/cycle, role=developer and "
        "exact candidate commit_sha, then verify the sealed changes/checks and their build/workspace "
        "provenance. Embed that verified Developer result ID, candidate SHA, approved source coordinates and "
        "actual pipeline/workspace receipt references in the Reviewer's own sealed report. Do not amend "
        "Developer artifacts to insert a future ID or wait for your own future accepted Reviewer result. "
    ),
    "tester": (
        "Tester reads the actual accepted Reviewer result identified by supplied previous_result_id and its "
        "sealed report. Propagate its verified acceptedDeveloperResultId, exact candidate SHA, approved "
        "coordinates and actual build/workspace receipt references into the Tester's sealed report; reread "
        "that accepted Developer result and verify source=delivery, task/cycle, role=developer and commit_sha. "
        "Missing/mismatched provenance blocks testing acceptance; do not infer it from a report filename, "
        "moving branch or old passing cycle. Do not wait for your own future accepted Tester result. "
    ),
    "devops": (
        "DevOps reads the actual accepted Tester result identified by supplied previous_result_id and its "
        "sealed report, resolves the propagated acceptedDeveloperResultId and rereads that real accepted "
        "Developer result/SHA. Verify the same task/cycle, reviewed/tested candidate, repository, original "
        "pipeline/workspace receipt, lookup hash, artifact ID and raw SHA. Require separately supplied "
        "operator owner-target references and the actually published Forge target policy; never invent an "
        "environment, deployment URL or target, enroll one as agent, or use a protected stand by default. "
        "Use existing cicd-cli workspace delivery --project <forge-configuration-uuid> --operation-key "
        "<original-workspace-key> --from-file <delivery.json> and cicd-cli workspace delivery-readback "
        "--project <forge-configuration-uuid> --operation-key <original-workspace-key> --delivery-key "
        "<original-delivery-key> --from-file <lookup.json>. Use the existing DeliveryCommand and current "
        "DevOps taskFence with actual developmentResultId; preserve the old build/workspace binding "
        "separately from the current DevOps assignment/lease. Keep the saved build's original workspace key; "
        "do not replace it with the current DevOps startup key. Owner target policy and server verification "
        "remain authoritative; do not replace this with generic deployment create or an unbound pipeline. "
        "Retain actual deployment, health, acceptance and rollback readbacks in sealed deployment/verification "
        "artifacts. Unknown delivery uses original-key readback, not another effect. Do not wait for your own "
        "future accepted result or Tracker transition before ending this run. "
    ),
}

SEALED_ARTIFACTS = (
    "Use sealed assignment artifacts for technical evidence under the current configured assignment "
    "and project rights. Ordinary comments carry discussion and the final handoff; they do not replace "
    "sealed artifacts. Do not borrow owner/scheduler credentials, use a human token or broaden "
    "permissions. Read permitted own artifacts and accepted predecessor references using task-tracker"
    " attachment list --issue <task-uuid> and task-tracker attachment download <attachment-uuid> "
    "--out <private-artifact-path>. Match issue_id to task=root and the exact supplied "
    "reference/hash; match expected assignment_id, execution_id and role from artifact.binding to the"
    " actual producer/predecessor, not a guessed current assignment for old evidence. Verify SHA256 "
    "of the raw downloaded bytes; CLI download success alone is not an ArtifactReceipt. After role "
    "work and BEFORE the FINAL Workflow phase report, publish the actual structured JSON role "
    "reports/checks/deployment evidence through task-tracker attachment upload --issue <task-uuid> "
    "--file <role-artifact.json> --content-type application/json. Use only the current supplied "
    "assignment/execution/agent/fence and run context. Tracker enforces exact routing, "
    "Running/InProgress and a live lease; the lease holder is the scheduler, not the agent. Do not "
    "renew it as scheduler or set status yourself. Preserve the exact uploaded bytes, filename and "
    "MIME for replay. Use the actual server-returned artifact.receipt {reference,sha256}, with "
    "reference=tracker-attachment:<UUID> and SHA256 of raw bytes, and artifact.binding "
    "{assignment_id,execution_id,role}. Read the saved metadata back with attachment list, download "
    "by the actual attachment UUID and verify raw SHA256 and size against that receipt. New role "
    "outputs must match this current task/assignment/execution/role, including Developer rework. "
    "Never fabricate an attachment UUID, reference, SHA or a receipt from a local path, comment, "
    "Forge URL/job ID or Workflow terminal hash. Workflow terminal receipt and role artifact contents"
    " are separate evidence. Unknown upload acceptance requires authorized metadata/byte readback: "
    "locate the actual saved entry by exact current binding, filename, MIME, size and raw SHA; if "
    "found, download its returned UUID and retain the verified receipt without another upload. If no "
    "matching saved entry exists, only an exact-file replay with the original filename/MIME under the"
    " still-current assignment and project rights is permitted; never overwrite sealed bytes, delete "
    "evidence, change identity/fence or declare success from uncertainty. 404/403, missing artifact "
    "capability, stale binding, checksum mismatch or unavailable readback is a concrete blocker: "
    "leave the phase unfinished, report it and do not fake Workflow/business completion. "
)


def artifact_instruction(role: str) -> str:
    return (
        ROLE_SOURCE_EVIDENCE[role]
        + SEALED_ARTIFACTS
        + (
            ("Prepare ")
            + f"{RESULTS[role]}"
            + (
                " from verified artifact receipts. Include actual role evidence in the final phase "
                "report. The final report does not require its own future terminal receipt, future "
                "ordinary comment or future Tracker transition. "
            )
        )
    )


def context_instruction(role: str) -> str:
    common = (
        "Read the ticket and ALL participants comments with task-tracker sdlc discussion read --task "
        "<task-uuid>; follow next_after with the same snapshot until next_after is null. Start a fresh "
        "complete scan before the final comment. Read requirements, current assignment, previous typed "
        "results and authorized attachments. Missing required access is a blocker. "
    )
    if role == "project_manager":
        return common + (
            "Read task-tracker sdlc input and questions for this task. An absent requirements "
            "revision is normal before the first real document."
        )
    return common + SOURCE_CONTEXT + FORGE_TASK_WORKSPACE + ROLE_IMAGE_BUILD.get(role, "") + artifact_instruction(role)


PM_PHASE_REPORT = (
    "Apply saved answers and relevant feedback to the Draft; publish the next FULL requirements "
    "revision without asking for separate permission to save the draft. 'Not confirmation of the "
    "final revision' does not prohibit updating the Draft. Do not invent unresolved business choices."
    " Report only this completed preparation phase. "
) + (
    "Complete only the present preparation phase using the normal report operation and current "
    "version. Submit only actual completed phase work with project-workflow --json step --task "
    "<workflow-task-key> --operation-key <stable-key> --expected-version <last-returned-version> "
    "--report -. Supply report text on stdin. Before submission, check EVERY required_check against "
    "actual evidence and include the required_evidence: reference saved alternatives/tradeoffs when "
    "they exist, actual blockers and the no-additional-tasks check; do not invent alternatives, "
    "checks or evidence. Inspect the returned verdict, missing, blockers, phase and version. A known "
    "PARTIAL is not phase acceptance: do the missing work or correct its report in the SAME "
    "execution, using the returned version and a NEW operation key ONLY for a new corrected report "
    "body. Do not request owner consent or claim preparation complete while preparation remains "
    "PARTIAL. After an unknown response retain exactly that key, version and report; read back "
    "history for the operation. Provider/transport failure or unknown acceptance is NOT a known "
    "PARTIAL and does not permit automatic resubmission. Do not select a replacement key merely "
    "because acceptance is unknown. Follow the returned current phase."
)
PM_DRAFT_INSTRUCTIONS = [
    "Be a full brainstorming partner, not a mandatory questionnaire. Clarify ONLY when the initial input "
    "is incomplete or contradictory for the requirements: identify the concrete gap, ask one useful question "
    "at a time, and accept free-form answers in small iterations. Offer alternatives with tradeoffs only "
    "when an unresolved choice needs the owner; do not reopen choices already explicit in the brief. "
    "No long mandatory questionnaire, preselection, default selected answer or implied consent.",
    "If the initial input is complete and consistent, ask no clarification questions: proceed directly "
    "to the real requirements document using the supplied scope, constraints and acceptance criteria. "
    "Do not invent a question, missing detail or alternative solely to complete a phase. Brainstorming, "
    "clarification and requirements review all remain inside draft mode and Draft stage. Read the immutable "
    "initial request and distinguish facts, preferences and actual open choices.",
    "Converge on one clear in-scope requirements document without selecting a solution on the owner's "
    "behalf. Preserve explicit choices from a complete brief. Resolve blocking gaps or contradictions "
    "with the owner before claiming the requirements are ready; keep unresolved issues explicit. "
    "A complete brief is not owner confirmation: present the saved requirements for exact confirmation in phase 3.",
]
PM_DRAFT_CHECKS = [
    "Draft has a server-saved exact revision/hash, clear scope and measurable acceptance criteria.",
    "Clarifications were requested only for incomplete or contradictory input; a complete, consistent "
    "brief proceeds directly to requirements with no clarification questions or mandatory alternatives.",
    "Actual blocking gaps/contradictions were resolved without invented answers or preselection; "
    "if none exist, no question/answer evidence is required. Owner confirmation remains a separate exact action.",
    "Unresolved blockers remain explicit; no additional Tracker tasks were created.",
]
PM_DRAFT_EVIDENCE = [
    "Saved Draft revision/hash, source brief, scope/acceptance criteria and owner review presentation.",
    "For incomplete/contradictory input only: actual clarification and resolution references. "
    "For a complete, consistent brief: requirements derived from that brief, "
    "with no question/answer references required.",
]
PM_PUBLISH_INSTRUCTION = (
    "When clarification is needed, brainstorm in small free-form iterations before a document exists; "
    "never create a placeholder revision "
    "or question solely for checkpointing. When the agreed draft is ready, publish the real requirements "
    "using task-tracker sdlc revision publish --task <task-uuid> --from-file -. Formal "
    "clarification is conditional on an actual unresolved gap and requires an existing requirements revision: "
    "only then publish a focused question using "
    "task-tracker sdlc question publish --task <task-uuid> --from-file -. Pass JSON on stdin. Use actual strict "
    "MachineFence, revision/version and idempotency fields from the supplied context; never invent IDs. "
    "Read questions/requirements back and match the actual server revision/content_hash. Reconcile "
    "uncertain publication through those supported reads before retry with the exact original key/body."
)
PM_CONFIRMATION_INSTRUCTIONS = [
    (
        "Present the FULL latest saved requirements document with exact revision/content_hash and request"
        " explicit human owner confirmation. Never confirm as owner."
    ),
    (
        "Wait for missing human input or final owner consent in the same conversation with this phase "
        "unfinished. An already saved answer or feedback may be applied to the Draft without final owner "
        "consent. Feedback is not confirmation. Revise and republish the whole document when needed; only"
        " explicit owner consent to the latest revision/hash permits PM completion. No checkpoint, native"
        " readback or Fleet rebind is required by this protocol."
    ),
    (
        "Handle feedback by revising and publishing the document within the SAME execution, then present "
        "the FULL new saved revision/content_hash. Apply saved answers and relevant feedback without "
        "asking for separate permission to save the draft; publishing a Draft revision is NOT owner "
        "confirmation or PM completion. Any document change invalidates earlier consent. Free feedback "
        "and confirmation must not fabricate an answer ID, question or clarification request. Only actual"
        " unresolved gaps require clarification. Confirmation must be the real owner's saved receipt for "
        "the latest exact revision/hash, not a conversational assertion. Unresolved feedback keeps phase "
        "3 unfinished; no final Workflow report is permitted yet. No native checkpoint or rebind is "
        "required."
    ),
    (
        "After owner confirmation read task-tracker sdlc confirmation read --task <task-uuid> --revision "
        "<revision>. Match exact latest revision/hash, owner and task. Confirmation stays in stage=Draft;"
        " it is not a Workflow or Tracker completion."
    ),
]
PM_CONFIRMATION_CHECKS = [
    "The full latest saved requirements document and exact revision/hash were presented to owner.",
    "An actual owner confirmation matches that latest task/revision/hash and owner.",
    "Actual feedback is resolved; no stale consent or invented questions.",
    "No unresolved business blockers. Waiting for owner input leaves this phase unfinished.",
    (
        "Workflow completes in confirmed Draft; only subsequent Tracker completion publishes Backlog / "
        "Ready. No automatic Analyst."
    ),
]
PM_CONFIRMATION_EVIDENCE = [
    "Full saved document, exact revision/hash and owner presentation.",
    (
        "Actual owner confirmation receipt; current report does not require its own future terminal "
        "receipt, comment or status transition."
    ),
]


def completion_instruction(role: str) -> str:
    comment = (
        "AFTER accepted Workflow complete=true, publish an ordinary final Tracker comment with "
        "task-tracker sdlc discussion publish --task <task-uuid> --from-file - and JSON on stdin: "
        "fence={assignment_id,execution_id,agent_id,assignment_version} from fresh context.assignment, "
        "body and a stable idempotency_key. Include result, checks, evidence, limitations and intended "
        "handoff. Read discussion operation --task <task-uuid> --key <same-key> and verify receipt. "
        "Editing or deleting this comment blocks a new handoff. "
    )
    if role == "project_manager":
        return comment + "Use the committed terminal_receipt. " + PM_COMPLETION_INSTRUCTION
    return (
        (
            "The final report has committed. Use the returned workflow_receipt {reference,sha256}, "
            "which is a sibling of terminal_receipt in this response. "
        )
        + comment
        + (
            (
                "Prepare the existing SubmitDeliveryProposal with fence from fresh lifecycle, "
                "workflow_receipt=the returned workflow_receipt, result="
            )
            + f"{RESULTS[role]}"
            + (
                ", idempotency_key=delivery-result:<assignment_id>. Send JSON on stdin using task-tracker "
                "sdlc result propose --task <task-uuid> --from-file -. Read task-tracker sdlc result "
                "operation --task <task-uuid> --key <same-key>. Unknown acceptance requires original-key "
                "readback. Return the real proposal result and finish the run. Fleet verifies real terminal "
                "before Tracker Complete; a proposal is not a transition. Tracker chooses "
            )
            + f"{TARGETS[role]}"
            + (
                ". Repaired candidates repeat Review and Testing; honor the server Rework limit. Never borrow"
                " scheduler credentials, choose a new stage or manufacture evidence."
            )
        )
    )


PM_COMPLETION_INSTRUCTION = (
    "Submit task-tracker sdlc pm completion submit --task <task-uuid> --from-file - with JSON on stdin. "
    "Use ONLY these fields: interaction_protocol='configured-cli-v1'; "
    "fence={assignment_id,execution_id,agent_id,assignment_version} from fresh Tracker "
    "context.assignment, matched exactly to the Workflow terminal receipt; "
    "requirement_revision=terminal_receipt.requirements_revision; "
    "content_hash=terminal_receipt.requirements_sha256; namespace_id=terminal_receipt.namespace_id; "
    "workflow_execution_ref=terminal_receipt.execution_ref; "
    "workflow_operation_key=terminal_receipt.operation_key; "
    "workflow_result_version=terminal_receipt.result_version; "
    "idempotency_key=<one-stable-completion-key>. requirement_revision is singular in this Tracker "
    "request. Match fence.assignment_id to terminal_receipt.assignment_ref, fence.execution_id to "
    "terminal_receipt.tracker_execution_id (NOT Workflow execution_ref), fence.agent_id to "
    "terminal_receipt.concrete_agent_ref and fence.assignment_version to "
    "terminal_receipt.assignment_version. Do not paste a fabricated receipt or add native/lease fields. "
    "Tracker reads the terminal receipt server-to-server and performs atomic Draft -> Backlog / Ready. "
    "Read the exact operation using task-tracker sdlc pm completion operation --task <task-uuid> --key "
    "<same-completion-key>, then task-tracker sdlc pm completion read --task <task-uuid> and task-tracker"
    " sdlc context --task <task-uuid>. Verify the operation.result, completion read.current and fresh "
    "context agree on the same task/root and revision/hash, with stage=Backlog and status=Ready after "
    "completion. After unknown POST acceptance use original-key readback, never a new key or blind "
    "resubmit. Do not require Backlog before Workflow completion. A pasted receipt alone is not "
    "authority. Business completion requires a valid saved document, resolved questions and actual owner "
    "consent, not an external verifier checklist. Configured CLI readiness is a separate runtime check. "
    "Stop at Backlog / Ready; do not create Analysis intent, dispatch Analyst or confirm requirements as "
    "the owner."
)


def terminal_instruction(role: str) -> str:
    common = (
        "PRECOMMIT ASSESSMENT ONLY: finish the current phase work and report actual inputs, outputs, checks, "
        "evidence and unresolved blockers. The report cannot contain its own future terminal receipt, "
        "future final comment or future Tracker transition. These are subsequent actions after acceptance. "
        "Missing, stale, mismatched or fabricated current work/evidence must not pass. "
    )
    if role == "project_manager":
        return common + (
            "The FULL latest saved requirements document, resolved feedback and blocking questions, and "
            "the actual human owner's confirmation must match the exact task/revision/hash/owner in Draft. "
            "Do not claim Backlog before completion or require an external verifier checklist or Analyst. "
            "Submit project-workflow --json step --task <workflow-task-key> --operation-key <stable-key> "
            "--expected-version <current-version> --report - --requirements-revision <confirmed-revision> "
            "--requirements-sha256 <confirmed-content-hash>. Supply the actual report on stdin and use "
            "only the saved owner's exact confirmation. "
        )
    return common + (
        f"Prepare {RESULTS[role]} from verified saved role artifacts and the exact assigned candidate. "
        "Reviewer/Tester may complete verification with a business rework verdict and real findings; "
        "do not pass a defective candidate to obtain acceptance of a correct verification report. "
    )
