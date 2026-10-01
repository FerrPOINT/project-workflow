# PM Continuation Machine Contract v1

Status: Workflow backend implemented; local gate results are in
[verification](pm-continuation-verification.md). Fleet's trusted runtime readback
endpoint and continuation orchestration are not yet implemented. There is no
live resume acceptance claim.
OpenAPI: `/openapi.json`, schemas `PMIdentity`, `PMBind`, `PMCheckpoint`,
`PMResume`, `PMRebind`, `PMReadback`. Runtime callback schema is
`RuntimeObservation` (also included in Workflow OpenAPI).
The checked-in [generated OpenAPI](pm-continuation-openapi.json) contains these
PM paths and the ordinary assignment/bind paths. Regenerate it with
`python -m scripts.export_pm_openapi`; a contract test checks it against the
application's generated schema.

## Concrete agent boundary

The catalog/phase agent name and assignment `role_key` remain `project_manager`.
They select a role, not a Fleet agent. The server-owned assignment adapter sends
`concrete_agent_ref` to ordinary `/internal/runtime/bind`: a strict canonical
non-nil lowercase Fleet agent UUID, for example `aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa`.
Workflow persists it separately on `task_runtime_assignments` in the same CAS
and bind digest as the real binding/run refs. Only the role-scoped assignment
credential may write this mapping. PM commands and callback data cannot create
or replace it. Runtime bind responses expose the saved `concrete_agent_ref`.

`PMIdentity.agent_ref` is required to be that exact UUID on every command and
callback. Workflow compares it with the persisted mapping and verifies the
mapping against the original bind digest, before consulting Fleet. It never
compares a UUID with the phase agent name or trusts a caller-only agent claim.
The callback still has exactly the same 18 fields; no mapping field is added.
Missing mapping, altered provenance, stale assignment or another agent UUID
fails closed, including command replay, readback and Supervisor access.
Resume preserves this UUID while allocating a new session-run UUID and run refs.

Ordinary PM bind also requires the concrete UUID. Non-PM binds may omit it or
send null; their existing bind digest/replay and step/history remain compatible.
Published historical rows are migrated with null mapping, with no guessed
identity. An authorized `legacy_bound` adoption can set it once alongside bind
metadata; a finalized binding cannot later be enriched or rebound. Existing PM
records without mapping need an explicit owner-controlled rollout decision.
The single pending `0005_pm_execution` migration adds the nullable column and
constraint; no additional pending migration is introduced.

## Fleet runtime callback (implement this first)

Configure Workflow `PROJECT_WORKFLOW_PM_READBACK_URL` as a fixed collection
URL, for example `http://fleet:8080/internal/runtime/v1/pm/runs`.
Workflow calls `GET <collection>/<session_run_id>` with
`Authorization: Bearer <PROJECT_WORKFLOW_PM_READBACK_TOKEN>`.
The UUID is encoded as one path segment; credentials are never URL parameters.
No request can override this URL. Redirects are refused. Timeout: connect 3s,
read 10s. HTTP other than 200, timeout, malformed or unavailable probe means
unknown acceptance (Workflow 503); it never proves termination.

Fleet authenticates this service credential, loads exactly that persisted
session-run UUID, verifies its session/assignment/execution/agent binding, maps
it to the actual runtime endpoint plus runtime-local Hermes run ID, and probes
Hermes over HTTP. Return the JSON below only after this probe. Do not return
cached Fleet run state, EOF, a submitted human status, or an unscoped lookup of
a raw Hermes ID as terminal proof. Do not mark `stopped` until the actual
runtime confirms safe stop. If the runtime cannot prove status, return 503.

`session_run_id` is a canonical lowercase UUID string allocated by Fleet.
It is globally unique across agents and runtimes. `hermes_run_ref` is the
runtime-local string used by the existing Workflow assignment/step API;
it is NOT globally unique. Raw Hermes IDs may collide across runtimes.
Workflow stores each run by Fleet UUID and verifies both values plus full
identity. The callback must refuse mismatched runtime mapping, never fall back
to another agent's run.

Example exact `RuntimeObservation` JSON (no envelope or extra fields):

```json
{
  "task": "PM-1",
  "execution_ref": "execution:one",
  "tracker_instance_ref": "tracker:one",
  "tracker_project_ref": "project:one",
  "task_ref": "business-task:PM-1@1",
  "root_ref": "business-task:PM-1@1",
  "agent_ref": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "assignment_operation_key": "assign:one",
  "assignment_ref": "assignment:one",
  "assignment_revision": 1,
  "observation_ref": "runtime-probe:one",
  "session_run_id": "11111111-1111-4111-8111-111111111111",
  "binding_ref": "binding:one",
  "hermes_run_ref": "runtime-local-run-id",
  "status": "running",
  "dispatch_operation_key": "pm-bind:one",
  "checkpoint_ref": null,
  "fence": 1
}
```

`agent_ref` and `session_run_id` are canonical lowercase UUID strings.
Nil `agent_ref` (`00000000-0000-0000-0000-000000000000`) and nil
`concrete_agent_ref` are rejected, matching Fleet's concrete-agent validator.
Other refs are nonblank strings, at most 512 characters; `task`, operation keys
are at most 128. Integers are strict positive signed-64-bit values. Extra
fields/coerced integers are rejected. Status is exactly one of `running`,
`completed`, `failed`, `cancelled`, `stopped`. `observation_ref` identifies the
actual probe. Terminal statuses must be immutable for a session-run UUID.
`dispatch_operation_key` is the initial PM bind key, or the reserved resume
key for a continuation. Initial `checkpoint_ref=null`, `fence=1`; resumed run
uses the exact reserved checkpoint and next fence. These fields must come from
Fleet's persisted dispatch binding, not be echoed from callback query input.

## Workflow endpoints and authorization

All five endpoints are POST JSON below `/internal/runtime/v1/pm`:

| Route | Credential | Additional payload beyond identity |
| --- | --- | --- |
| `/bind` | PM assignment adapter | operation_key, expected_version=0, session_run_id, binding_ref, hermes_run_ref |
| `/checkpoint` | PM runtime + execution token | command cursor, checkpoint_ref, clarification_request_ref, clarification_version, requirements_revision |
| `/resume` | PM assignment adapter | checkpoint payload + answer_event_ref, new_session_run_id |
| `/rebind` | PM assignment adapter | command cursor, checkpoint_ref, resume_operation_key, new_session_run_id, new_binding_ref, new_hermes_run_ref |
| `/readback` | PM adapter, or PM runtime + current execution token | optional operation_key |

Identity is the first ten fields in the callback example through
`assignment_revision`. It is immutable and required on every command/read.
Command cursor: `operation_key`, `expected_version`, `expected_fence`,
`session_run_id`, `binding_ref`, `hermes_run_ref` (current old run for rebind).
The execution token is the response `execution_token`, passed in
`X-Workflow-Execution-Token`, together with the existing runtime bearer token.
It is HMAC-bound to full identity, Fleet UUID, binding, raw run ref and fence.
`PROJECT_WORKFLOW_PM_SCOPE_SECRET` is Workflow-only, minimum 32 characters;
never share it or assignment credentials with the agent runtime.
The scope signing secret must differ from runtime/adapter/catalog/callback tokens.

Canonical Workflow role is `project_manager`, namespace command
`workflow-project_manager`, workflow key `hermes-sdlc:project_manager`.
Hermes profile/namespace use hyphenated names such as `hermes-project-manager`.
`project-manager` is not an alias for the Workflow PM API role; Fleet must map
its display/runtime role to the canonical role at the adapter boundary.

## Minimal handshake

1. Persist Fleet session, task/root/concrete-agent binding and execution ref.
   Accept the ordinary `/internal/runtime/assign` assignment, then persist a
   Fleet session-run UUID and PM bind operation key before initial dispatch.
2. Dispatch initial run using that stable key; persist real runtime mapping.
   Finalize ordinary `/internal/runtime/bind` with actual binding/raw run refs
   and `concrete_agent_ref` from Fleet's persisted concrete-agent binding.
   PM `/bind` verifies the callback (`running`, initial key, fence=1). Success
   returns version=1, fence=1 and execution token.
3. Runtime calls `/checkpoint` with current cursor and structured Tracker
   request/revision refs. This records the existing Supervisor phase without
   advancing it: state=waiting, version=2, fence=1. Further steps are fenced.
   Waiting does not prove that the runtime has exited.
4. After Tracker durably saves answers, Fleet persists the new session-run UUID,
   then calls `/resume` with `new_session_run_id` and the exact
   checkpoint, request/revisions, answer event and expected_version=2. Workflow
   probes the OLD Fleet UUID and accepts only immutable terminal status.
   Success reserves state=resume_pending, version=3, fence=2, preserving execution
   and freezing `resume_session_run_id` to that new UUID.
   `resume_operation_key` is the only permitted new dispatch key. No new run
   has been dispatched by Workflow; `resume_delivered=false`.
5. Fleet persists the reserved key/checkpoint/fence onto that same UUID,
   dispatches once with runtime idempotency, then calls `/rebind` with
   expected_version=3, expected_fence=2, old cursor and new UUID/raw mapping.
   Workflow verifies the NEW callback as running with the reserved key,
   checkpoint and fence. Success: same execution, state=active, version=4,
   new token, `resume_delivered=true`. Use that token and `session_run_id` with
   the existing `/internal/runtime/step`; existing Supervisor/history own work.
   Enrolled PM `/internal/runtime/history` also requires the current execution
   token and `session_run_id` query parameter. Ordinary unbound tasks keep their
   existing role-scoped API.
   Committed PM step responses additionally carry `execution_ref`, `session_run_id`,
   `execution_version`, `execution_fence` alongside the ordinary assignment cursor.
   Their history rows expose these same persisted fields and run/assignment refs.

Successful responses: `{"ok":true,"result":{...},"execution_token":"..."}`.
Token is returned only to the adapter for an active binding. Result contains
`contract_version`, identity, state, version, fence, session_run_id,
binding_ref, hermes_run_ref, checkpoint, resume_operation_key, resume_session_run_id,
terminal_readback, workflow_step_allowed, resume_delivered.
Readback additionally contains `operation=null` or
`{operation_key,kind,request_sha256,result}` with the original durable result.
Readback returns persisted Workflow facts, not a fresh runtime health claim.

Same command key/canonical payload replays its durable result, even after later
commands; changed payload/kind conflicts. Replay results are historical; use
readback for the current cursor. Unknown response requires readback/retry of
the SAME command/key and SAME Fleet UUID. Missing operation is not permission
to dispatch a different run. Fleet must read back unknown runtime dispatch
acceptance by its stable dispatch key before retrying; Workflow has no scheduler
and cannot supply runtime dispatch idempotency for Fleet.

Errors: 401 unauthorized, 403 wrong machine/scope credential, 404 missing scoped
task/execution, 409 stale identity/version/fence or payload/proof mismatch,
422 malformed payload, 503 unavailable capability/dependency or unknown runtime
acceptance. `ok=false,error_code,error` never indicates successful delivery.
Capability metadata advertises PM continuation only when schema/catalog/build
are ready and trusted callback plus scope signing are configured. Configuration
does not assert that Fleet/Hermes is healthy or deployed compatibly.

Tracker owns authorization, answer completeness and revision semantics.
Workflow validates exact stored request/revision refs, not human answer text.
Live multi-service acceptance and Fleet's actual Hermes probe remain required.
This repository implements the callback consumer, not Fleet's callback server.
