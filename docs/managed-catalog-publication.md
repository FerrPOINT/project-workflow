# Managed Instruction Publication

This is a separate, next-release source package based on master `620f45cd`.
The accepted PM catalog works without it. It does not change the installed
cohort, Fleet assignments/configuration, Hermes, credentials or agent messages.

## Current Source Gate

On source23797fbf (production tree156956017cceb3afe3d37f2f53195d12cdf9619d,
tests tree3b99c068045ae3380876b5957fb77bfa30101fd5), the complete non-PG
warnings-as-errors/coverage gate passes: **3186 passed, 73 subtests passed,
4 skipped, 132 deselected; coverage94.04%**, required94%, 1474.45 seconds.
Skips are three explicit private Base-source opt-ins and the NTFS executable-mode
test; they are not passes. Integration exclusions remain a different boundary.

The mandatory project PostgreSQL target also passes **74 tests**, 204.51 seconds,
on PostgreSQL17.6, in addition to the16 targeted publication PG cases below.
Fresh disposable ComposeHelper v2, 512MiB/0.5CPU, owned database/network/volume,
30GiB preflight and finally cleanup; no runtime data was copied. Retained local
evidence is `.local/publication-full-coverage.{log,xml}` and
`.local/publication160-abf7e8c16b/{result.json,pytest.log,junit.xml,compose/journal.json}`.

Actual normal Build `ec7b4199433f4a10b3ed55fc3b0b6817` now packages source
`9ce5d5d95776a425bfacb26eb74cafdbebd902d7` with the same production/tests trees.
Image `sha256:4df018d8d4795ea76050329e796d4482618c00f487b36ea2074a222fed371414`
passes the real fresh-database Compose readiness check: migration head
`0023_catalog_publication_author`, database/schema/catalog health and all six
catalog operations in the HTTP OpenAPI (45 paths). The owned v2 project is
cleaned; no stand, credentials or publication was changed. Original Build
receipt SHA256 `4be46559212efda0e62e20e9ddefe10fb68e1f2b1ac051e9a4cb02c0b77a326b`;
readiness result SHA256 `2ece3b3108ea9b250c5ebd6ff7e73b5e7c69b00ab8d3f4f3e8c670fa0a1db8da`.

This supersedes the earlier partial full-gate status below. Editor/client
adoption, orchestrator-specific deployment and installed/live text publication
remain open. The PM package on620f45cd does not wait for this API-only feature.

## Boundary

The existing `workflow_modes.catalog_version` and
`workflows.active_catalog_version` are the execution model. A saved draft is a
new set of mode/phase rows, **not activation**. Explicit publication records its
canonical content/hash and selects that version atomically for new executions.
No second engine, file bootstrap, automatic conversion or runtime restart is
introduced. Once this server/API package is installed, subsequent text-only
publications require no Fleet/Hermes image rebuild or configuration change.

Only the current sealed `single-task-v1` family (seven roles/eight modes) can
publish. Mode/phase keys, order/count, synchronous execution, skills, role,
scope and workspace policy remain fixed. Editable text is mode/phase names,
phase description, instruction descriptions and existing check/evidence text.
Blank required text and extra/structural fields fail closed. This is an
administrator operation, not a capability granted to an assigned agent.

Every distinct pending draft appends rows; saving a correction creates another
version. Under the existing catalog lock, an identical pending snapshot reuses
its saved version instead of appending duplicates. Active-base CAS still applies.
An unpublished draft can never execute. Publication changes only the active
version pointer and inserts one receipt; old modes, phase IDs, tasks,
assignments, reports and terminal receipts are not updated. Existing executions
keep their assigned `mode_id`, including subsequent reports after publication.
Only a new task/new cycle chooses the active revision. Recovery/replacement of
an unfinished configured assignment retains that cycle's published mode, under
the same current Tracker authority/CAS guards; it never migrates an active cycle.

Sealed v1 namespace bindings and manifest/catalog hashes remain **baseline
provenance**, not a claim that a text revision equals that manifest. The new
catalog API gives the actual selected version and content hash. Baseline,
published content and assigned historical revision are validated independently;
raw edits, an unsealed active version and pointer rollback fail closed. Legacy
native families remain read-only and cannot use publication to become configured.

## JSON API

All six routes use the existing `require_administrator` dependency, current
human application admission and DB commit guards. They are not machine-agent
runtime endpoints. Responses are `Cache-Control: no-store`.

1. `GET /api/workflows/{workflow_id}/catalog`
   returns `{ok:true,revision:{workflow_id,catalog_version,content_sha256,modes}}`.
   `modes` is the complete current snapshot, without mutable database row IDs.
2. `POST /api/workflows/{workflow_id}/catalog/drafts`
   accepts `{expected_version,expected_sha256,modes}`. Start with the GET
   snapshot and change only the permitted text. Returns
   `{ok:true,revision:{workflow_id,catalog_version,content_sha256,modes,published:false,active_catalog_version}}`.
   Saving does not move the active pointer or create an execution. Identical
   pending content returns the same version, even after another distinct save;
   a changed active base still requires reload rather than bypassing CAS.
3. `GET /api/workflows/{workflow_id}/catalog/drafts`
   returns the highest pending version in the same full snapshot shape, or
   `{ok:true,revision:null}` if none remains. This recovers a saved draft after
   reload or a lost save response, without requiring local editor JSON.
4. `GET /api/workflows/{workflow_id}/catalog/drafts/{version}`
   returns the exact saved snapshot/content/hash and current active version.
   Unknown versions return `404`. If already published, `published:true` and
   retained publication metadata are returned instead; this read never activates.
5. `POST /api/workflows/{workflow_id}/catalog/drafts/{version}/publication`
   accepts the following exact body, using values returned by the preceding
   reads/save, not guessed versions or hashes:

   ```json
   {
     "expected_version": 1,
     "expected_sha256": "<current-content-sha256>",
     "draft_sha256": "<saved-draft-content-sha256>",
     "operation_key": "catalog-review-20261029-pm"
   }
   ```

   Returns the full published revision with `published:true`. Catalog lock,
   expected active version/hash, draft hash and structural validation are
   checked in the same transaction. Exact operation replay returns the original
   revision even after later publications; changed payload/key reuse conflicts.
   New publications also return `published_by_subject` and `published_at` (UTC).
   The subject comes only from the already verified central human identity;
   the server records the time. Body author/time fields are rejected, headers
   cannot override them, and standalone administration without verified identity
   cannot publish (`401`). Replay retains the original author/time, including
   when another currently authorized administrator reads/replays the operation.
6. `GET /api/workflows/{workflow_id}/catalog/publications/operations/{operation_key}`
   reads that original published revision without effects. After an unknown
   publish outcome, read this exact key first; never invent another key.

Missing workflow/operation is `404`; stale/tampered/structurally changed content
is `409`; malformed outer commands are `422`; denied administration is `403`.
Normal editor save routes remain read-only for configured catalog rows. UI157
does not acquire publication controls in this package; integrating its editor
with these explicit JSON operations is separate work, not an implicit save hook.
This API-only package does **not** constitute accepted text editing in the UI.

### Editor Handoff

After Zeno UI's main package: read active snapshot; save text against its exact
version/hash; recover pending or exact saved version on reload; preview the
server-returned content; explicitly publish that saved version/hash against a
fresh active base with one stable operation key. Resolve an unknown publication
outcome by operation readback. Never silently rebase stale edits or publish on
save. A highest pending version is discovery, not proof that it is the current
editor's own save; compare content or use the retained exact version.

Backend contract is ready for that handoff; UI agreement/integration is pending.
No Zeno thread/agent identity was available to address the requested coordination;
the main UI work is not blocked or altered by this package.

## Integration Registration

- Migrations: `0021_profession_task_workflows` -> `0022_catalog_publication`
  -> `0023_catalog_publication_author`; one linear Workflow head. Migration 22
  creates receipts; forward migration 23 adds author/time without changing 22.
  Existing pre-audit receipts keep null author/time, never an invented identity.
  New application publications always record both. Startup accepts 21 and 22 as
  upgrade predecessors. Published history/authorship prevents destructive downgrade.
- Integrator order for the **next** release: reconcile the migration slot
  against then-current master; qualify synthetic PostgreSQL/upgrade and API
  gates; install the Workflow server/API package; only then expose publication
  in an editor/client. No Tracker DTO/migration or Fleet/Hermes dependency is
  introduced. Current installed `620f45cd` PM acceptance continues independently.
- No schema-version change to the existing single-task binding DTO: its IDs
  describe sealed baseline v1. Consumers that need the selected text revision
  must use the new catalog API, not reinterpret that baseline hash/version.
- Source tests are not installation or live acceptance. Full PostgreSQL integration,
  full project gate, packaging and Docker/Kubernetes qualification remain separate
  gates until actually executed on the exact candidate. No runtime DB copies.

## Source Verification

Current production subtree `156956017cceb3afe3d37f2f53195d12cdf9619d`
and tests subtree `3b99c068045ae3380876b5957fb77bfa30101fd5`:

- **482 passed, 20 deselected**, 337.93 seconds, with ResourceWarning and
  PytestUnraisableExceptionWarning treated as errors. Selected files:
  `test_catalog_publication`, `test_api_gaps`, `test_runtime_catalog_read_scope`,
  `test_configured_cli`, `test_initial_migration`,
  `test_profession_execution_membership_migration`,
  `test_configured_catalog_migration`, `test_retained_pm_migrations`,
  `test_phase_effective_view`, `test_managed_catalog_editing`,
  `test_single_task_instructions`, `test_single_task_artifact_instructions`,
  `test_single_task_source_context_instructions`, `test_identity_deletion`,
  `test_session_and_templates`, `test_sso` (all under `tests/`, `.py`).
  Flags: `-q --timeout=60 -x -k 'not browser'` plus the two warning filters.
  Of those 20 exclusions, nine SSO-origin unit cases were then run separately:
  **9 passed, 32 deselected**, 6.20 seconds, using
  `tests/test_sso.py -k browser_origin` with the same timeout/warning filters.
  The remaining 11 are browser cases; no browser acceptance is claimed.
- Ruff: `All checks passed!`; mypy: no issues in 165 source files;
  `git diff --check` and indexed repository hygiene: PASS.
- The existing isolated `.venv` matches all 53 exact `constraints.txt` pins.
- **16 PostgreSQL passed**, 102.32 seconds, PostgreSQL 17.6, on commit
  `4c00021f202b809f0e8d22cb66326cfbfaa8454c` with the source/test trees above.
  Command: `pytest -q -m integration tests/test_catalog_publication_postgres.py
  --timeout=120 -x`, with both warning filters above. These exercise all eight
  modes, retained terminal history/recovery, v2 replay after v3, restart, persisted
  draft readback and real concurrent save dedup/publication CAS.
  Fresh synthetic DBs only, never runtime data or copies. ComposeHelper v2 project
  `sdlc-qa-publication160-41f4135c49`, 512 MiB limit, 0.5 CPU, own network/volume,
  random loopback port; host free disk exceeded 30 GiB. Cached immutable image:
  `sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94`.
  Finally cleanup journal is `cleaned`; a subsequent exact-project container,
  network and volume query returned zero resources. Local retained evidence:
  `.local/publication160-41f4135c49/{result.json,pytest.log,junit.xml,compose/journal.json}`.
- The earlier full non-PG/coverage attempt was stopped after finding the route Mock-key
  regression. The guard now requires a real string, and all selected affected
  API cases pass. That partial attempt is **not** a full PASS or a coverage
  measurement. The Current Source Gate above closes the later complete non-PG/
  coverage and mandatory project PG runs; packaging and installation remain open.

These are source tests with controlled Auth/Tracker/advisor peers and synthetic
SQLite history. They do not attest installed CLI capabilities or live role work.

The audit/draft-readback follow-up separately proves with synthetic SQLite:
exact v2 operation replay after v3 does not roll the pointer back; normal startup
and engine restart retain v2 while the old assignment remains pinned; real SSO
admission supplies the author and rejects demotion/spoofing; upgrade from a
pre-audit receipt preserves history; reload reads full persisted draft content;
repeated identical saves do not add versions. The focused publication file has
**32 passed**, warnings-as-errors, also included in the 482-test selection.
The historical 344-test result is superseded for these selected paths, not
reused as qualification of changed source. PG concurrency/restart/dedup checks
are included in the actual 16-case PostgreSQL result above. This bounded PG gate
does not replace the full project PostgreSQL integration suite or live acceptance.

## Read-Only Tracker Contract Review

Tracker remote main observed at `b54f9e6c6d704ed28ed46eb59a0ddb817299a89c`.
The reviewed local `49e75898` CLI tree equals remote main's `backend/cli` tree:
`d5a52381b63641644ad39672b921d8077d555491`. Relevant lifecycle app/domain/infra
and configured DTO blobs also match remote main. No Tracker files were changed.

All modes start with real `task-tracker sdlc context --task TASK_UUID` and
`project-workflow --json step --task WORKFLOW_TASK_KEY`; task UUID, Workflow key,
Tracker execution ID and Workflow execution ref are deliberately distinct.
The final phase report assesses actual work, never its own future receipt or
comment. Only after accepted `complete=true` do returned `completion_instructions`
require the ordinary final comment and the guarded Tracker command below.

| Role / Mode | Existing Tracker command and strict role result |
| --- | --- |
| PM / draft | `sdlc revision publish`, `sdlc question publish`, `sdlc confirmation read`, then `sdlc pm completion submit` with the real final Workflow receipt selectors; owner alone confirms exact revision/hash; Draft -> Backlog/Ready, no Analyst |
| Analyst / analysis | `sdlc result propose`: `result={role:analyst,analysis:ArtifactReceipt}` |
| Architect / decomposition | same command: `result={role:architect,design:ArtifactReceipt}`, plan inside this task, no child DAG |
| Developer / initial | same command: `result={role:developer,commit_sha,changes:ArtifactReceipt,checks:[ArtifactReceipt]}` |
| Developer / rework | same typed result for the repaired candidate, then repeat Review/Testing |
| Reviewer / delivery | same command: `result={role:reviewer,verdict:approved\|rework,report:ArtifactReceipt}` |
| Tester / delivery | same command: `result={role:tester,verdict:passed\|rework,report:ArtifactReceipt}` |
| DevOps / delivery | same command: `result={role:devops,deployment:ArtifactReceipt,verification:ArtifactReceipt}` |

Full commands are `task-tracker sdlc discussion publish --task TASK_UUID
--from-file -` / `discussion operation --task TASK_UUID --key KEY`, then
`task-tracker sdlc result propose --task TASK_UUID --from-file -` /
`result operation --task TASK_UUID --key KEY`. Proposal JSON is exactly
`{fence,workflow_receipt,result,idempotency_key}`. Non-PM `DeliveryFence` is
`{assignment_id,execution_id,fencing_token,lease_id,expected_lease_version}` from
authorized lifecycle, **not** the four-field PM/comment MachineFence.
`workflow_receipt` is the actual returned `{reference,sha256}` artifact, not a
locally invented phase hash. Typed proposal does not complete the stage: Fleet
must attest actual terminal before scheduler-owned Tracker Complete.

Actionable remaining boundaries, not PM blockers:

- Tracker deliberately rejects EnsureQueued/Reserve from configured Draft or
  Backlog. Publication does not opt the current PM task into Analyst or the full
  flow. Downstream admission is a separate integrator-owned behavior package;
  do not remove this guard or claim seven-role live readiness here.
- The sealed non-PM final phase uses generic wording "exact assigned candidate"
  even for initial Analyst/Architect/Developer work. Their source-context
  instruction correctly forbids inventing a future candidate SHA. A reviewed
  next text revision should distinguish existing-candidate verification from
  initial source/base coordinates and actual produced output. Existing sealed
  catalogs are not silently rewritten for this wording issue.
- Runtime terminal instructions name real Tracker commands and typed results,
  but source-only checks do not prove installed CLI/server support, permissions,
  sealed artifacts, actual terminal delivery, Rework or deployment acceptance.
  Those remain exact-cohort synthetic/integration/live gates, not a reason to
  hold the accepted PM catalog or the present UI157 work.

### E: Explicit Downstream Start

Post-publication read-only review of Tracker main `b54f9e6c` found **no current
operation that explicitly starts downstream configured delivery from a completed
PM Backlog/Ready task**. This is a missing producer, not permission to mutate a
stage or manually assign each role:

- `backend/api/src/routes/sdlc.rs:151` registers only
  `GET /api/v1/issues/{id}/sdlc/analysis-intent`; `task-tracker sdlc intent` is
  also GET-only. The repository returns 404 outside Analysis; it never creates
  an intent on read (`backend/infra/src/sdlc.rs:1065`).
- The existing writer is `POST /api/v1/issues/{id}/sdlc/lifecycle`, with commands
  Reconcile, EnsureQueued, Reserve, Heartbeat, BindRun and Complete. There is no
  explicit start/activation command. EnsureQueued/Reserve reject configured
  Draft/Backlog (`backend/infra/src/sdlc_lifecycle.rs:1107`).
- `TASKTRACKER_SDLC__SINGLE_TASK_PROJECT_IDS` is a project allowlist, not an
  activation operation. `backend/infra/src/sdlc_candidates.rs:23` excludes
  configured tasks before pagination even in an enabled project.
- `backend/infra/src/sdlc.rs:79` explicitly labels `seed_analysis_fixture`
  `cfg(test)`: it imports a synthetic initial technical snapshot under an owned
  DB, briefly disables/restores the initial canonical trigger, and is **not** a
  production PM-to-Analyst transition. These tests cannot prove automatic E.
- Current SQL (`configured_critical_lifecycle.sql:380`) already allows technical
  progression only through the exact existing lifecycle transaction permit and
  retained PM completion. It does not authorize initial Analyst as a PM publish
  side effect. Existing trigger/result/owner guards must remain.

Minimal separate **Tracker producer feature**, not implemented here:

1. One explicit authorized start operation for the opted-in test project/task,
   with original-key readback and exact CAS on current Backlog/Ready, owner,
   requirements revision/hash/confirmation, retained PM completion and routing/
   source generation. Deny an unapproved project, stale consent/current state,
   active conflicting execution and legacy/native history conversion.
2. In one existing owner transaction, create/retain the real Analysis intent and
   initial canonical queued lifecycle/operation evidence under the existing
   permits and outbox. Exact replay returns the same receipt; a changed body
   conflicts. PM completion itself must still create zero intents.
3. Integrate discovery/admission for **explicitly started** configured tasks with
   the existing scheduler and typed terminal/proposal path. Do not simply remove
   the global configured exclusion or add a Fleet planner. Existing automatic
   Complete-to-next-role/Rework handling, not human per-role advance, owns the
   rest of the cycle.
4. Prove no-start means no intent/candidate, one authorized start means one
   intent/queue receipt, concurrent/replayed/stale/foreign-owner cases are fenced,
   and the existing auto flow reaches later roles/Rework without manual advance.
   Synthetic fixtures are source evidence only; actual E remains a separate
   exact-cohort live acceptance.

Any Tracker command/DTO or forward migration needed for that producer requires
its own reviewed package and migration-slot registration; published SQL must
not be rewritten. This report makes no Tracker source changes and blocks neither
the accepted PM cohort on `620f45cd` nor Workflow publication source delivery.
