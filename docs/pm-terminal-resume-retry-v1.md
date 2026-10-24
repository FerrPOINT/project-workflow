# PM Terminal Resume Retry V1

Status: source implemented and verified with isolated SQLite/TestClient fixtures
and synthetic authenticated native readback. PostgreSQL integration, deployment
and live CLI handoff remain open. This contract does not authorize installation,
native dispatch, another business input or owner confirmation.

This is an extension of the [PM continuation contract](pm-continuation-contract.md).
The [generated OpenAPI](pm-continuation-openapi.json) is exported from the actual
application with `python -m scripts.export_pm_openapi`; its parity test passes.

## Supported State

The original source run accepted a checkpoint and became terminal. Ordinary
`/resume` reserved a target, but that target became terminal before `/rebind`.
Workflow therefore remains `resume_pending`, bound to the original source and
checkpoint. The failed target has no Workflow `PMRun` or accepted checkpoint.

For example, source fence1, failed pending fence2 and the new pending fence3 are
different facts. A terminal target is not successful input delivery. There is no
reset to `waiting` or `active`, fence rollback, fabricated first-step receipt or
replacement of the original source checkpoint.

## Command And Authorization

`POST /internal/runtime/v1/pm/resume-retry` accepts the closed
`SingleTaskPMResumeRetry` request:

| Fields | Meaning |
| --- | --- |
| `contract_version` | Exactly 1. |
| Existing `PMIdentity` fields | Task, execution, Tracker instance/project/task/root, concrete agent and assignment identity. |
| `instruction_profile`, `instruction_manifest_sha256` | Exact installed `single-task-v1` profile and saved manifest. |
| `operation_key`, `expected_version`, `expected_fence` | New retry key and current pending CAS cursor. |
| `session_run_id`, `binding_ref`, `hermes_run_ref` | Retained bound source, not the failed target. |
| `checkpoint_ref`, `prior_resume_operation_key` | Exact retained source checkpoint and current pending resume/retry key. |
| `input`, `input_receipt` | Existing typed input kind/UUID and receipt reference/SHA256, exactly matching the saved resume. |
| `failed_session_run_id`, `failed_hermes_run_ref`, `failed_binding_ref` | Exact terminal, never-rebound pending target. |
| `new_session_run_id`, `new_binding_ref` | Unused target UUID and exact `fleet:pm:<new_session_run_id>` binding. |

Source, failed and new run IDs and binding refs must be distinct. The new key
must differ from the prior resume key. No prompt, stage override, caller-supplied
proof, checkpoint for the failed target, or owner answer is accepted.

Only the existing `project_manager` assignment credential may issue this
command. Runtime and catalog credentials do not acquire retry authority.
Installed profile/manifest, original assignment namespace and concrete-agent
mapping are checked through the existing machine bridge. The capability list
advertises `resume-retry` only for configured single-task assignment callers.

The existing fixed `PROJECT_WORKFLOW_PM_READBACK_URL` and separately configured
callback token supply terminal evidence. The request cannot supply a callback
URL, token or terminal assertion. Redirects are not followed. Callback failure
or an unknown/nonterminal/foreign result blocks the retry without a reservation.

## Locked Validation And Transition

The producer reuses the task lock and run-ID advisory locks. It verifies the
current assignment/execution, `resume_pending` state, version/fence, phase,
bound source and exact pending operation result. Input, receipt, checkpoint,
profile and manifest must still match. The failed target must not already have
a `PMRun`; the new target must not be used or reserved elsewhere.

The retained source terminal observation must match its identity, binding,
native run, fence and checkpoint. The independently authenticated failed-target
callback must match its identity, target UUID, native run, binding, current
pending fence and prior resume dispatch key. Its status must be one of
`completed`, `failed`, `cancelled`, `stopped`, and its `checkpoint_ref` must be
null. The producer does not copy the source checkpoint onto the failed run.

On success, the producer appends the genuine failed terminal observation as
`PMRun` history and stores a `PMOperation(kind=resume_retry)` receipt. It increases
version and fence, replaces only the pending target/key, and keeps the same
source, checkpoint, saved input and `resume_pending` state. Task/assignment/step
history is not advanced by this command. Workflow never sends a native POST.

## Result And Readback

The closed response is `PMResumeRetryResponse`, not `PMExecutionSnapshot`:

```json
{
  "ok": true,
  "result": {
    "contract_version": 1,
    "operation_key": "retry operation key",
    "request_sha256": "canonical typed request SHA256",
    "prior_resume_operation_key": "retained pending operation key",
    "input": {"input_kind": "feedback", "input_id": "existing input UUID"},
    "input_receipt": {"reference": "existing receipt reference", "sha256": "existing receipt SHA256"},
    "source": {
      "session_run_id": "retained source UUID",
      "binding_ref": "retained source binding",
      "hermes_run_ref": "retained source native ref",
      "fence": 1,
      "checkpoint_ref": "retained source checkpoint"
    },
    "failed_terminal": {"...": "existing RuntimeObservation wire"},
    "pending": {"...": "existing PMExecutionSnapshot wire after CAS"}
  }
}
```

The example illustrates structure, not a valid executable request/receipt.
`request_sha256` hashes the complete typed request using the existing canonical
JSON helper, without an additional operation tag. `pending` retains the existing
snapshot wire shape and sets `resume_operation_key` to the retry key. Its
`single_task_context_sha256` is freshly computed from the binding and current
fence; it changes when the pending fence increases and must not be forced equal
to the predecessor hash. No execution token is returned by retry.

Existing `/readback` with the exact operation key returns the current outer
snapshot and the original distinct receipt under
`operation={operation_key,kind,request_sha256,result}` with `kind=resume_retry`.
The adapter uses its assignment credential. Runtime readback still requires
`X-Workflow-Execution-Token` bound to the current identity, source/native refs,
binding, session UUID and fence; an old-fence token is rejected. Reading a pending
receipt does not issue a token or prove current native health.

Same key and exact payload replay the saved receipt without another callback,
target allocation or history mutation, including after a subsequent rebind.
Changed payload/kind conflicts. A different key cannot replace a target already
retried or rebound. For an unknown POST result, use original-key readback/replay,
not a second retry key or another owner input. A missing receipt is not proof
that native dispatch is safe.

Only the existing `/rebind` path, with actual running callback proof for the
reserved new target/key/fence/checkpoint, changes Workflow to active and supplies
its normal execution scope. The existing no-report first instruction and CLI
handoff still have to succeed while that native run is alive.

## Migration And Verification Limits

Additive migration `0019_pm_terminal_resume_retry` follows
`0018_identity_deletion_owner` and extends only `ck_pm_operation_kind` with
`resume_retry`. It adds no table, queue, scheduler or receipt rewrite. Existing
operation rows remain intact. Downgrade explicitly refuses while any
`resume_retry` receipt exists; it never deletes retained history to restore the
old CHECK. PostgreSQL transactional DDL and concurrency remain integration gates.

Source evidence on producer `ba990991e7053dd068991854e35a390d4d8f995b`:

- 33 retry cases pass against isolated SQLite/TestClient with synthetic native
  callback data, including exact replay, canonical bootstrap identity, scoped
  readback, failed-target null checkpoint, rebind and populated-history downgrade.
- Four targeted review cases pass, including actual generated OpenAPI parity.
  Ruff/diff checks pass; scoped producer/API mypy passes. These are not a full
  suite, full coverage, PostgreSQL or deployed acceptance claim.
- Main reports actual Fleet Rust shared-golden validation 5/5 PASS on `3dae`.
  The golden used actual typed producer enrollment for `SDLC-7`, request, original
  pending snapshot, response and operation-key readback without normalization.
  Native refs and observations remain synthetic; no live PM work is implied.

Still open: real PostgreSQL migration/locking, full repository gates, deployed
cross-service auth/callback/capability compatibility, and real CLI delivery.
The final business boundary remains genuine owner confirmation followed by
Backlog/Ready for FLEETQA-3 without Analysis/Analyst. This technical retry is not
that confirmation, an instruction completion receipt or SDLC business success.
