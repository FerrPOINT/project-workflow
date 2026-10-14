# Single-Task Runtime Packet

## Runtime Routing Follow-Up: 14 October 2026

Source package `a7cfc454845bce83aebd2fc6342e7a16b8b95ad7`, integrated as
`f0d1780`, corrects generic capability validation of the builtin profile and
selects namespaces from validated typed requests/original assignment family,
not the process-global default alone. Legacy requests retain legacy routing.
The original Base ordinary-execution prohibition, role/credential purpose,
manifest/native binding, execution token and fence checks remain in place.
No DTO, URL, catalog, manifest hash, migration or Hermes change is included.

Affected component suites report263 passing tests, scoped Ruff/mypy and diff
checks; the final post-test changes are formatting and a local optional-int
annotation. PostgreSQL/concurrency, whole-suite coverage, actual image/runtime
and installed legacy/profile coexistence still need independent qualification.
The frozen d0 CLI remains a separate input, not relabeled as this server package.
Base's matching catalog3/4 descriptor probe is implemented separately; an actual
Base4 companion image and preserved-history rollout are not claimed here.
Counter-review identified remaining family-specific capability-readiness,
unsupported generic-rebind advertising and Base catalog-auth/role-map cases.
Their paired producer/consumer follow-up is required before rollout; the263
component passes do not close those newly identified cases.

Bounded opt-in execution uses the existing assignment/bind/step/history bridge,
Supervisor, PM continuation endpoints and repositories/locks. No routing DTO,
second queue, native-runtime proof, Hermes change or additional readback service.
Installed family remains 7 namespaces / 7 workflows / 8 modes / 24 phases.
The runtime packet did not change instruction bytes. The subsequent
[instruction audit](single-task-instruction-audit.md) records current source hashes
and grant-aware PM/context corrections; runtime DTOs and producer behavior are unchanged.

## Assignment And Binding

For the validated single-task technical family, a new local execution key may
start with Tracker's nonzero Rework cycle. Assignment revision still starts at 1;
actual cycle is retained through bind and first step. Legacy/Base new-task
assignments and a new PM Draft still require cycle 0. Fleet must not normalize
cycle to zero or reuse another execution's display key to satisfy this sink.

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

The original profile migration is `0015_single_task_assignments`, predecessor
`0014_launch_profile_only`. It preserves prior CHECK predicates and legacy/history
rows, excludes the new family from the legacy binding branch, adds the narrow
task=root / NULL-decomposition branch, and permits an absent delivery tech pair
only for this profile. A partial tech pair still fails. No destructive downgrade.
SQLite tests cover actual predecessor upgrade, repeat readback, preserved legacy
rows/history/predicates, three-phase execution, typed PM continuation and contracts.

`SingleTaskNamespaceBinding` remains unchanged and reports
`live_activation_allowed=false` / `runtime_ready=false`. This installation response
is not live admission even though the parent source policy/consumer hooks now exist.
The current exact Workflowd0/Tracker CLI2aa/server817/Fleetd5 source inventory and
already obtained parent qualification are recorded in the
[instruction audit](single-task-instruction-audit.md). Tracker registers actual
lifecycle/result routes and authorizes current delivery-grant readers; its CLI
supports `sdlc lifecycle --task` and `sdlc result read --task --result`.
Authorized PM confirmation direct GET and the actual immutable Workflow
terminal ArtifactReceipt are implemented, not current missing producers; see
[Single-Task Terminal Receipt](single-task-terminal-receipt.md).

Fleet d5 connects the receipt/proposal consumer to actual raw-artifact validation
using delegated child CLI credentials, outside the fence gate, then performs a
fresh authority/fence read before existing Complete. No scheduler credential is
given to the agent. Exact owner confirmation still precedes PM Workflow completion
and actual native completion; an Analysis intent alone cannot assign Analyst.

Remaining deployment acceptance: compatible installed manifest and configured
credentials/policy, actual run/receipt/lease-resume readbacks, all-role and Rework
flows, plus deployment artifact/health/acceptance. Source qualification, including
parent PG gates, is not installed-image or live-agent acceptance. No Docker/PG/build,
deployment, runtime configuration, secrets or other repositories were changed by
this docs-only reconciliation.

Parent integration preserves the original profile migration and the exact installer family.
Source/unit evidence and parent PostgreSQL qualification remain separate from live
acceptance. Parent-owned integration references (not rollout approval):
[Fleet81](https://github.com/FerrPOINT/fleet-control/pull/81),
[Tracker152](https://github.com/FerrPOINT/task-tracker/pull/152),
[Forge103](https://github.com/FerrPOINT/CI-CD/pull/103). Terminal receipt publication
and the consumer hook are implemented in source; actual rollout remains explicit
follow-up, not a new registry.

Generated public request/readback schema: [pm-continuation-openapi.json](pm-continuation-openapi.json).

## Subsequent PM Business Review

A trusted assignment may start another `draft` PM execution of the same Tracker
task/root in the existing single-task PM namespace after the previous PM Workflow
has a validated sealed final step and its original native run is confirmed terminal.
Use the new authoritative execution's Workflow task key, execution UUID, assignment
and session-run UUID; do not replace the original Workflow task or reuse its keys.
The existing role credential, assign/bind, execution-token step and history APIs
remain unchanged. The assignment and PM bind both check prior completion under
the existing namespace lock. Unknown readback, a live prior run, missing
seal or pending continuation refuses enrollment. Legacy PM repeat stays denied.
Only the existing trusted runtime observation establishes quiescence, never EOF
or a Stop ACK. Native terminal status does not itself establish business success.

The same unreleased `0015_single_task_assignments` migration also replaces the permanent
`uq_pm_task_agent` constraint with a lookup index. Execution, Workflow-task and
run/fence uniqueness remain; no execution, assignment, operation or history rows
are deleted or repurposed. Downgrade refuses rather than discard repeat history.
Released migrations 0001 through 0014 remain byte unchanged. The existing guarded
migration entrypoint supports their real ancestry from `0001_initial` to 0015;
no stamp, reset or catalog adoption is needed to migrate the schema alone.
The same instructions and exact owner-confirmation final-step guards apply to
the new execution; no new mode, generic rebind capability or Hermes change exists.
SQLite/HTTP regression evidence is not PostgreSQL or installed-runtime acceptance.
