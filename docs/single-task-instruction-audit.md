# Single-Task Instruction Audit

Source-qualified audit of the actual installable family: seven professions,
eight role/modes and 24 phases. Tracker was inspected read-only at
`b8b9546ff2a083d849028ccceadb0c699a7ed71b`. No live agent/PG/deployment evidence
is claimed. Runtime DTOs, producers, migration and public OpenAPI are unchanged.

## Findings And Corrections

1. The shared context instruction called questions for delivery roles, but
   `backend/app/src/sdlc_lifecycle.rs:delivery_request_policy` allows their own-task
   context/requirements/events/lifecycle, not clarifications. Ordinary comments
   and attachments are outside both delivery and PM task-grant prefixes
   (`backend/api/src/middleware/sdlc_auth.rs:pm_request_policy`). The overlay now
   selects permitted commands by role and requires parent-supplied immutable
   sources or explicit authorized access, not borrowed owner/scheduler credentials.
2. PM instructions still described typed continuation and confirmation readback
   as unimplemented. Actual profile schemas now use unified input/input_receipt,
   and `backend/cli/src/sdlc_pm_commands.rs:confirmation` directly reads the retained
   confirmation. Instructions now name actual input IDs and direct readback;
   obsolete answer_event_ref is removed from installed profile guidance.
3. `PublishQuestion` requires a real requirement_revision
   (`backend/domain/src/sdlc.rs`), while pre-document feedback is valid without
   a document. PM can checkpoint early brainstorming with required null/null
   requirements fields and feedback only, in the same execution. A formal question
   follows a real saved revision; no placeholder document or fake question/answer
   is created just to wait. Exact owner confirmation still precedes final Workflow
   completion, and any changed document invalidates earlier consent.

The frozen fb9dd53 preset/proposal and legacy catalog pins/source are untouched.
Corrections are in the installable overlay, not legacy history or native Hermes.

## Eight-Mode Handoff Matrix

| Role / Mode | Actual Result | Allowed Next Stage / Status |
| --- | --- | --- |
| PM / draft | Exact owner confirmation receipt; no delivery proposal | Backlog / Ready, then Analysis / Ready by parent pickup after PM actual completion |
| Analyst / analysis | analysis ArtifactReceipt | Architecture / Ready |
| Architect / decomposition | design ArtifactReceipt, architecture/plan for one task | Development / Ready |
| Developer / initial | commit_sha, changes ArtifactReceipt, checks ArtifactReceipts | Review / Ready |
| Developer / rework | Same typed Developer result, new candidate and finding/fix verification | Review / Ready, then fresh Testing |
| Reviewer / delivery | verdict approved or rework, report ArtifactReceipt | Testing / Ready or Rework / Ready |
| Tester / delivery | verdict passed or rework, report ArtifactReceipt | Deployment / Ready or Rework / Ready |
| DevOps / delivery | deployment and verification ArtifactReceipts | Deployment / Completed |

All eight modes start with the scoped existing Workflow CLI step before Tracker
reads, dialogue or file/CI work. The family never activates integration modes,
children, decomposition cards, delivery DAGs or integration barriers. Status
Ready/InProgress/Completed remains separate from waiting_reason/runtime state.
Review/Testing defects require fresh Review and Testing after Developer rework.
DevOps terminal evidence is artifact/deployment/health/acceptance, not build alone.

## Actual CLI And Consumer Prerequisites

PM context uses existing `task-tracker sdlc context`, `requirements`, `input` and
`questions`, each with `--task <UUID>`. Delivery roles use context/requirements,
plus authorized supplied predecessor/source artifacts. The parent must make
required comment/attachment content available as immutable inputs; do not require
an agent to call an endpoint excluded by its task grant. Missing authorized
sources remain a blocker and may not be summarized into invented evidence.

PM publishes only real drafts/questions through existing `sdlc revision publish`
and `sdlc question publish --task <UUID> --from-file <file>`. Actual MachineFence,
revision/version and idempotency values are required. Pre-document resume uses
`input_kind=feedback`, actual `PmFeedbackReceipt.message_id`, and an actual
input_receipt reference/hash. Answer/confirmation require the existing exact
document; only answer has the real clarification reference/version pair.
The trusted parent adapter, not the agent, validates Tracker input/receipt and
old run terminal before Workflow resume. No fake answer ID or additional PM cycle.

PM final readback is the supported command:

```text
task-tracker sdlc confirmation read --task <UUID> --revision <REVISION>
```

It directly calls `GET /api/v1/issues/{UUID}/sdlc/requirements/{revision}/confirmation`.
Match actual ID/task/revision/content_hash/owner_subject/created_at and the FULL
latest owner-reviewed document. The receipt's historical stage=Backlog is not
current lifecycle completion. PM never confirms as owner, reads Analysis intent
as a substitute, or dispatches Analyst; parent waits for PM actual completion.

Every non-PM final step requires accepted Supervisor PASS/done with the immutable
actual Workflow receipt, then the existing producer/readback while the run is alive:

```text
task-tracker sdlc result propose --task <UUID> --from-file <proposal.json>
task-tracker sdlc result operation --task <UUID> --key <original-key>
```

The actual strict proposal has exactly fence/workflow_receipt/result/idempotency_key.
DeliveryFence is assignment_id/execution_id/fencing_token/lease_id/expected_lease_version.
ArtifactReceipt is reference/sha256. Use actual owner-provided fence and evidence,
not narrative success, invented hashes or an agent-selected owner/lease. Role
result fields above match `backend/domain/src/sdlc_lifecycle.rs:DeliveryResult`.
Assessment needs_rework is not a wire verdict; serialize reviewer approved|rework
and tester passed|rework. Wire devops maps to Fleet dev_ops only at that boundary.

Readback must match proposal_id/task/assignment/execution/agent/producer_subject,
workflow_receipt/result/output_sha256 and the original operation. Unknown effect:
read that operation before exact key/body replay; never issue a new key to retry.
Return actual proposal receipt identifiers and end the run, without stage polling.
The proposal does NOT transition the stage. After actual acceptable runtime terminal,
Fleet must verify the immutable Workflow terminal receipt through its existing
authenticated readback, exact binding/session/run/fence/result, all referenced
artifact contents/hashes and current Tracker lease/assignment before schedulerComplete.
Re-read `GET /api/v1/issues/{UUID}/sdlc/lifecycle` and its real operation/result
receipts using the registered parent authority. This API exists in
`backend/api/src/routes/sdlc_delivery.rs`; the inspected CLI has no lifecycle
subcommand. Do not invent one or give agents scheduler completion credentials.
No generic patch, issue transition, board move or manual status substitution.
API registration, authorized grants, receipt resolution, health/acceptance and
actual consumer policy must all be available; 403/404/missing evidence is a blocker.
Tracker now has the scoped sealed-artifact publisher on the existing attachment
CLI/API, and Fleet has a bounded fixed-origin resolver. These source packages do
not establish live producer/consumer compatibility. Technical instructions require
actual uploaded bytes, assignment binding and raw SHA-256 verification before the
final Workflow report; PM's ordinary attachment access remains prohibited.
Missing publisher/resolver capability blocks execution. No references, hashes,
human credentials or extra publisher CLI are invented.

## Source Hashes And Rollout Boundary

```text
catalog:  b7b8bed470dc8a8730c8c1b1af8db0d556afec652394c569a9b0e97a64b6dcfd
manifest: e5e67111d89a0eeae89b6f78da6c887281cca187d7ea7792822d76ce2c4cc7a8
```

Only instruction changes trigger this family/hash revision. Existing two source
hash pin constants are synchronized; no DTO shape or producer behavior changes.
All seven routes must use the same actual installed family, never mix old/new
manifest pins. The PM producer fixture is refreshed from actual temporary SQLite
endpoints, with synthetic authority and only execution tokens redacted.

This is source-only, not an in-place catalog upgrade or live activation. Existing
bootstrap intentionally rejects old installed content as drift; do not rewrite
old instructions/bindings/history or add a permissive dual-hash fallback. Parent
owns the coordinated existing-installation rollout/versioning decision; fresh
disposable QA may install this source directly. Legacy pins/history and archived
source remain unchanged; live_activation_allowed remains false until actual policy.

## Regression Evidence

`tests/test_single_task_instructions.py` audits the installable artifacts, all
eight first/final steps, role grants, strict result vocabulary, PM small-iteration
brainstorming, pre-document feedback, exact confirmation ordering and single-task
boundaries. It does not mistake the frozen historical preset for the installed
content. Existing installer, source provenance, runtime and terminal tests cover
actual scoped SQLite execution/readback. No PG/Docker/heavy/live QA is run here.

On 14 October the regenerated installable artifacts passed 64 instruction,
artifact-instruction and catalog tests, plus source-generation `--check` and scoped
Ruff. The runtime/terminal/installation run passed 85 cases; its remaining failure
was the old expected manifest hash in the PM terminal fixture. Both initial and
terminal wire fixtures were regenerated from actual isolated producer responses,
not hand-edited, and all ten focused producer/terminal-fixture tests then passed
without update mode. Only synthetic authority/native inputs and redacted execution
tokens are used. No live model, installed catalog update or full SDLC acceptance
is inferred from these results.
