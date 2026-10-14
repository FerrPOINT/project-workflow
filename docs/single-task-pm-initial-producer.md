# Single-Task PM Initial Dispatch Producer

The current producer supports this sequence without a new PM assignment endpoint:

1. `POST /internal/runtime/assign` with `SingleTaskAssignmentRequest`.
2. `POST /internal/runtime/bind` with `SingleTaskBindRequest`.
3. `POST /internal/runtime/v1/pm/bind` with `SingleTaskPMBind`.
4. `POST /internal/runtime/step` with `SingleTaskStepRequest`, no report.

The first three calls use the existing `project_manager` assignment credential.
The fourth uses the existing PM runtime role credential and the execution token
issued by call 3 in `X-Workflow-Execution-Token`. No runtimeCompatibility,
Base admission/proof, routing DTO, synthetic work item, queue, decomposition,
workspace or integration reference is needed or accepted in the profile request.
Tracker/Fleet policy owns dispatch admission and lease freshness; this is not live
activation acceptance. `live_activation_allowed=false` remains unchanged.

## Actual Fixture

[`single_task_pm_initial_dispatch.json`](../tests/fixtures/single_task_pm_initial_dispatch.json)
contains exact requests and parsed HTTP response bodies from the real endpoints
with the real installer and temporary SQLite repositories. It also contains the
existing runtime observation input and PM operation readback. Only top-level
execution-token values are replaced by explicitly named markers. Tests consume
the actual issued tokens, assert rotation at PM enrollment and reject the old
token/hash before the admitted first step. No deployed credentials are captured.

The authority and all UUIDs/keys/input contents are synthetic test data, not
live Tracker/Fleet evidence. Numeric catalog IDs are this fixture's persisted IDs;
Fleet must obtain actual IDs from installation readback, never copy these IDs.
Fixture response strings include the current installed instructions verbatim.
The later [instruction audit](single-task-instruction-audit.md) refreshes the
fixture from actual isolated endpoints for its new source hash, with the same
producer logic, request shapes, Fleet keys, original input and token redaction.

Fleet-shaped fixture identity uses local key `SDLC-7`, assignment operation
`pm-draft:<assignment UUID>`, general bind key `fleet-pm-runtime-bind:<creation UUID>`,
PM bind key `fleet-pm-bind:<creation UUID>`, binding `fleet:pm:<creation UUID>`,
run `run_pm` and session_run_id equal to the creation UUID. Its original input
has title `Owner goal` and description `Exact original input`; the canonical
Tracker hash is `8f09dacd2e9dcd6335b867319edeb40a412b1affb0906fa4f560f4b12ef6cdcf`.
The exact input ref contains only `kind=pm_draft_input`, UUID `ref` and `hash`:
omitted `revision` stays omitted in assign/bind/readback and the assignment ledger.
An explicitly supplied null is still distinct for idempotency; it is not silently
collapsed into omission. Legacy request schemas/serialization are unchanged.

## Builder Mapping

- Assignment: `role_key=project_manager`, `workflow_key=single-task-v1:project_manager`,
  `mode_key=draft`, `execution_scope=business`, `stage_key=Draft`, `task=root`
  through equal canonical `business_task_ref` and `root_task_ref`. `task` itself
  is the Workflow-local task key. Preserve the issued context and original input
  `exact_input_refs` (`kind/ref/revision/hash`) without fabricating a requirements
  revision before it exists. The test computes the original-input hash from
  exact UTF-8 canonical JSON of description/title, matching Tracker's producer.
  `expected_revision=0` is the initial Workflow assignment CAS; `task_revision`
  is the separate actual Tracker task revision. Input-ref `revision` is a string.
- General bind: take `assignment_revision`/`assignment_operation_key`/`assignment_ref`
  and mode/cycle/attempt from the accepted assignment; use the actual Fleet
  `session_run_id`, concrete agent and binding/run references. Initial state is
  `expected_binding_state=unbound`.
- PM bind identity: `task`, `execution_ref`, `tracker_instance_ref`,
  `tracker_project_ref`, `task_ref=business_task_ref`, `root_ref=root_task_ref`,
  `agent_ref=concrete_agent_ref`, assignment operation/ref/revision. Add profile,
  exact manifest, separate PM `operation_key`, `expected_version=0`, and the
  same bound `binding_ref/hermes_run_ref/session_run_id`.
  The initial PM fence is server-assigned 1, separate from Tracker fencing_token.
- First step: keep the original assignment/ref/mode/cycle/attempt and bound run
  identity, `expected_status=active`, `expected_phase_code` from assignment
  `current_phase_code`, a distinct original step operation key and no report.
  **Replace** the general-bind integrity hash and execution token with the PM-bind
  `result.single_task_context_sha256` and top-level `execution_token`.

General assign/bind respond `{ok,exit_code,result}`; bind adds top-level
`execution_token`. Initial assign has null concrete agent/binding/run columns
until bind and does not echo the complete context; retain the original command.
Assignment replay after binding returns the current assignment projection, not
the earlier unbound response. Never infer a missing context from this projection.

PM bind responds `{ok,result,execution_token}`, **without** `exit_code`.
`result` is the existing snapshot: contract_version=1, immutable identity,
state=active, version=1, fence=1, exact session/binding/run, checkpoint=null,
resume_operation_key=null, resume_session_run_id=null, terminal_readback=null,
workflow_step_allowed=true, resume_delivered=false, profile/manifest and context
hash. The profile is opt-in; contract_version=1 here is not Tracker route version.

First step responds `{ok,exit_code,output,result}`. Its cursor field is
`result.phase_code=PM-DRAFT-01`, not `current_phase_code`. Result also contains
status=active, instructions, phase_contract (including allowed_tools), workflow_id,
mode_id/mode_key and cycle_number. It has **no complete or workflow_receipt field**;
do not require complete=false. No model evaluation, phase advance or step-history
record is produced by a no-report instruction read. Repeating it reads the current
cursor, not a frozen report receipt; use a distinct key for the subsequent report.

Existing `POST /internal/runtime/v1/pm/readback` takes the same profile+PMIdentity
and optional operation_key. It returns the current snapshot plus `operation`
when a key is requested; `operation.result` is the accepted operation snapshot.
An assignment-credential readback of an active execution also returns its actual
top-level execution token. Exact PM bind replay is covered without extra runs.

## Preconditions And Blockers

- Installer/config selector and installed-manifest validation must succeed.
  General assign/bind alone cannot admit a PM step before PM enrollment.
- PM namespace ownership must already be provisioned for the exact Tracker
  instance/project. Existing `NamespaceOwnershipService.provision` is immutable
  and rejects a second PM namespace for the same Tracker pair. An existing legacy
  owner is therefore a parent provisioning/adoption decision, not an instruction
  to create another registry, overwrite ownership or change this contract.
  See `application/namespace_ownership.py:provision` and
  `application/pm_execution.py:PMExecutionService.bind`.
- Existing PM readback/scope configuration must be available with distinct
  credentials (`interfaces/ui/routes/pm_api.py:configured`). The actual running
  readback must match PMIdentity, session, binding/run, fence=1,
  dispatch_operation_key=PM-bind operation_key and checkpoint_ref=null
  (`application/pm_execution.py:PMExecutionService._proof`). Missing/foreign
  ownership, a stopped/mismatched run or unavailable callback cannot enroll PM.
- `/internal/runtime/v1/pm/assign` remains legacy `PMDraftAssignment` with
  runtimeCompatibility and `TaskService.assign_pm_draft`
  (`interfaces/ui/routes/pm_api.py:assign`). Sending the profile general packet
  there returns 422. No new endpoint or speculative schema patch is needed.

## CLI And Terminal Handoff

The existing first-operation CLI is:

```text
project-workflow --json step --task <workflow-key> --operation-key <original-step-key> --runtime-request <private-request.json> --execution-token-file <private-token-file>
```

Fleet supplies the final PM-enrolled request/token; the agent must not derive the
hash or reuse the general-bind token. The CLI outputs the HTTP `result` at its
JSON root. PM completion remains after actual owner confirmation in the same
execution, using the existing typed checkpoint/resume path.

The non-PM immutable terminal producer, exact readback DTO, final-report CLI,
Tracker proposal handoff and parent PG selectors are documented in
[`single-task-terminal-receipt.md`](single-task-terminal-receipt.md).
That receipt is not produced by this PM first instruction read.

## Focused QA

Run without `-m integration`:

```powershell
& C:/git/azhukov/sdlc/project-workflow/.venv/Scripts/python.exe -m pytest -q tests/test_single_task_pm_producer.py --timeout=60 -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
```

Nine cases cover exact producer exchanges/replay/readback, original input,
first-step admission, no extra assignment/execution/run, old-token/hash rejection,
missing/foreign ownership, mismatched/stopped/unavailable actual run observation
rejection by legacy PM assign, omitted-input-field preservation and equality of
legacy request schemas with the existing public OpenAPI artifact.
Callback authority is synthetic; this is not
a Fleet builder or live dispatch E2E. No PG, Docker or runtime changes.
