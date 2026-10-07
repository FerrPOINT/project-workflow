# B-SDLC-03: First Source Admission Slice

Status: source implementation, not installed or deployed. This is the opt-in
counterpart on the existing owner API, not autonomous Base acceptance.
Owner-contract audit on 2026-10-03 found that source attestation cannot prove
trusted execution. Production Base work steps, replay and terminal issuance/
readback now fail closed pending actual owner binding and evidence protocols.
The receipt derivation below is component-tested code, not callable success
against the current Fleet/Tracker/Forge contracts.

## Source Reconciliation

- Owner checkout: `.local/pm-clarification/project-workflow`, branch
  `feat/pm-clarification`, existing PR90 foundation at
  `0401af1`. The initial worktree was clean.
- Fetched and verified PR91 branch `docs/base-sdlc-transfer-20261002`:
  `674aab3f016255cf948b6e6e8b0ea92a8bf92557`.
- Verified remote master: `ef66f165a5eb85895f43f67829273291f428850c`.
  This is the common ancestor. PR91 candidate files and documentation were
  reconciled into the same owner branch without merge, reset or force.
- Candidate catalog is byte-identical to the PR91 Git blob
  `5581b929c9e80bfba85684e98109944b2fb898ae`.
- Canonical private Base package remains pinned to
  `4b9b4c9297a13fb28a6ba2039af2f7cb719f2f58`,
  `agent-skills/manifest.json`. No private role or skill text is copied here.

## Callable Interface

Use the existing protected `POST /internal/runtime/assign`, `bind` and
`step`. No CLI command or executor was added. The public CLI remains
`step/history`.

`assign` accepts optional `base_admission`. Its strict schema is
`project_workflow.domain.base_admission.BaseAdmission`:

| Field | Required Meaning |
| --- | --- |
| `contract` | Exact `base-sdlc-admission/v1` |
| `config_ref`, `config_sha256` | Declared config identity; source-only until independently verified against a frozen Fleet assignment binding |
| `concrete_agent_ref` | Canonical non-nil lowercase Fleet agent UUID |
| `namespace`, `profile` | Canonical role namespace/profile |
| `catalog_sha256` | SHA256 of candidate JSON bytes normalized to LF |
| `skills_revision` | Exact canonical Base commit above |
| `skills_manifest_sha256` | SHA256 of the pinned manifest Git blob normalized to LF |
| `role_instruction_sha256` | Pinned manifest hash for this role instruction |
| `physical_skills` | Exact ordered role allowlist from the pinned manifest |

The ordinary assignment fields record declarations for task/root, revisions,
workflow, role, mode, scope, cycle/attempt, workspace refs and generations,
frozen inputs and assignment operation key. Their names are preserved, including
legacy `business_task_ref`; that field does not transfer ownership to Business.

The compatible opt-in `assignment_shape: "business-pre-decomposition"` is
available only for PM/draft, Analyst/analysis and Architect/decomposition in
business scope. It does not require a decomposition or Forge lease that the
owner has not created. Those refs and physical generations must be absent/null;
a real logical Tracker workspace may be included only as a ref/revision pair.
See [runtime assignment contract](runtime-assignment-contract.md) for exact
fields, legacy compatibility and additive source migration 0008. This marker
is declaration-only: it cannot unblock Base first work, evaluator, replay or
terminal receipts, nor upgrade Fleet's `runtime_ready:false` observation.

`bind` must supply the same `concrete_agent_ref`. Existing binding/run refs and
CAS/idempotency ledger are reused; this is not a Fleet native acceptance ACK.

`step` must additionally supply `base_config_ref` and
`base_config_sha256`, equal to the declared config in the assignment. Existing
assignment/run/mode/phase/status fencing still applies. Exact step payload
hashes include these fields; omitting them on legacy calls leaves their
existing hashes unchanged.

Accepted responses include `base_admission_receipt` with contract
`base-sdlc-source-admission-receipt/v1`, exact assignment payload hash,
assignment revision/ref, binding/run, task key, role/workflow/mode/scope,
cycle/attempt, frozen admission and canonical `receipt_sha256`.
Its durable evidence is the existing immutable assignment/bind ledger, which
proves consistency of declarations only. This is not a trusted execution ACK,
terminal workflow receipt or Task transition authorization. Production Base
step (including instruction-only) returns conflict before work/evaluation.

## Admission Boundary

Admission reads only regular Git blobs at the exact Base commit, validates
canonical repository/schema, the 14-skill inventory, hashes and physical
allowlists, and compares role/mode/scope/namespace/profile against the candidate.
The verifier used by candidate scripts is shared with the application.
Runtime access requires explicit `PROJECT_WORKFLOW_BASE_SKILLS_ROOT` pointing
to an authorized Base checkout's `agent-skills` directory.

The complete persisted catalog must match candidate v3, including phase
instructions/checks/evidence. A v2 database, missing source, drift, config
mismatch or stale assignment rejects work before Supervisor. Generic CLI/human
step cannot create or execute an unadmitted v3 cursor. Existing generic routes
and v1/v2 handling retain their behavior.

No default path, bootstrap, SDK pin, image or deployment was changed. The
later business-only compatibility slice adds source migration 0008 without
installing it in accepted runtime or adopting candidate v3.
An explicit isolated candidate installation is still required. Existing
startup/capability/exporter paths describe the accepted legacy runtime and
must not be used as Base dispatch readiness evidence.

## Durable Terminal Receipt

The component implementation for an accepted final PASS report stores `base_terminal_receipt` inside the
existing step history `supervisor_response`, in the same transaction as its
`completed` phase event and terminal cursor. No table, migration, independent
ledger, executor or CLI was added. Base instruction-only and non-terminal
responses carry `complete=false`; final acceptance carries `complete=true` only
after durable receipt construction AND trusted owner admission. Receipt failure rolls back both report and
cursor. Replay checks the persisted receipt again; readback never manufactures
a missing receipt from a done flag or history.

Minimal owner reconciliation DTO:

```json
{
  "task": "DEV-1",
  "step_operation_key": "accepted-final-report:1",
  "assignment_revision": 1,
  "assignment_ref": "assignment:1",
  "binding_ref": "binding:1",
  "hermes_run_ref": "run:1",
  "mode_key": "initial",
  "cycle_number": 0,
  "attempt_number": 1,
  "base_config_ref": "frozen-owner-config:1",
  "base_config_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}
```

Call `POST /internal/runtime/base/terminal-receipt/readback` with a fresh Base PAT
having exactly `["project-workflow:read"]` and a deployment-registered reader
subject/role. Legacy runtime/assignment/catalog shared tokens, browser sessions
and privileged-human assumptions grant no Base read authority. Optional `receipt_sha256` checks
the expected immutable result. PM execution, when enrolled, also requires its
current `session_run_id` AND existing `X-Workflow-Execution-Token`; there is no
assignment-token bypass. Catalog readers cannot read task receipts.
The component success shape is `{"ok":true,"complete":true,"receipt":{...}}`,
but production success is disabled until owner evidence exists. Unknown operation is
404, absent/stale/mismatched evidence is 409, unavailable dependencies are 503.

Receipt contract is `base-sdlc/workflow-terminal-receipt/v1`. It includes:

- Exact task/root/work-item/stage/decomposition and workspace/lease generations,
  workflow/role/mode/scope/cycle/attempt and frozen-input digest.
- Frozen assignment operation/ref/revision/payload hash, accepted bind operation
  and request hash, concrete agent, exact binding/run refs and run identity hash.
- Full frozen `base_admission`: owner-attested config ref/hash, Base pin,
  normalized manifest/role-instruction/catalog hashes, namespace/profile/allowlist.
- Accepted step operation/request hash, worker report and evaluation snapshot
  hashes, accepted-response hash, creation time and canonical `receipt_sha256`.
- Terminal cursor and hash, with `revision` equal to the exact existing completed
  phase-event ID linked to the accepted step history entry.

Config is taken from the immutable assignment declaration bound by the accepted
local bind operation, never from model output or the readback caller. Equality
and canonical hashes cannot authenticate the declared execution/config/evidence.
This is not frozen Fleet binding readback. Fleet's implemented configuration
observation verifies effective DB head and managed HOME files but always returns
`runtime_ready=false`; editable `PackageProof` metadata alone grants no rights.
Independent numeric Fleet
binding/run revisions are not present in the generic ledger: the receipt uses
assignment revision plus accepted bind operation/hash and exact run refs/hash,
not invented Fleet counters. An enrolled PM run additionally has existing
execution version/fence/session identity. EOF, instruction-only output, a report
without successful evaluator coverage, a synthetic ACK or a manually done cursor
are not completion evidence.

Audit of the actual owner contracts in Tracker
`docs/SDLC_LIFECYCLE_V1.md`, Fleet `docs/contracts/SDLC_EXECUTION_V1.md` and Forge
`docs/SDLC_DELIVERY_V1.md` found no callable non-PM frozen binding/acceptance
lookup and no Forge trusted SDLC operation receipt lookup. Forge's physical
attempt workspace marker/runner ACK is not a task/assignment/evidence receipt.
Therefore Workflow cannot authenticate report/cursor acceptance for Base yet;
it does not authorize Tracker transitions or replace Forge delivery evidence.
This concrete DTO has not passed integrated counterpart acceptance.
Receipt/derivative hashes reuse `domain.runtime_assignment.canonical_json`:
UTF-8, sorted object keys, compact JSON separators, unescaped Unicode. The
receipt's own hash excludes `receipt_sha256`; cursor/run hashes exclude their
own hash fields. Package artifact hashes normalize LF; worker-report hash uses
the exact accepted UTF-8 text, not a reworded model summary.

Frozen evaluator proof additionally requires BOTH lowercase 64-hex contract
fingerprints and their recomputation from the exact accepted Supervisor state.
Base reports persist `contract_fingerprint_state` inside the existing evaluation
snapshot: prompt version, contract, evaluation items, previous coverage, delegation,
group, transition routes and full phase graph. This uses the existing Supervisor
JSON/SHA256 algorithm without changing its bytes or legacy fingerprints. The
partial public `contract_snapshot` alone is not its hash input. Readback also
checks that snapshot against the frozen state and recomputes the existing report
replay fingerprint (task ID, contract fingerprint, normalized report). Missing
old frozen state is rejected, never reconstructed from current catalog/history.
Coverage must have nonempty, unique, nonblank string IDs in both the contract
and accepted ledger; the existing strict `ResponseParser` revalidates the raw
evaluator against those exact IDs. Raw PASS, duplicate IDs hidden by set equality
or two absent/equal invented fingerprint values are not successful proof.
These validators are independent of the current production owner-admission block.

## Explicit Source Export

`GET /internal/runtime/base/source-catalog` requires a registered catalog reader.
`GET /internal/runtime/base/source-capabilities` accepts registered role/catalog
readers; task data and receipts are not returned. Both are source-only and
do not open a request database UoW or install a catalog. Startup is unchanged.

The callable `application.base_source.export_base_source` verifies the exact
regular candidate source artifact against its PR91 Git blob, reads only pinned
private Base Git blobs, and reuses the native managed-catalog derivative for
7 roles / 11 modes / 33 phases. Returned metadata includes candidate revision,
blob and artifact hash, exact Base revision/schema/normalized manifest hash,
role-instruction and skill hashes, namespace/profile/allowlists, mode scopes,
public candidate phase sets and canonical derivative hashes. No private role or
skill text is exported. Source owner declarations name Base, Tracker, Fleet,
Workflow and Forge; legacy Business routing and v2 runtime capability claims are
not exported.

Source catalog schema is `base-sdlc/workflow-source-catalog/v1` with
`catalogVersion=3`, `sourceOnly=true`, `runtimeReady=false`. Source capability
contract is `base-sdlc/workflow-source-capability/v1`, with
`implementation_build_attested=false`. The PR91 revision identifies the candidate
artifact, not an immutable build of this implementation. Legacy
`/internal/runtime/catalog`, `/internal/runtime/capabilities` and the default v2
export remain unchanged. Missing private pin/config or drift returns 503, with
no lazy fetch or legacy fallback. This DTO is an explicit source-review surface,
not an installed runtime compatibility descriptor.

## Remaining Owner Dependencies

The actual Fleet predecessor endpoint is
`GET /internal/runtime/v1/agents/{agent_id}/configuration`: dedicated registered
subject, exactly `fleet-control:read`, concrete UUID allowlist, source observation
with `runtime_ready=false`. It does not return frozen assignment/config binding,
run/fence acceptance or native-loaded skill evidence. Workflow does not reinterpret
it as an ACK or call a guessed endpoint. Tracker must provide trusted exact
assignment/execution identity and revisions; Forge must provide trusted operation
lookup for required workspace/delivery evidence. No request field, env readiness
toggle, LLM PASS, HTTP 200 or canonical hash waives these missing dependencies.

New Base readers use `PROJECT_WORKFLOW_BASE_READER_SUBJECTS_JSON`, an operator-owned
JSON map from canonical non-nil subject UUID to canonical role or `catalog`, with
fixed `AUTH_INTERNAL_BASE_URL` / `AUTH_ISSUER`. Every request performs bounded
fresh Base `/auth/tokens/introspect` lookup; duplicate registry/response keys,
unknown subjects, excess/duplicate/wildcard scopes, redirects, oversized responses
and unavailable authority fail closed. Only issuer-supported `project-workflow:read`
is required, not a compound resource scope. Base `crates/auth-server/src/routes.rs`
issues only registered `service:read` / `service:write` grants. The separate
namespace-owner endpoint's earlier unissuable compound-scope requirement was
also corrected: standard read/write plus its existing pinned provisioner subject,
with persisted issuer/subject verification and unchanged canonical PM namespace/
Tracker mapping guards. It is not Base execution authority; PM checkpoint/run
credentials retain their existing fences. See `pm-namespace-ownership.md`.

The existing PM checkpoint/resume API is retained. Generic Base continuation
fails closed until trusted checkpoint + terminal ACK/release integration exists.
No checkpoint protocol or synthetic ACK was introduced.

## Namespace Mapping Contract

Base manifest `roles.developer.namespace = "hermes-developer"` and source exporter
`roles.developer.namespace` are SYMBOLIC NAMES, not database IDs. The corresponding
profile is `roles.developer.profile = "hermes-sdlc-developer"`; workflow is the
stable key `roles.developer.workflow = "hermes-sdlc:developer"`, not its DB ID.

The existing installed directory is `GET /internal/runtime/catalog`, protected
by the existing Fleet catalog token (unchanged legacy route). Actual namespaces
contain `id` / `namespace_id` (same positive numeric DB ID), `name` /
`namespace_name` (symbolic name), `workflow_id` (FK to the returned workflow),
`cli_command` / `namespace_cli_command`. Actual workflows contain `id` (positive
numeric DB ID), `key` (stable workflow key), `name` and `modes` with `role_key`.
Join namespace `workflow_id` to workflow `id`; match role/key/CLI command and
namespace NAME against the canonical source definition. Fleet may represent an
ID as an opaque string, but must preserve that value, never replace it with a
label. Its separate `WorkflowBinding.namespace_name` is the symbol comparison.

The legacy installed directory does NOT return `hermes_profile` and continues to
validate accepted default v2. The source-only exporter does not open a DB and
cannot allocate or report installed namespace/workflow IDs.

### Read-Only V3 Owner Observation

`GET /internal/runtime/base/namespace-bindings/{namespace_id}` requires fresh
`authorize_read`, exactly the issuer-supported `project-workflow:read` grant,
and a subject explicitly registered as `catalog`. Role readers, human subjects,
legacy catalog/runtime credentials and extra/compound scopes are rejected.
Authorization precedes opening the DB; there is no credential fallback or cache.
The ID must be canonical ASCII positive decimal in `1..9223372036854775807`;
leading zeros, signs, whitespace, labels and out-of-range values return 422.

On success the exact response is:

```json
{
  "ok": true,
  "binding": {
    "schema": "base-sdlc/workflow-binding/v1",
    "namespace_id": "123",
    "namespace_name": "hermes-developer",
    "workflow_id": "456",
    "workflow_key": "hermes-sdlc:developer",
    "role_key": "developer",
    "profile": "hermes-sdlc-developer",
    "catalog_version": 3,
    "catalog_sha256": "<lowercase SHA256 of LF-normalized canonical candidate bytes>",
    "skills_revision": "4b9b4c9297a13fb28a6ba2039af2f7cb719f2f58",
    "runtime_ready": false
  }
}
```

Example IDs are illustrative, never allocated by this endpoint. Both IDs are
actual persisted numeric identities serialized as strings, not namespace labels.
Workflow reads namespace `workflow_id` -> workflow `id`/`key` -> registered role
agent/profile. The complete installed candidate must validate (all seven roles,
11 modes, 33 phases, instructions/checks/evidence and namespace identities), with
every canonical workflow actively selecting v3. The exact candidate Git blob,
Base pin, full immutable package validation and all role namespace/profile/mode/
allowlist agreements reuse the source exporter verifier. `catalog_sha256` equals
its `workflowCatalogSourceArtifacts["project_workflow/references/base_sdlc_catalog_v1.json"]`,
not `sourceSha256`, a DB hash or caller assertion. Parsing and hashing share the
same verified source bytes. No private instruction/skill text is returned.

The version check explicitly selects `list_modes(..., catalog_version=3)`;
the canonical owner's full validator/inventory also selects active modes. It
does not prohibit retained historical v2 modes/phases, assignment pins or history.
A focused future-adoption fixture proves v3 readback with those v2 rows unchanged;
the target must include the v3 workflow descriptions as well as appended modes
and active version selection, per the canonical validator (v2 descriptions differ).
This readback does not itself install or adopt a catalog. The separate explicit
append-only source path is described in [Base Catalog Adoption](base-catalog-adoption.md).

The observation takes the existing shared catalog transaction lock, discards
cached rows and revalidates/re-reads the mapping before returning. It performs no
writes, commits or ledger creation; its UoW is rolled back and closed. Responses
use `Cache-Control: no-store`; semantic binding fields contain no timestamp.
Fleet can freeze these fields and compare a fresh authenticated readback.

Errors are JSON `{ok:false,error_code,error}` with no binding: 401/403
`machine-access-denied`, 503 `authorization-unavailable`, 409 `binding-conflict`
for missing/partial/stale/mismatched installed mapping or candidate, 503
`binding-unavailable` for source pin/config/DB dependencies. Source/DB errors are
sanitized. Absence of v3 never causes installation, default switch or v2 fallback.
FastAPI DTO-generated [OpenAPI](base-binding-openapi.json) is reproduced with
`python -m scripts.export_base_binding_openapi`; PM OpenAPI/SDK pins are untouched.

This is a namespace/catalog/profile owner observation, NOT frozen execution/config,
assignment/run authority, native Fleet readiness, build attestation or terminal
success. `require_owner_execution_evidence` remains unconditionally fail-closed.
The default v2 startup validator, bootstrap and accepted runtime are unchanged;
v3 runtime installation/adoption and startup compatibility remain a separate
integrated milestone. The new observation is verified only against disposable
pytest SQLite with explicit candidate installation and the authorized Git pin,
not an accepted runtime DB. No Fleet code or fixtures were changed.

Remaining B-SDLC-03 work: production v3 installation/image selection and source
build provenance, Fleet effective-config frozen-binding proof, Fleet/Tracker/Forge
counterpart contract tests, trusted Base checkpoint/rebind and integrated
acceptance. Existing PM enrollment checks v2 compatibility and is intentionally
not broadened to v3 in this slice. Runtime scenarios remain NOT RUN.

## Scoped Evidence

`test_namespace_binding.py` covers the fresh catalog-only auth boundary, actual
persisted FK/profile and all seven role mappings, stable readback without writes,
missing/default-v2/partial/stale/drifted candidate state, full source agreement,
canonical IDs, typed dependency failures, generated OpenAPI and an opt-in actual
private Git pin case. The opt-in case measures three complete HTTP observations
with real pinned Git export plus two full DB validations each, checks the 5s Fleet
readback budget and prints stage/aggregate timings. Its issuer HTTP is mocked and
DB is isolated SQLite, not live authority, PostgreSQL or accepted-runtime latency.
These tests never bypass the owner execution guard.

Admission/terminal component fixtures explicitly bypass the production owner
guard to test ledger derivation and corruption handling. `test_owner_evidence.py`
restores the real guard: claimed frozen config/run/scope/report, instruction-only
and previously stored internally consistent receipts cannot admit work/readback
or mutate the cursor. `test_machine_readers.py` covers registered subject/exact
issuer scope enforcement and malformed/unavailable authority. These tests do not
assert live acceptance or owner protocol implementation.

Source/API tests are in `tests/base_candidate/test_admission.py`; Fleet
metadata and evaluator replies are explicitly synthetic. They cover all seven
roles, Developer initial/rework with separate delivery/aggregate scope, config
and source drift, missing admission/source, concrete agent mismatch, stale
run/assignment/phase, replay/collision, ledger readback and generic bypass.
The restart test recreates the API app over the same persisted database; it is
not a process-crash or live recovery test.

Private-source semantics use real synthetic Git fixtures in
`test_pinned_skills.py`, including changed HEAD/worktree, wrong origin/schema/
hash/inventory/allowlist, unavailable pin and symlink rejection.
The canonical private Base pin was also checked locally with
`scripts/verify_base_sdlc_candidate.py --skills-root <authorized-checkout>/agent-skills`.
No full suite, build, container, deploy, commit or push is part of this slice.

Verification on 2026-10-03: 47 admission tests passed, including the optional
callable API test against the actual authorized private Git package; 24 candidate/
pinned-package tests passed; 22 PM guard/continuation tests and 126 existing
runtime/assignment/task-service cases passed across focused runs. Scoped ruff
and mypy passed. TestClient emitted an existing Starlette deprecation warning.

Terminal/source slice verification on 2026-10-03: 29 terminal tests (including
one opt-in real-private-Git test) and 9 source export tests (including real pin
verification) passed. The combined candidate evidence is 109 distinct cases
across focused runs; 134 existing PM/runtime/guard/capability cases passed across
focused runs. The first regression run found the generated PM OpenAPI snapshot
missing the earlier optional admission schema; the existing exporter regenerated
it, and its exact equality test passed. PM DTO/guards were not changed.

Before the batch-read follow-up below, the optional real-package terminal test
exceeded the generic 60-second timeout while reading immutable blobs; rerun
passed in 71 seconds with a local 180-second marker. That measurement is
historical, not the current reader cost.
Scoped ruff (changed code/tests), mypy (7 changed source files) and `git diff
--check` passed. Evaluator, config and Fleet run metadata in receipt tests are
synthetic, even where the canonical private package is real. These are isolated
SQLite source/API tests, not PostgreSQL crash recovery, deployed runtime,
effective-config admission or autonomous SDLC acceptance.

## Batched Pinned Reads

Source follow-up 2026-10-03: `infrastructure/base_package.py` now uses the Fleet
`backend/infra/src/base_package.rs` batch approach as a reference. There is no
cache, lazy fetch, persistent worker, scheduler or new runtime capability. Every
validation still checks the operator-supplied checkout root, canonical origin
and exact immutable commit. One `ls-tree -r -l -z` validates the complete regular
inventory; one `git cat-file --batch` reads manifest plus all 21 role/skill files.
The five Git processes replace 49 per full package verification. The helper
disables replacement refs/fsmonitor hooks, prompts, lazy fetch and all Git
transport protocols; it never resolves HEAD or consumes worktree/donor files.

Limits: 256 KiB per nonempty blob, 64 KiB inventory, exactly 22 package entries,
bounded batch input/output and a five-second deadline per Git process. Stdout is
bounded while the child runs, rather than only checked after an unbounded
capture. Timeout/overflow kills and reaps the child and closes its short-lived
I/O reader. Frames must exactly match object ID/type/size, body length and LF
separator, without extra/trailing data; each raw body must match its Git object
hash and decode as UTF-8. Normalized SHA256, all role/skill allowlists, skill
headers and the entire strict manifest schema/provenance are then verified.
Unknown/duplicate manifest keys, runtime donor dependency, altered authority,
nonregular entries, wrong hashes, missing/oversized blobs and malformed batch
data fail closed. Errors do not expose private file contents.

Actual authorized canonical Base pin measurements on this host:

| Source Operation | Before | Batched Reader |
| --- | --- | --- |
| Full package verification | 3.239 s / 49 Git processes | 0.267, 0.293, 0.328 s / 5 processes each |
| Actual-pin terminal receipt/readback test | 71.36 s | 8.29 s focused; 14.71 s in the larger scoped regression run |
| Actual-pin callable admission test | not separately timed | 1.93 s focused |

The real terminal test now has a 30-second timeout instead of the temporary
180-second allowance. These local source/API observations are below the stated
30-second lease TTL; they do not prove live lease liveness or timing on another
host. Receipt/catalog shapes, normalized source hashes, default v2, bootstrap
and SDK pins remain unchanged. The real-package source export test compares the
returned manifest exactly to the pinned raw JSON metadata. Private instructions
and skill text remain unexported.

Verification: 75 batch/pinned-source cases passed across focused runs, plus 147
admission/terminal/source/catalog and existing PM/machine-scope/capability cases.
Negative cases include malformed batch/frame/order/body/trailer, invalid UTF-8,
input/output/time limits with child cleanup, nonregular/sized inventory,
duplicate paths/keys, schema/provenance/allowlist failures, real synthetic Git
oversize and replacement refs. Scoped ruff and mypy (5 source/consumer files)
passed. No full suite, build, DB install, deploy, commit or push was performed.

## Owner Audit Verification

2026-10-03 follow-up: 324 scoped admission/source/package/namespace/PM guard/
capability cases verified across the combined run and corrected 66-case namespace
rerun. The combined run's sole failure was an obsolete expectation allowing
readback after issuer substitution; corrected coverage requires 403 and proves
the original immutable mapping remains readable after restoring registration.
79 terminal/frozen-proof/owner-block cases passed (39 new frozen-proof cases),
including the actual private Git pin component test. 84 shared Supervisor
contract/reliability/parser and actual directory mapping tests passed. In total,
447 distinct scoped cases were verified across focused runs; no full suite was run.
Scoped ruff and mypy on all 20 task-owned source/script files passed, as did diff
whitespace review. The existing Starlette TestClient deprecation warning remains.

Production external owner evidence is still unavailable: Base work and receipt
success are blocked, Fleet native `runtime_ready=false`, and successful receipt
derivation tests explicitly bypass only that external-dependency guard. New
frozen-proof negatives independently fail with that outer guard bypassed.
No other repository, runtime DB, default catalog, bootstrap, SDK pin, container,
build or deployment was changed. The owner authorized a source commit of the
verified task-owned slice; push remains gated on the integrated milestone.

## File Inventory

| Area | Files |
| --- | --- |
| Admission/auth | `application/base_admission.py`, `domain/base_admission.py`, `infrastructure/base_package.py`, `infrastructure/base_auth.py`, `infrastructure/namespace_auth.py` under `project_workflow/` |
| Terminal/source slice | `application/base_terminal.py`, `application/base_source.py`, `interfaces/ui/routes/base_api.py`, `interfaces/ui/app.py`, `supervisor/evaluate.py` under `project_workflow/` |
| Existing runtime | `application/task.py`, `domain/runtime_assignment.py`, `interfaces/ui/routes/runtime_api.py`, `interfaces/ui/schemas.py`, `supervisor/core.py`, `config.py` under `project_workflow/` |
| Issuer-compatible namespace owner | `application/namespace_ownership.py`, `interfaces/ui/routes/namespace_ownership_api.py` under `project_workflow/`, `tests/test_namespace_ownership.py`, `docs/pm-namespace-ownership.md` |
| PR91 candidate | `project_workflow/references/base_sdlc_catalog_v1.json`, `scripts/build_base_sdlc_candidate.py`, `scripts/verify_base_sdlc_candidate.py` |
| Tests | `tests/base_candidate/test_admission.py`, `test_candidate.py`, `test_pinned_skills.py`, `test_terminal.py`, `test_source.py`, `test_batch.py`, `test_machine_readers.py`, `test_owner_evidence.py`, `test_namespace_issuer.py`, `test_frozen_evaluation.py` |
| Documentation | `docs/base-sdlc-admission.md`, `docs/base-sdlc-candidate.md`, `docs/pm-continuation-openapi.json`, `docs/architecture.md`, `AGENTS.md` |
