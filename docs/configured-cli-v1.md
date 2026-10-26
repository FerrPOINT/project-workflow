# Configured CLI V1

Source implementation for NEW PM tasks, not installation or live acceptance.
Legacy assignments, native PMExecution/run/checkpoint receipts and request bytes
are unchanged. Machine credentials never gain access to human routes.

## Agent Configuration

Required permanent environment: `FLEET_CLI_PROTOCOL=configured-cli-v1`,
`PROJECT_WORKFLOW_URL`, dedicated Auth PAT `PROJECT_WORKFLOW_API_TOKEN`,
`FLEET_AGENT_ID`, numeric `PROJECT_WORKFLOW_NAMESPACE_ID`. Owning deployment
supplies secret references; messages do not rotate credentials or write files.
Missing/unknown configuration fails before HTTP/DB. No global PDLC token,
localhost default or local DB fallback is used. Only step/history remain.
Existing Base pdlc-cli-core validates the service origin using the permanent
PDLC_CLI_TRUSTED_HTTP_ORIGINS supplied by Fleet from admin-configured URLs;
there is no per-message or per-call origin setup. A missing shared transport
fails closed. Its explicit PAT argument is always the dedicated Workflow PAT.
The initial message carries the Tracker UUID. Read its authorized context to
obtain workflow_task_key, then use that SDLC-N key for step/history.

FLEET_AGENT_ID is a client response-consistency check, not server authority.
Fresh Central Auth must prove service_account and project-workflow:read for
reads or project-workflow:write for reports. The subject must match enrollment.
Current Tracker context independently checks the task/root, owner and exact
assignment/execution/version/concrete agent/machine subject. No Fleet/native
callback or rebind is required.
Its workflow_task_key must also exactly equal the enrolled SDLC-N key; missing
or different keys refuse both enrollment and current agent access.

## Enrollment

`POST /internal/runtime/assign` uses the existing PM assignment-service token,
not an agent PAT. Closed body:

```json
{
  "interaction_protocol": "configured-cli-v1",
  "task": "SDLC-901",
  "namespace_id": 2,
  "workflow_key": "single-task-v1:project_manager",
  "mode_key": "draft",
  "role_key": "project_manager",
  "operation_key": "configured-pm-enroll:original-task-uuid",
  "assignment_ref": "10000000-0000-4000-8000-000000000001",
  "tracker_execution_id": "10000000-0000-4000-8000-000000000002",
  "assignment_version": 1,
  "business_task_ref": "10000000-0000-4000-8000-000000000005",
  "machine_subject": "10000000-0000-4000-8000-000000000003",
  "concrete_agent_ref": "10000000-0000-4000-8000-000000000004",
  "tracker_task_id": "10000000-0000-4000-8000-000000000005",
  "owner_subject": "10000000-0000-4000-8000-000000000006",
  "expected_version": 0
}
```

IDs/namespace above are illustrative, never defaults. role_key may be omitted;
its default is project_manager. task retains the actual server-issued SDLC-N
key. assignment_ref is Tracker assignment_id.
business_task_ref is the canonical Tracker task UUID, equal to tracker_task_id.
The namespace is the installed numeric Workflow PM namespace, not a task UUID.
Workflow validates the installed single-task PM namespace and current Tracker assignment. Existing tasks cannot
be converted or re-enrolled under another key. Exact original-key replay returns
the original Workflow-issued execution_ref, with no new task/native binding.

Response: `{ok:true,exit_code:0,result:{...}}`. Cursor fields:
interaction_protocol, execution_ref, task, namespace_id, concrete_agent_ref,
assignment_ref, business_task_ref, version, phase_code, status, workflow_id,
mode_id. Initial version1 and PM-DRAFT-01/active. There is no native run ID.

## Step And History

`project-workflow --json step --task SDLC-901` sends existing
`POST /internal/runtime/step` with interaction_protocol, task, namespace_id.
Reads do not increment the version. Actual phase reports use:

```sh
project-workflow --json step --task SDLC-901 --operation-key report-a01 --expected-version 1 --report -
```

Report text comes from bounded stdin, not a temporary file. The body adds
report, operation_key, expected_version. Legacy runtime-request/execution-token
file flags are refused in this protocol. The server supplies the full assignment
fence internally. Exact key/version/report replay returns its saved result;
changed payload conflicts. A committed report is not necessarily a completed
phase: inspect verdict, status, missing/blockers and complete.

After uncertain HTTP acceptance, retain the exact key/version/report and read
the original operation; never allocate a replacement key or automatically
redispatch. Safe JSON preserves HTTP status without raw HTTP bodies/secrets.

`project-workflow --json history --task SDLC-901` calls existing
`GET /internal/runtime/history` with interaction_protocol/namespace_id/task,
bounded to 200 records. Optional --operation-key and --execution-ref select an
exact saved operation. No DB fallback or human API is used.

## Confirmation And Receipt

Server settings PROJECT_WORKFLOW_CONFIGURED_TRACKER_URL and
PROJECT_WORKFLOW_CONFIGURED_TRACKER_READ_TOKEN must have actual read admission
to existing Tracker context/requirements/confirmation APIs. This source does not
issue credentials or register/broaden permissions. Authority URLs are fixed in
server configuration; reads are bounded, without redirects or environment proxy.

The final PM report requires the latest requirements revision/hash and its real
saved owner confirmation. Workflow rechecks the same confirmation and current
assignment before commit after evaluator IO. Prose, silence, a clarification
answer or an older confirmed revision never substitutes for owner consent.
The final write MUST explicitly include requirements_revision and
requirements_sha256. These must match the real latest confirmed document both
before evaluation and before commit. Other phases reject those evidence fields.
The CLI supplies them without creating another command:

```sh
project-workflow --json step --task SDLC-901 --operation-key final-a01 --expected-version 3 --requirements-revision 7 --requirements-sha256 <actual-content-hash> --report -
```

Version3/revision7 are examples, not a bypass or a required fixed cursor.

Terminal result contains terminal_receipt and workflow_receipt reference/SHA256.
Receipt fields: interaction_protocol, execution_ref, task, tracker_task_id,
namespace_id, concrete_agent_ref, assignment_ref, operation_key, request_sha256,
result_version, requirements_revision, requirements_sha256, owner_subject,
confirmation_id, history_id, status, assignment_version, tracker_execution_id,
machine_subject. The last three fields come ONLY from the saved enrollment
request, not step/readback caller claims. assignment_version is a strict positive
integer; both identity fields are canonical non-nil UUIDs. They are included in
the canonical receipt hash and checked against enrollment on readback, including
when a corrupt receipt has a recomputed hash. The readback request body below
is unchanged and does not accept these fields as caller-supplied authority.
No native proof is claimed. Workflow does
not move Tracker or dispatch Analyst. Tracker owns the Backlog/Ready transition.

Tracker verifies the actual retained result server-to-server at the EXISTING
terminal-receipt endpoint. Authorization is the existing trusted PM assignment
service Bearer, not an agent PAT or browser credential. Closed request:

```json
{
  "interaction_protocol": "configured-cli-v1",
  "task": "SDLC-901",
  "namespace_id": 2,
  "execution_ref": "10000000-0000-4000-8000-000000000007",
  "operation_key": "final-a01",
  "concrete_agent_ref": "10000000-0000-4000-8000-000000000004",
  "assignment_ref": "10000000-0000-4000-8000-000000000001",
  "requirements_revision": 7,
  "requirements_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "result_version": 4
}
```

`POST /internal/runtime/terminal-receipt/readback` returns
`{ok:true,complete:true,workflow_receipt:{reference,sha256},receipt:{...}}`.
The receipt is the exact retained terminal history result. The server checks
the selected execution/operation/agent/assignment/revision/hash/version tuple,
history/enrollment metadata, frozen confirmation and canonical receipt hash.
Unknown operation is 404; nonterminal or mismatched tuple is 409; wrong service
credential is 403. Error responses carry no private authority payload. No
receipt is synthesized from current task status. This is historical evidence,
not a fresh grant: completed receipt lookup does not require a live native run,
nor does it move Tracker. Legacy terminal lookup remains its own strict branch.

The existing history endpoint also permits exact trusted operation inspection:

```text
GET /internal/runtime/history?interaction_protocol=configured-cli-v1&namespace_id=<actual>&task=<SDLC-N>&execution_ref=<actual>&operation_key=<original>
```

The trusted PM assignment-service token can read only an exact
execution+operation in this branch; agent PATs read their own current assignment.
`result.records[].result` is the stored operation result, never a reconstructed
success or new execution grant.

## Storage And Gates

No migration/table or applied-catalog rewrite. Existing append-only
task_runtime_assignments.payload stores protocol, generated execution_ref and
trusted enrollment request; native columns remain NULL, never synthetic.
task_step_history.evaluation_snapshot.configured_cli stores key/request hash,
assignment hash, frozen confirmation and result version. Existing replay
fingerprint stores protocol/assignment/key hash. Business transition and receipt
commit together; version is rechecked after provider IO. Concurrent provider
evaluation may occur, but only matching version can commit.

Configured instructions are a runtime projection; legacy catalog bytes and
execution contracts are retained. Host tests use disposable SQLite ledgers,
controlled Auth/Tracker responses and a controlled evaluator, including actual
request interleaving while the provider releases the transaction. They do NOT
qualify PostgreSQL locking, populated-copy preservation, packaged CLI,
integrated Fleet/Tracker, real credentials, deployment or live new-chat behavior.

Initial scoped host check (f275bdf): 72 PASS across test_configured_cli.py,
test_configured_cli_transport.py, test_configured_cli_tracker.py and
test_pm_assignment_guard.py. Ruff over the repository and mypy over all
163 product/script source files pass. Python used: 3.13.13, with the already
prepared host dependencies; no Compose or live requests were executed.
The authoritative enrollment-metadata receipt follow-up passed all 24 cases
in test_configured_cli.py, scoped Ruff on its three changed Python files and
scoped mypy on its two changed source modules. Full Ruff/mypy were not repeated
for this bounded receipt-only follow-up.

The wider 341-case host selection was not green: 337 passed, one skipped and
three failed. Its extra legacy replay read was fixed and the whole affected
assignment-guard module subsequently passed in the 72-case check. The other two
failures are the current/retained19 exact-wire fixtures in
test_single_task_pm_terminal.py, which expect SDLC-7 while their unchanged
prepare helper supplies RUN-7. Both failures reproduce on unmodified PR148
head60c4dd6. Old fixtures were not regenerated or waived. Full repository,
coverage, PostgreSQL and deployed-cohort gates remain open.

```sh
python -B -m pytest -q tests/test_configured_cli.py tests/test_configured_cli_transport.py tests/test_configured_cli_tracker.py tests/test_pm_assignment_guard.py --timeout=60
python -B -m ruff check .
python -B -m mypy project_workflow scripts
```
