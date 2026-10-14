# Single-Task Terminal Receipt

Actual Workflow completion produces an immutable `ArtifactReceipt` for
single-task-v1 roles, including PM and analyst/architect business scopes. This is not a
Fleet actual-run terminal observation, Tracker lifecycle transition or new proof
owner. Parent Tracker/Fleet policy remains responsible for those checks.

No new service, queue, table, migration, CLI command, secret setting or instruction
change in the receipt packet. Legacy/Base receipt content and history remain
unchanged. Current profile source hashes and later instruction-only corrections
are recorded in the [instruction audit](single-task-instruction-audit.md).

## Publication And Readback

The existing final Supervisor report transaction records PASS/coverage, completion
event and done cursor, builds the receipt, persists it in `supervisor_response`,
then commits. Any build/seal failure rolls everything back. Profile `complete=true`
is returned only after the receipt is durably accepted. PM additionally retains
its current execution/run and typed confirmation ledger pins inside `binding.pm`;
see [PM sealing](single-task-pm-terminal-receipt.md). Owner confirmation and native
terminal remain separate authorities.

Final step API `result` and the existing CLI JSON result add:

```json
{
  "complete": true,
  "workflow_receipt": {"reference": "<actual owner reference>", "sha256": "<actual sha256>"},
  "single_task_terminal_receipt": {"schema": "single-task-sdlc/workflow-terminal-receipt/v1"}
}
```

The body shown above is abbreviated. The actual body contains exact structured
binding/context, task=root, assignment/execution/agent, lease/version/fencing token,
profile/manifest, mode/cycle/attempt/session/run, assignment hash, completion cursor,
history/event IDs, operation/request/report/evaluation hashes, allowlisted accepted
result and full accepted-response hash. Reference format is
`workflow-terminal:single-task-v1:{namespace_id}:{history_id}`; it is opaque within
the configured Workflow owner, not a URL supplied by a caller.

SHA-256 covers UTF-8 of existing `canonical_json(body)` (sorted keys, compact
separators, no extra newline), not an envelope containing its own hash. Response
hash excludes the two receipt fields and canonically sets complete=true both when
building and reading. Raw reports, free-form evaluator messages, prompts/provider
inputs, credentials and execution tokens are not copied into the receipt. The
result is an explicit structured allowlist. Private persisted values are hashed
as the exact stored bytes/JSON; no redacted/unredacted hash comparison or mutable
environment-based redaction is introduced. Existing report handling is unchanged.

`POST /internal/runtime/terminal-receipt/readback` accepts strict
`SingleTaskTerminalReadback`:

```text
task: string
step_operation_key?: string
receipt_reference?: string
current_run?: boolean (default false)
instruction_profile: "single-task-v1"
instruction_manifest_sha256: lowercase SHA-256
session_run_id: canonical non-nil UUID
single_task_context_sha256: lowercase SHA-256
receipt_sha256?: lowercase SHA-256
```

Exactly one selector is required: `step_operation_key`, `receipt_reference`, or
explicit `current_run=true`. Existing operation-key callers and responses are unchanged;
an explicit null for the unused selector is also accepted. Reference lookup
requires non-null `receipt_sha256`. Missing/both selectors or a missing reference
hash produce framework validation HTTP 422. Generated OpenAPI expresses all three
branches in `SingleTaskTerminalReadback.oneOf`.

Direct CLI reports need not appear in Fleet's private tool journal. When their
operation key/reference is not yet known, Fleet uses `current_run=true` with the
same task/run/profile/context/token. After authorization the existing service
finds at most two actual final PASS rows for the current assignment and native
binding. One sealed row is read back; no row/not done returns 404, ambiguity or
unsealed/stale evidence returns 409. It never searches model text, manufactures
a report key, creates a receipt during lookup or bypasses the current-run scope.

Fleet can submit the actual `workflow_receipt` reference/hash without retaining
the original final step operation key:

```json
{
  "task": "SDLC-7",
  "receipt_reference": "workflow-terminal:single-task-v1:7:42",
  "receipt_sha256": "<actual workflow_receipt.sha256>",
  "instruction_profile": "single-task-v1",
  "instruction_manifest_sha256": "<actual installed manifest sha256>",
  "session_run_id": "<actual session run UUID>",
  "single_task_context_sha256": "<actual saved binding hash>"
}
```

IDs above illustrate the owner-reference format, not real deployment evidence.
Resolution happens after the same current task/run authorization: parse only the
canonical Workflow reference, require the authorized namespace/task/role, find
the existing history row, then use the same complete/stale/manifest/seal/hash
validation as operation-key lookup. Unknown, foreign or noncanonical references
return 404 without receipt contents; incomplete/unsealed/drifted records or a
wrong hash return 409. No URL fetching, new storage, credentials, migration,
catalog hash change or retroactive sealing is introduced.

Headers: existing runtime role credential in `Authorization`, and
`X-Workflow-Execution-Token`. Fleet uses the existing actual run role credential
and retained scoped context, not an agent-supplied owner URL/lease/observation.
Assignment/catalog credentials cannot use this endpoint. PM requires its existing
current PM scoped token and the exact typed confirmation completion seal.
Response: `{ok:true, complete:true, workflow_receipt:{reference,sha256}, receipt:body}`.
All handler responses have `Cache-Control: no-store`; malformed DTOs retain the
existing framework validation response contract.

Missing credential is 401; wrong credential kind/role or scoped token is 403;
missing owned task/step is 404; incomplete/stale/mismatched/unsealed evidence or
installed drift is 409; unavailable dependencies are 503. Readback only validates
the stored receipt. Older terminal records without it are not retroactively sealed,
and cannot provide a new terminal proof through step replay either. Their history
remains intact. Ordinary legacy and Base execution/replay behavior is unchanged.

## Existing CLI Handoff

The producer is the already-supported command, with the original issued context:

```text
project-workflow --json step --task <workflow-key> --report <exact-report-text> --operation-key <original-key> --runtime-request <private-request.json> --execution-token-file <private-token-file>
```

The agent uses `result.workflow_receipt` from HTTP, or root `workflow_receipt` from
CLI JSON, as `SubmitDeliveryProposal.workflow_receipt`. The producer does not invent
IDs/hashes, turn a narrative report into a receipt, or call Scheduler completion.
On unknown acceptance, explicitly replay the exact original report/key/body through
the same CLI; it reads the stored accepted response without another model call.
`history` gains no new CLI flags or command. The protected terminal endpoint reads
the existing history; it does not create an additional ledger.

Publish/readback remain the actual Tracker commands already used by instructions:
`task-tracker sdlc result propose --task <UUID> --from-file <proposal.json>` and
`task-tracker sdlc result operation --task <UUID> --key <original-key>`.
After actual run terminal Fleet reads Workflow's endpoint, compares exact receipt
body/reference/hash and run/fence/result against the proposal, then performs its
authorized Tracker completion. Workflow receipt alone does not establish actual
Fleet terminal, lease freshness, deployment acceptance or stage completion.

This readback does not publish analysis/design/review/test/change/check/deployment
artifact contents. A terminal receipt or its report hash is not a substitute for
the distinct role-artifact receipts and their authorized resolvers.

## QA Selectors

SQLite packet: `tests/test_single_task_terminal.py`; run without `-m integration`.
It covers atomic rollback, exact replay/restart, canonical hash, CLI handoff,
incomplete/stale/tampered evidence, no retroactive sealing and sensitive-data exclusion.

Read-only collection verified the existing PG file has 77 integration cases:

```powershell
& C:/git/azhukov/sdlc/project-workflow/.venv/Scripts/python.exe -m pytest --collect-only -q -m integration tests/test_postgres_integration.py
```

For bounded parent PG QA use prefix
`tests/test_postgres_integration.py::TestPostgresInitialMigration::` and exact nodes:

- `test_fresh_upgrade_matches_orm_metadata`
- `test_head_preserves_nullable_legacy_assignment_shape`
- `test_upgrade_bound_assignment_preserves_rows_and_accepts_native_wide_revision`
- `test_concurrent_runtime_assignment_reconciles_one_ledger_record`
- `test_concurrent_runtime_bind_reconciles_one_real_binding`
- `test_concurrent_runtime_steps_reconcile_global_operation_key`

Together these collect 7 cases, not zero; the wide-revision test has two parameters.
Use full node IDs with `-m integration --timeout=120`, and collect first. They are
existing schema/legacy/concurrency regression, not profile-specific terminal PG E2E.
The SQLite migration test is
`tests/test_single_task_migration.py::test_actual_0014_upgrade_preserves_legacy_predicates_rows_and_history`;
selecting it with `-m integration` deselects it.

Before pytest starts, parent supplies approved disposable QA `PGHOST`, `PGPORT`,
`PGUSER`, nonempty `PGPASSWORD`, `PGDATABASE` (admin DB), `PGCONNECT_TIMEOUT`.
The PG fixture creates/drops `project_workflow_test_<pid>` and sets `DATABASE_URL`
and `DB_SCHEMA=project_workflow` itself. Do not target runtime DB or create another
persistent Docker group. This packet runs no PG/Docker/live deployment; activation
remains false pending actual parent Tracker/Fleet policy acceptance.
