# Single-Task Runtime Packet

Bounded opt-in execution uses the existing assignment/bind/step/history bridge,
Supervisor, PM continuation endpoints and repositories/locks. No routing DTO,
second queue, native-runtime proof, Hermes change or additional readback service.
Installed family remains 7 namespaces / 7 workflows / 8 modes / 24 phases.
Instruction/catalog/manifest bytes remain unchanged: catalog `896c4063ac10660e5a95824d560d191ba609fe24e7fa34cd77d6338d6c2ab260`,
manifest `e44b83a7d0909a1e0371cb19919d08b51b29967edfdf4c759f59125e6681f74b`.

## Assignment And Binding

`POST /internal/runtime/assign` accepts `SingleTaskAssignmentRequest` separately
from legacy `RuntimeAssignmentRequest`. The trusted assignment credential owns:

- `instruction_profile=single-task-v1`, exact `instruction_manifest_sha256`;
- `task` (local key), `business_task_ref == root_task_ref` (real canonical Tracker UUID);
- `role_key`, `workflow_key`, `mode_key`, `execution_scope`, `stage_key`;
- `cycle_number`, `attempt_number`, `operation_key`, `assignment_ref`;
- `tracker_instance_ref`, `tracker_project_ref`, `execution_ref`, `concrete_agent_ref`;
- `task_revision`, `lease_ref`, `lease_version`, `fencing_token`, `exact_input_refs`;
- existing `expected_revision/status/mode_key/cycle_number` CAS fields.

There are no queue/work-item/workspace/decomposition/integration resources in this
request. Those legacy DB columns remain NULL, including stage/workspace/lease
generation projections; task/lease revisions retain their actual meanings in
the immutable context instead of being relabeled. Base admission is forbidden.
Domain validates task=root, role/mode/stage/scope and the actual installed family.
Optional `tech_execution_workspace_ref` / `tech_execution_attempt_ref` may carry
a real complete pair for delivery only; neither is mandatory or synthesized.

`POST /internal/runtime/bind`: `SingleTaskBindRequest` retains existing bind fields,
requires actual `concrete_agent_ref`, `session_run_id`, profile/manifest and
`expected_binding_state=unbound`. Only the existing assignment credential may bind.
Exact replay returns the same result; changed body/key collisions fail closed.
Bind result adds `single_task_binding`, `single_task_context_sha256`; the response
adds `execution_token` using the existing scope secret with a separate HMAC domain.
The secret must remain distinct from bridge/readback credentials.

One nullable `task_runtime_assignments.single_task_binding_json` stores this exact
binding without mutating the original assignment payload/hash. Legacy rows remain
NULL. For enrolled PM the existing PMRun ledger supplies the current resumed run;
the original binding remains immutable.

## Step And History

`POST /internal/runtime/step`: `SingleTaskStepRequest` retains existing step fields,
adds profile/manifest, requires session UUID and the server-issued context hash.
Uses existing runtime role credential and `X-Workflow-Execution-Token`; wrong role,
missing token, stale session/context, foreign family or persisted drift cannot
reach replay/evaluation. Version 1 does not bypass the assignment guard. Human/local
Supervisor cannot create or execute an unbound profile task.

The context hash is an INTERNAL saved-binding integrity fence, not native-runtime
attestation or a Tracker lease check. There is no pre-model network probe. Steps
do not renew lease expiry; the holder validates/renews through Tracker. No
caller-selected observed owner/lease fields are accepted.

Supervisor history keeps exact effective binding/context and its hash in the
existing evaluation snapshot. Profile report responses explicitly include
`complete` and `single_task_context_sha256`; exact operation replay returns the
persisted response. [Terminal receipts](single-task-terminal-receipt.md) now publish
an actual Workflow ArtifactReceipt; this is not a Tracker transition receipt.

`GET /internal/runtime/history` requires existing runtime credential/execution
token plus `task`, `session_run_id`, `instruction_profile`,
`instruction_manifest_sha256` for profile tasks. Profile records include the
saved binding/hash. Legacy query/response/replay serialization remains unchanged.

## Typed PM Continuation

Existing `/internal/runtime/v1/pm/{bind,checkpoint,resume,rebind,readback}` endpoints
accept separate `SingleTaskPM*` DTOs with exact profile/manifest. Legacy PM request
DTOs, including `PMResume.answer_event_ref`, remain unchanged. Existing namespace
ownership provisioning/authorization is reused; no new owner is added.

Checkpoint keeps existing PM identity/CAS/run fields and `checkpoint_ref`, adds
required nullable `requirements_revision`, `requirements_sha256`. Both are null
before the first document, otherwise both identify a real revision/hash. This
lets brainstorming wait for owner feedback without a fake initial document.
Optional clarification ref/version must be a real pair and requires an existing
document. Resume echoes that exact checkpoint/document,
retains `new_session_run_id` and uses only:

```json
{
  "input": {"input_kind": "confirmation", "input_id": "<actual UUID>"},
  "input_receipt": {"reference": "<actual Tracker receipt reference>", "sha256": "<actual sha256>"}
}
```

`input_kind` is `answer|feedback|confirmation`; IDs are respectively actual
`Answer.id`, `PmFeedbackReceipt.message_id`, `Confirmation.id`. Only answer
requires clarification refs. Feedback/confirmation reject fake answer fields.
Only feedback can resume a pre-document checkpoint. Answer and confirmation
require an existing requirements revision/hash; ordinary legacy PM schemas are
not relaxed.
The trusted parent Fleet assignment adapter reads Tracker and validates receipt,
task/owner/current document before submitting this packet. Workflow does not
treat an agent assertion or the supplied reference as independently fetched proof.
Tracker lease-resume remains a trusted server Scheduler operation, not agent CLI.

Existing actual old-run terminal readback remains required before resume; rebind
uses the existing reserved new run. No new runtime observation fields/service.
`execution_ref`, assignment and cycle stay the same. The existing checkpoint JSON
stores accepted `resume_input={input,input_receipt}`; current readback and immutable
PM operation result expose it. Starting a new checkpoint clears the current input
while preserving its historical operation. Changed receipt under the same key,
late revision/hash, old run/token and resume of completed Workflow are rejected.

Phase 3 final report is rejected without a current typed confirmation receipt.
Feedback can publish a new document and checkpoint in the same execution; its
new revision/hash rejects stale consent. Actual owner/receipt/latest-document
verification belongs to Tracker plus the trusted adapter; instructions still
require PM CLI confirmation readback before final report. PM never dispatches Analyst.

## Migration And Remaining Integration

Exactly one additive migration: `0015_single_task_assignments`, predecessor
`0014_launch_profile_only`. It preserves prior CHECK predicates and legacy/history
rows, excludes the new family from the legacy binding branch, adds the narrow
task=root / NULL-decomposition branch, and permits an absent delivery tech pair
only for this profile. A partial tech pair still fails. No destructive downgrade.
SQLite tests cover actual predecessor upgrade, repeat readback, preserved legacy
rows/history/predicates, three-phase execution, typed PM continuation and contracts.

`SingleTaskNamespaceBinding` remains unchanged and `live_activation_allowed=false`
until actual parent Tracker/Fleet policy integration. `runtime_ready=false`
is the same integration boundary, not a claim that the bounded bridge is absent.
Remaining parent QA: PostgreSQL upgrade/concurrency, actual installed deployment
manifest, authorized owner confirmation CLI direct GET, trusted receipt validation,
Scheduler lease-resume/PM actual completion ordering and a usable immutable Workflow
terminal ArtifactReceipt for non-PM delivery proposals. The latter is now implemented
in [Single-Task Terminal Receipt](single-task-terminal-receipt.md); parent still
owns actual run/receipt verification and policy activation. No Docker/PG/deployment,
runtime configuration, secrets or other repositories were changed by this packet.

Parent integration preserves one additive migration and the exact installer family.
Separate source-qualified tests are not PostgreSQL/live acceptance. Dependent Drafts:
[Fleet81](https://github.com/FerrPOINT/fleet-control/pull/81),
[Tracker152](https://github.com/FerrPOINT/task-tracker/pull/152),
[Forge103](https://github.com/FerrPOINT/CI-CD/pull/103). Terminal receipt publication
and actual consumer rollout remain explicit follow-up, not a new registry.

Generated public request/readback schema: [pm-continuation-openapi.json](pm-continuation-openapi.json).
