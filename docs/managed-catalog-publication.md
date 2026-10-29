# Managed Instruction Publication

This is a separate, next-release source package based on master `620f45cd`.
The accepted PM catalog works without it. It does not change the installed
cohort, Fleet assignments/configuration, Hermes, credentials or agent messages.

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

Every saved draft appends rows; saving a correction creates another version.
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

All four routes use the existing `require_administrator` dependency, current
human application admission and DB commit guards. They are not machine-agent
runtime endpoints. Responses are `Cache-Control: no-store`.

1. `GET /api/workflows/{workflow_id}/catalog`
   returns `{ok:true,revision:{workflow_id,catalog_version,content_sha256,modes}}`.
   `modes` is the complete current snapshot, without mutable database row IDs.
2. `POST /api/workflows/{workflow_id}/catalog/drafts`
   accepts `{expected_version,expected_sha256,modes}`. Start with the GET
   snapshot and change only the permitted text. Returns
   `{ok:true,revision:{workflow_id,catalog_version,content_sha256,published:false,active_catalog_version}}`.
   Saving does not move the active pointer or create an execution.
3. `POST /api/workflows/{workflow_id}/catalog/drafts/{version}/publication`
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
4. `GET /api/workflows/{workflow_id}/catalog/publications/operations/{operation_key}`
   reads that original published revision without effects. After an unknown
   publish outcome, read this exact key first; never invent another key.

Missing workflow/operation is `404`; stale/tampered/structurally changed content
is `409`; malformed outer commands are `422`; denied administration is `403`.
Normal editor save routes remain read-only for configured catalog rows. UI157
does not acquire publication controls in this package; integrating its editor
with these explicit JSON operations is separate work, not an implicit save hook.

## Integration Registration

- Migration: `0022_catalog_publication` after
  `0021_profession_task_workflows`; one linear Workflow head. It only creates
  `workflow_catalog_publications`, no seed rewrite/backfill. Startup accepts
  `0021` as an upgrade predecessor. Published history prevents downgrade.
- Integrator order for the **next** release: reconcile the migration slot
  against then-current master; qualify synthetic PostgreSQL/upgrade and API
  gates; install the Workflow server/API package; only then expose publication
  in an editor/client. No Tracker DTO/migration or Fleet/Hermes dependency is
  introduced. Current installed `620f45cd` PM acceptance continues independently.
- No schema-version change to the existing single-task binding DTO: its IDs
  describe sealed baseline v1. Consumers that need the selected text revision
  must use the new catalog API, not reinterpret that baseline hash/version.
- Source tests are not installation or live acceptance. PostgreSQL lock tests,
  full project gate, packaging and Docker/Kubernetes qualification remain separate
  gates until actually executed on the exact candidate. No runtime DB copies.

## Source Verification

On the final production subtree `d97c3db96663b63185d34054c4cdb90cd25dc4a0`
and tests subtree `bfcbbef72605ed7641dd9797ffcc83f6a81f11d9`:

- **344 passed, 11 deselected**, 292.45 seconds, with ResourceWarning and
  PytestUnraisableExceptionWarning treated as errors. Selected files:
  `test_catalog_publication`, `test_api_gaps`, `test_runtime_catalog_read_scope`,
  `test_configured_cli`, `test_initial_migration`,
  `test_profession_execution_membership_migration`,
  `test_configured_catalog_migration`, `test_retained_pm_migrations`,
  `test_phase_effective_view`, `test_managed_catalog_editing`,
  `test_single_task_instructions`, `test_single_task_artifact_instructions`,
  `test_single_task_source_context_instructions` (all under `tests/`, `.py`).
  Flags: `-q --timeout=60 -x -k 'not browser'` plus the two warning filters.
  The 11 exclusions are browser cases, not executed acceptance.
- Ruff: `All checks passed!`; mypy: no issues in 164 source files;
  `git diff --check` and indexed repository hygiene: PASS.
- The existing isolated `.venv` matches all 53 exact `constraints.txt` pins.
- Twelve tests in `tests/test_catalog_publication_postgres.py` collect with
  `-m integration`; **not executed**. They require only disposable synthetic PG
  fixtures, never a copy of runtime data.
- The full non-PG/coverage attempt was stopped after finding the route Mock-key
  regression. The guard now requires a real string, and all selected affected
  API cases pass. That partial attempt is **not** a full PASS or a coverage
  measurement. Full non-PG/94% coverage, actual PG/locking and installation
  gates remain open for this next-release Draft.

These are source tests with controlled Auth/Tracker/advisor peers and synthetic
SQLite history. They do not attest installed CLI capabilities or live role work.

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
