# PM Continuation Verification

## Immutable PM Namespace Ownership (2026-10-02)

This current foundation supersedes older namespace-ownership GAP entries below;
older sections retain historical gate evidence, not current ownership status.
This bounded follow-up adds write-once namespace -> Tracker instance/project
authority, not PMDraft admission. Provision/readback independently require fresh
bounded Base PAT introspection, standard scopes plus exact namespace grants;
provisioning additionally requires the configured canonical central machine
subject. These new grants/policies are configuration prerequisites, not issued
by this PR. No cookie/local/runtime token fallback or caller issuer/actor claim
is accepted. Instance refs are exact 1..128 UTF-8 bytes without whitespace/control;
UUIDs are canonical lowercase and non-nil. Stored actor, issuer, UUID and time
remain immutable on same-owner replay. SQL uniqueness and RESTRICT FK fence
namespace and reverse Tracker instance/project ownership.

Fleet `backend/domain/src/pm_execution.rs` uses Rust string byte length in
`valid_ref(value, 128)`. Final review corrected Python character-count acceptance:
an exact 128-byte Unicode scalar string is preserved, 129+ bytes and invalid
surrogates are rejected before mutation. Generated OpenAPI exposes
`x-max-utf8-bytes=128`; standard maxLength alone counts characters. No identity/
callback fields, generic DTO or migration changed for this correction.

Provision and new enrollment lock Catalog -> Project -> Task where applicable.
The first full PG candidate exposed a real deadlock: generic continuation held
Task and needed Project FK KEY SHARE while PM bind held Project FOR UPDATE and
waited for Task. The dedicated PM namespace lock now uses FOR NO KEY UPDATE,
which serializes provisioning/enrollment without blocking that FK lock. Existing
generic Project FOR UPDATE locks are unchanged. SQL compilation and both PG
race orders protect this distinction; catalog bootstrap retains catalog-first
locking. New enrollment requires matching persisted ownership, with no implicit
backfill. Legacy exact bind replay, readback and checkpoint/resume remain valid
without the new mapping; the old execution identity/assignment never moves.

Only pending `0007_pm_execution` is extended, after accepted `0006`; published
`0001`-`0006` are unchanged. It adds an initially empty ownership table and
UPDATE/DELETE rejection. Fresh and 0006 upgrades pass; an old applied pending
0007 without this table fails schema readiness and is not silently repaired.

Own Linux QA source is `/tmp/workflow-pm-ownership-qa-source-20261002`.
Final PostgreSQL 16 runs used only owned `workflow-pm-ownership-utf8-qa-db`,
loopback 55451, with isolated per-test databases and auto-remove/tmpfs storage.
Final gates:

| Gate | Ownership Result |
| --- | --- |
| Full unit + coverage + strict resource warnings | 2,097 passed, 76 integration deselected, 916.04s; coverage 94.26%, threshold 94 enforced |
| Full canonical PostgreSQL integration | 76 passed, 218.19s, exit 0 |
| Focused ownership/auth/strict wire/legacy continuation | 60 passed, 16.78s |
| Focused ownership/PM/security/contracts/docs | 237 passed, 87.03s |
| PostgreSQL ownership/catalog/generic lock races | Included in full 76 pass; both race orders |
| Ruff | All checks passed |
| Mypy | Success, 102 source files |
| Generated OpenAPI | Regenerated; identity 10 / Fleet callback 18 unchanged |
| Development image / isolated Compose | Passed; health HTTP 200, database/schema/catalog ok |
| Unconfigured authority / release preflight | Expected typed 503; no synthetic grants or provenance |

The final unit gate emitted only the two existing SQLAlchemy transaction/savepoint
warnings in UI app tests; strict ResourceWarning/unraisable checks passed. Runtime,
test and migration sources matched the worktree byte-for-byte and did not change
after these final gates. Only this verification record was completed afterwards;
final docs/generated-contract checks are rerun before commit.

Commands used the canonical prefix
`uv run --isolated --with-requirements constraints.txt --all-extras`:

```text
COVERAGE_FILE=.coverage.ownership-utf8-final pytest -q --cov=project_workflow --cov-report=term --timeout=60 -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --basetemp=/dev/shm/workflow-pm-ownership-utf8-unit-20261002
PGHOST=127.0.0.1 PGPORT=55451 pytest -q -m integration tests/test_postgres_integration.py --timeout=120 --basetemp=/dev/shm/workflow-pm-ownership-utf8-pg-20261002
pytest -q tests/test_namespace_ownership.py --timeout=60 -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
pytest -q tests/test_namespace_ownership.py tests/test_pm_execution.py tests/test_pm_assignment_guard.py tests/test_pm_generic_continuation.py tests/test_concrete_agent_mapping.py tests/test_runtime_assignment_contract.py tests/test_docs_quality.py --timeout=60
ruff check .
mypy project_workflow scripts
python -m scripts.export_pm_openapi
git diff --check
```

Implementation and contract files:

```text
project_workflow/domain/namespace_ownership.py
project_workflow/domain/repositories.py
project_workflow/infrastructure/namespace_auth.py
project_workflow/infrastructure/db/models.py
project_workflow/infrastructure/db/repositories/project.py
project_workflow/infrastructure/db/migrations/versions/0007_pm_execution.py
project_workflow/application/namespace_ownership.py
project_workflow/application/pm_execution.py
project_workflow/interfaces/ui/routes/namespace_ownership_api.py
project_workflow/interfaces/ui/app.py
project_workflow/interfaces/ui/sso.py
project_workflow/config.py
.env.example
docker-compose.yml
scripts/export_pm_openapi.py
tests/test_namespace_ownership.py
tests/test_pm_execution.py
tests/test_postgres_integration.py
tests/test_docs_quality.py
docs/pm-namespace-ownership.md
docs/pm-continuation-openapi.json
docs/pm-continuation-contract.md
docs/runtime-assignment-contract.md
docs/pm-continuation-verification.md
```

Development image digest was
`sha256:ea57a08d66b363c6b7ba5dce3ad1ae4a5352f716f47177a899d9031e82e6c6db`.
The image tag and all owned QA Compose containers/network/volumes were removed.
PG fixture teardown left only default postgres/project_workflow/template databases
before the standalone PG container was removed. No shared runtime, pins, Base
credentials/policy or UI changed; browser verification is not applicable.

Remaining product GAP: the current catalog has ONE managed PM namespace, so
this rollout supports only ONE explicitly mapped Tracker instance/project pair.
Multi-project routing is not completed. Tracker reservation allocates authoritative
UUID/version/ordinal and immutable input with dispatch_allowed=false; ownership
does not enable dispatch. PMDraftAdmission/owner CAS, explicit replacement history
and verified prior quiescence, real workspace/lease producer, actual concrete Fleet
agent validation and source-pinned native skills/release remain separate work.
Typed not-applicable may cover queue/decomposition/delivery, never input/workspace.
General Delivery DTO, ten-field identity and eighteen-field callback are unchanged.

## Enrolled PM New Assignment Guard (2026-10-02)

Bounded follow-up on `014bb76`: the proven done-but-running generic `/assign`
escape is closed. Any immutable PM enrollment of the task rejects a new generic
assignment with service ConflictError / HTTP 409, regardless of current cursor,
PM state or old terminal receipt. Task-wide indexed EXISTS uses the existing
unique `pm_executions.task_id` index under the same authoritative task lock as
PM bind, after exact historical replay and before assignment mutations.
No migration, DTO/callback/identity change, runtime probe or replacement is added.

Regressions exercise normal resumed scoped PASS to task=done while PM=active,
callback=running and terminal receipt absent, then deny both a fresh cycle and
retry without changing any task/assignment/event/history/PM table values.
Historical same-key replay remains read-only; changed payload conflicts. A
second replay read under the owner lock is preserved. Enrollment cannot be hidden
by a missing current assignment pointer. A terminal readback alone remains denied.
PostgreSQL additionally checks normal done denial, concurrent historical replay
versus new assignment, and both owner-lock race orders. PM enrollment winning
fences the waiting new assign; an unenrolled ordinary completed assignment winning
creates its accepted generic cycle and makes the old PM bind stale without partial
enrollment. Non-enrolled generic behavior also retains its existing full-suite tests.

Own Linux QA source: `/tmp/workflow-pm-assign-guard-qa-source-20261002`.
Test basetemp directories are owned `/dev/shm/workflow-pm-assign-guard-*` targets.
PostgreSQL uses only `workflow-pm-assign-guard-qa-db` on loopback port `55449`.
Final runtime/test sources match the worktree byte-for-byte. Final gates:

| Gate | Assignment Guard Result |
| --- | --- |
| Full unit + coverage + strict resource warnings | 2,037 passed, 70 integration tests deselected, 813.67s; coverage 94.18%, threshold 94 enforced |
| Canonical PostgreSQL integration | 70 passed, 204.89s, exit 0 |
| Focused security/contracts/docs | 139 passed |
| New PostgreSQL guard/replay/race cases | 5 passed |
| Ruff | All checks passed |
| Mypy | Success, 98 source files |
| Development build / isolated Compose | Passed; HTTP 200, database/schema/catalog ok; built image includes guard |
| HTTP wire / authenticated preflight | PM identity 10 fields, callback 18; expected 503 without release provenance |

The unit run emitted only the two existing SQLAlchemy transaction/savepoint
warnings in UI app tests; ResourceWarning/unraisable checks passed. Coverage
here is the final standalone unit gate, not the previous reconciliation's merged
coverage. Runtime, tests, schema and migration files did not change after these gates;
only this verification record was completed. Final docs/generated OpenAPI are
checked again before commit.

Commands run from the owned Linux source, with prefix
`uv run --isolated --with-requirements constraints.txt --all-extras`:

```text
COVERAGE_FILE=.coverage.guard-unit pytest -q --cov=project_workflow --cov-report=term --timeout=60 -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --basetemp=/dev/shm/workflow-pm-assign-guard-unit-final-20261002
PGHOST=127.0.0.1 PGPORT=55449 pytest -q -m integration tests/test_postgres_integration.py --timeout=120 --basetemp=/dev/shm/workflow-pm-assign-guard-pg-final-20261002
pytest -q tests/test_pm_assignment_guard.py tests/test_pm_generic_continuation.py tests/test_concrete_agent_mapping.py tests/test_runtime_assignment_contract.py tests/test_docs_quality.py --timeout=60 --basetemp=/dev/shm/workflow-pm-assign-guard-security-final-20261002
pytest -q -m integration tests/test_postgres_integration.py -k "normal_done_rejects or done_assignment_replay or enrollment_and_new_assignment" --timeout=120 --basetemp=/dev/shm/workflow-pm-assign-guard-pg-focused-20261002
pytest -q tests/test_docs_quality.py tests/test_pm_execution.py::test_openapi_exposes_pm_wire_and_callback_schema --timeout=60 --basetemp=/dev/shm/workflow-pm-assign-guard-docs-final-20261002
ruff check .
mypy project_workflow scripts
```

Follow-up files:

```text
project_workflow/application/task.py
project_workflow/domain/repositories.py
project_workflow/infrastructure/db/repositories/task.py
tests/test_pm_assignment_guard.py
tests/test_postgres_integration.py
docs/pm-continuation-contract.md
docs/runtime-assignment-contract.md
docs/pm-continuation-verification.md
```

The owned development image digest was
`sha256:976b37a4ab659fc4271034ae506760ec6c8eb4a44250f639ce8242ac2db74b22`.
Its image tag, Compose containers/network/volumes and standalone PG container
were removed after checks. PG fixture teardown left only the owned default
postgres/project_workflow databases before removal. UI is unchanged; browser
verification is not applicable. No shared runtime/schema or pinned image changed.

Remaining GAP: PMDraftAdmission still needs trusted immutable input, real business
workspace/lease provenance, owner-issued CAS, execution ordinal, authoritative
namespace ownership and explicit replacement history. The current unique PM task
binding cannot be moved to a new assignment. Unknown prior quiescence fails closed;
the guard is containment, not implementation of replacement or live PM admission.
Native immutable skills access/release provenance remains an external prerequisite;
development readiness is not a release-compatible build or live PM proof.

## Accepted Master Reconciliation (2026-10-02)

The bounded reconciliation merges accepted master
`ef66f165a5eb85895f43f67829273291f428850c` into `feat/pm-clarification`,
not the feature into master. Accepted catalog v2, scope sets, compatibility
pins, generic continuation and builder are preserved. Published migrations
`0001` through `0006` are byte-for-byte unchanged relative to that master.
Only this feature's pending migration was moved to `0007_pm_execution`, with
`down_revision=0006_versioned_mode_catalog`. This PR owns one new migration.

Generic continuation now checks immutable PM enrollment through the task
repository's indexed EXISTS query, under the same owner task lock as PM bind.
It rejects new continuation before mutations regardless of PM/task status.
Exact historical generic replay remains read-only. PM resume/rebind preserves
its original assignment identity and is the only continuation for enrolled PM.
PM commands also revalidate catalog v2/frozen compatibility before runtime probes.
The ten-field PM identity and existing eighteen-field Fleet callback are unchanged;
canonical agent UUIDs still reject nil at both schema and service boundaries.

Regression evidence includes active/waiting/resume-pending PM with active,
blocked and done tasks; unchanged cursor/revision/history/ledger on generic 409;
valid PM resume after denial; generic historical replay after enrollment;
accepted non-PM generic continuation; descriptor missing/drift/v1 refusal;
and both PostgreSQL owner-lock races. PM winning rejects generic continuation;
generic winning makes the prior PM bind stale without partial PM records.

Final runtime source is frozen in the owned Linux QA directory
`/tmp/workflow-pm-reconcile-qa-source-20261002`, with pinned constraints and
isolated uv runs. SQLite targets use owned `/dev/shm` directories; PostgreSQL 16
uses only `workflow-pm-reconcile-qa-db`, port `55449`, and disposable test databases.

| Gate | Reconciliation Result |
| --- | --- |
| Full unit, strict resource warnings and coverage | 2,029 passed, 65 integration tests deselected, 1838.66s; unit coverage 94.18%, threshold 94 enforced |
| Canonical PostgreSQL integration gate | 65 passed, 690.13s, exit 0 |
| PG coverage collection | 65 tests passed; subset coverage 63.18%, not a full-suite coverage gate |
| Combined final unit/PG coverage | 94.79%, threshold 94 enforced |
| Focused security/contracts + docs | 131 passed |
| PM generic boundary module | 14 passed |
| Ruff | All checks passed |
| Mypy | Success, 98 source files |
| Final docs/generated OpenAPI check | 14 passed |
| QA development image/Compose | Build/readiness passed; HTTP 200, database/schema/catalog ok |
| HTTP wire check | Callback 18 fields, PM identity 10 fields, explicit nil exclusion |
| Authenticated development preflight | Expected 503 without immutable build/compatibility manifest |
| Diff whitespace | Passed |

Exact gate commands run from the owned Linux source directory, using prefix
`uv run --isolated --with-requirements constraints.txt --all-extras`.
The PostgreSQL gate additionally sets `PGHOST=127.0.0.1` and `PGPORT=55449`;
credentials/database are the owned QA `project_workflow` fixture defaults.

```text
COVERAGE_FILE=.coverage.unit pytest -q --cov=project_workflow --cov-report=term --timeout=60 -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --basetemp=/dev/shm/workflow-pm-reconcile-unit-final-20261002
pytest -q -m integration tests/test_postgres_integration.py --timeout=120 --basetemp=/dev/shm/workflow-pm-reconcile-pg-gate-20261002
pytest -q tests/test_docs_quality.py tests/test_pm_generic_continuation.py tests/test_concrete_agent_mapping.py tests/test_runtime_assignment_contract.py --timeout=60 --basetemp=/dev/shm/workflow-pm-reconcile-security-final-20261002
pytest -q tests/test_docs_quality.py tests/test_pm_execution.py::test_openapi_exposes_pm_wire_and_callback_schema --timeout=60 --basetemp=/dev/shm/workflow-pm-reconcile-docs-final-20261002
ruff check .
mypy project_workflow scripts
COVERAGE_FILE=.coverage.merged coverage combine --keep .coverage.unit .coverage.pg
COVERAGE_FILE=.coverage.merged coverage report --fail-under=94
```

The full unit run emitted two existing SQLAlchemy transaction/savepoint
warnings in UI app tests; strict ResourceWarning/unraisable gates passed.
Combined coverage contains only the final frozen runtime source, not the
historical mapping run or the separate read-only admission probe below.

The development smoke image was built from Git QA snapshot
`e44efd2c224d445a29f5910bbd60dcfde925d05b`; its source archive SHA-256 is
`30543cbf37a123370202faa0865669924a21e9f089b9de9b06c60d86c0df8597`.
Later changes are documentation only, not runtime source. This is a standard
development build, not a release-compatible image: the native skills checkout
at accepted pin `46eb27f70b68cbefbf53903090f0c7f0fa68b748` was unavailable locally
and GitLab denied non-interactive source access. No fixture manifest or guessed
release provenance was substituted. The expected capabilities 503 is fail-closed,
not proof of PM admission readiness. Owned Compose containers, network, volumes
and image tag were removed after HTTP smoke.
The standalone integration container was removed after the canonical gate;
all test-created databases had already been dropped by fixture teardown.

Reconciliation-specific files (accepted auto-merged files are not rewrites):

```text
project_workflow/application/pm_execution.py
project_workflow/application/task.py
project_workflow/domain/repositories.py
project_workflow/domain/runtime_assignment.py
project_workflow/infrastructure/db/repositories/task.py
project_workflow/infrastructure/db/session.py
project_workflow/infrastructure/db/migrations/versions/0007_pm_execution.py
project_workflow/interfaces/ui/routes/runtime_api.py
scripts/export_pm_openapi.py
tests/test_pm_generic_continuation.py
tests/test_pm_execution.py
tests/test_initial_migration.py
tests/test_postgres_integration.py
tests/test_session_and_templates.py
docs/architecture.md
docs/pm-continuation-contract.md
docs/pm-continuation-openapi.json
docs/pm-continuation-verification.md
docs/runtime-assignment-contract.md
```

Main retains cross-service security, migration rollout and release ownership.
PMDraftAssignment admission, trusted Tracker input/owner CAS, authoritative
namespace ownership, execution ordinal and live PM acceptance remain separate.
No generic Delivery DTO was relaxed, no admission implemented, and no shared
runtime, schema or pinned image was changed. Publication remains Draft only;
new reconciliation commits deliberately do not skip GitHub CI.

Read-only admission assessment: task `done` is not PM run quiescence.
The following probe describes the pre-guard tree; the follow-up above now refuses
its new generic assignment. The quiescent replacement/admission GAP remains open.
`supervisor/transitions.py` records `done` on the last PASS without closing PM
execution/run. Existing `test_resumed_supervisor_report_is_persistent_and_replayable`
in `tests/test_pm_execution_edges.py` exercises that normal terminal path.
An owned, ignored QA probe reused that test and then observed task=done,
PM execution=active, the resumed callback still running and no terminal receipt.
The protected `/assign` accepted a fresh cycle/revision 2 while the old PM ledger
remained attached to revision 1; old PM readback then became stale. The assessment
probe passed (one test), with no runtime/committed-test changes or live dispatch.
The `done` branch in `application/task.py` validates retry/cycle but does not check
PM quiescence. Normal waiting/pending runtime steps are fenced; no public manual
task-status UI mutation was found, so this assessment does not claim such a path.

Future PMDraftAdmission must check prior enrolled execution/run under the owner
lock before any new assignment/dispatch: exact trusted terminal readback plus
durable owner CAS confirming no live or pending resume/dispatch/lease. Unknown
status, task done, a workflow PASS or a submitted terminal claim are insufficient.
A fresh cycle may allocate a new execution/ordinal only after that reconciliation;
resume retains its identity/ordinal. The current unique PM task binding also needs
an explicit replacement-history design, not moving the old ledger onto a new
assignment. This remains a separate admission prerequisite; generic non-PM
delivery and current assignment behavior were not rewritten in reconciliation.

Everything below is historical evidence from before this reconciliation.
Its old pending migration names and gate results do not describe the current tree.

## Concrete Fleet Agent Mapping Follow-up (2026-10-01)

Authoritative starting state: clean `feat/pm-clarification`, source commit
`a99a5d8e346055c812059cdd14b7069472c43631`.
Catalog phase agent stays `project_manager`; the protected ordinary runtime
bind writes `concrete_agent_ref` separately and freezes it in its CAS/digest.
PM identity and all 18-field callbacks use the same canonical non-nil Fleet agent UUID.
Missing/mismatched mapping and altered bind provenance fail closed before a
runtime probe; enrolled readback, command replay and Supervisor also revalidate it.
Legacy non-PM bind digests remain unchanged when the new field is omitted/null.
The only pending migration remains `0005_pm_execution`; published `0001`-`0004`
are unchanged. Upgrade from `0004` is now admitted by schema initialization.

Follow-up gates use Linux/WSL, pinned `constraints.txt` and `uv run --isolated
--with-requirements constraints.txt --all-extras`. Final source was copied to the
owned native Linux QA directory `/tmp/workflow-pm-mapping-qa-source-20261001`.
Final runs put their owned SQLite fixture targets under `/dev/shm` to avoid
host-disk fsync contention; coverage still measures that same source directory.
PostgreSQL uses only owned `workflow-pm-mapping-qa-db`, loopback port `55449`,
with test-created temporary databases. No shared runtime or existing PG is changed.

| Gate | Follow-up Result |
| --- | --- |
| Full unit + strict resource warnings | 1,970 passed, 56 integration tests deselected, 964.40s; final fixture/source |
| Unit coverage | 94.19%; threshold 94 enforced |
| Final merged unit/PostgreSQL coverage | 94.80%; threshold 94 enforced |
| Focused mapping, PM, assignment and migrations | 194 passed after nil UUID fix |
| Existing managed-catalog PM happy path | 12 passed after adding required concrete UUID to its bind fixture; security assertions unchanged |
| PostgreSQL integration | 56 passed in 587.81s after nil UUID fix |
| Ruff | All checks passed |
| Mypy | Success, 96 source files |
| Final docs/generated OpenAPI check | 14 passed |
| Owned QA image + Compose readiness | Final nil-aware image built; API/database healthy, HTTP 200, database/schema/catalog `ok` |
| Live OpenAPI + authenticated provenance | Exactly 18 callback fields; canonical/non-nil agent schemas; exact snapshot/archive/bundle hashes matched |
| Diff whitespace | Passed |

The final standalone unit gate is green. The separate full coverage collection
initially retained the old managed-catalog PM fixture without concrete UUID:
1,969 passed, one fixture failure, unit coverage 94.16%. Only that bind fixture
was corrected; runtime source stayed frozen. Its final 12-test module coverage
was combined with the full unit collection (94.19%), then final PostgreSQL
coverage (94.80%). No stale pre-nil runtime coverage was combined. The final
full unit gate above was independently rerun on the corrected fixture.
It emitted one Pydantic alias warning and two SQLAlchemy transaction/savepoint
warnings; strict ResourceWarning/Unraisable checks passed.

Exact follow-up commands below use the common pinned `uv run` prefix above.
PostgreSQL commands additionally use `PGHOST=127.0.0.1`, `PGPORT=55449`, and
the owned QA database/user `project_workflow`.

```text
pytest -q --timeout=60 --basetemp=/dev/shm/workflow-pm-mapping-unit-gate-final-20261001 -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
COVERAGE_FILE=.coverage.final pytest -q --cov=project_workflow --cov-report=term --timeout=60 --basetemp=/dev/shm/workflow-pm-mapping-unit-final-nil-20261001 -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
pytest -q tests/test_concrete_agent_mapping.py tests/test_pm_execution.py tests/test_pm_execution_edges.py tests/test_initial_migration.py tests/test_runtime_assignment_contract.py --timeout=60 --basetemp=/dev/shm/workflow-pm-mapping-nil-focused-20261001 -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
COVERAGE_FILE=.coverage.catalog pytest -q tests/test_managed_catalog_hardening.py --cov=project_workflow --cov-report=term --cov-fail-under=0 --timeout=60 --basetemp=/dev/shm/workflow-pm-mapping-catalog-final-20261001 -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
COVERAGE_FILE=.coverage.pg pytest -q -m integration tests/test_postgres_integration.py --cov=project_workflow --cov-report=term --cov-fail-under=0 --timeout=120 --basetemp=/dev/shm/workflow-pm-mapping-pg-final-nil-20261001
COVERAGE_FILE=.coverage.unit-final coverage combine --keep .coverage.final .coverage.catalog
COVERAGE_FILE=.coverage.unit-final coverage report --fail-under=94
COVERAGE_FILE=.coverage.merged coverage combine --keep .coverage.final .coverage.catalog .coverage.pg
COVERAGE_FILE=.coverage.merged coverage report --fail-under=94
ruff check .
mypy project_workflow scripts
```

QA image used immutable staged-source snapshot
`d8c3e7cebcd1a11bbc0a86c54dbd2d454096d40b`, tree
`86ef3e78f0cbe4a19235912d2596e341dbc7d3cd`.
Its archive SHA-256 is
`4eb6748f09f973b490aa6ecdcefc599455f4edcda20d69b2913161b6f61f31b1`
and runtime bundle SHA-256 is
`7a30e3ed9f80c961532bb8857a92c2a278aff2696f5b9f0f0cf3542ab5c626d2`.
Only evidence and the managed-catalog test fixture changed after that snapshot;
its runtime bundle is unchanged. This is QA provenance, not a deployed image
claim for the later publication commit.
The isolated Compose project `workflow-pm-mapping-qa`, its anonymous volumes,
network and QA image tag were removed after its HTTP smoke on port `18849`.
The separate integration PostgreSQL was also removed after its final gate.

Exact files changed by this follow-up:

```text
project_workflow/application/pm_execution.py
project_workflow/application/task.py
project_workflow/domain/__init__.py
project_workflow/domain/pm_execution.py
project_workflow/domain/repositories.py
project_workflow/domain/runtime_assignment.py
project_workflow/infrastructure/db/migrations/versions/0005_pm_execution.py
project_workflow/infrastructure/db/models.py
project_workflow/infrastructure/db/repositories/converters.py
project_workflow/infrastructure/db/repositories/task.py
project_workflow/infrastructure/db/session.py
project_workflow/interfaces/ui/routes/runtime_api.py
project_workflow/interfaces/ui/schemas.py
scripts/export_pm_openapi.py
tests/test_concrete_agent_mapping.py
tests/test_initial_migration.py
tests/test_managed_catalog_hardening.py
tests/test_pm_execution.py
tests/test_pm_execution_edges.py
tests/test_postgres_integration.py
docs/pm-continuation-contract.md
docs/pm-continuation-openapi.json
docs/pm-continuation-verification.md
docs/runtime-assignment-contract.md
```

Remaining owner work: Main owns Fleet integration, security regressions, migration
rollout and release. Fleet must send its persisted concrete agent UUID on ordinary
runtime bind and use that same UUID in PM command/callback identity across resume.
An already finalized PM binding with null mapping cannot be silently enriched.
Any previously applied old `0005` QA schema also needs an explicit owner decision;
head-schema validation refuses that incompatible schema, rather than inventing a
second pending migration or resetting data. The fetched `origin/master`
`ef66f16` now includes `0005_mode_execution_scopes` and `0006_versioned_mode_catalog`;
Main must reconcile this pending PM migration with that advanced chain before
merge/release. This follow-up does not modify shared schema or claim live
Fleet/Hermes continuation acceptance. The subsequent bounded publication was
explicitly authorized as one Draft PR into `master`, not ready/merge/deploy.

The evidence below is historical for the prior implementation, not a claim about
the follow-up's unit or coverage result.

Baseline: `7a720b1e31b5b2832c4e948548bea426205064ef` (`origin/master` at task start).
Implementation branch: `feat/pm-clarification`, isolated Workflow worktree.

Contract: [PM continuation v1](pm-continuation-contract.md).
This change adds PostgreSQL tables `pm_executions`, `pm_runs`, `pm_operations`
through additive migration `0005_pm_execution`. Existing assignments and
Supervisor history remain authoritative. Existing rows are not auto-enrolled.
The immutable assignment acceptance ledger is preserved; the enrolled
execution's verified current run overlays runtime step validation only.

Tests cover API authorization, immutable identity, version/fence checks,
checkpoint wait, terminal proof, durable replay, conflicts, late answers,
scoped tokens, old Supervisor report rejection, raw runtime ID collisions,
exact UUID mapping and OpenAPI schemas. PostgreSQL tests cover concurrent
checkpoint/resume duplicates, fresh application readback, migration/metadata
parity and an actual HTTP callback on old/new Fleet UUIDs. The callback uses a
deterministic test provider, not deployed Fleet or live Hermes.

Fleet's trusted runtime readback endpoint and continuation orchestration are
not yet implemented. Live resume acceptance is not claimed.
Live acceptance is still missing: a compatible Fleet callback probing actual
Hermes, persisted Fleet creation/dispatch saga, runtime dispatch idempotency/
readback, real scoped PM question creation, owner answer persistence in Tracker,
continuation, final revision and exact owner confirmation to Backlog. These
tests do not establish production readiness or cross-service acceptance.
Full lease scheduling remains outside this slice.

## Local Gate Results

Validated on Windows/Python 3.13 using
`uv run --isolated --with-requirements constraints.txt --all-extras`.

| Gate | Result |
| --- | --- |
| Full unit suite with strict resource-warning checks | 1,932 passed, 52 PostgreSQL tests deselected |
| Final-source PM/runtime/schema/capability suite | 150 passed, including six additional negative/repeated-wait cases |
| Final-source full PostgreSQL integration | 52 passed on the owned Compose PostgreSQL instance |
| Final-source PostgreSQL supplement | 4 passed (PM concurrent replay/restart, HTTP callback/new run, concurrent steps, fresh migration parity) |
| Unit coverage, full suite plus final-source supplement | 94.17%; threshold 94 unchanged |
| Final combined unit/supplement/PostgreSQL coverage | 94.79%; threshold 94 enforced |
| Ruff | All checks passed |
| mypy | No issues in 95 source files |
| Compose build/readiness | Owned API/database healthy; HTTP 200, database/schema/catalog all `ok` |
| OpenAPI HTTP smoke | All five PM paths and `RuntimeObservation` present |
| Diff whitespace check | Passed |

The long unit run passed every test but its initial coverage result was 93.09%.
The final schema compatibility edit changed source line positions after that
run had loaded the module. Final-source coverage was collected separately and
merged with the full unit coverage; `coverage report --fail-under=94` passed.
This is merged coverage, not a claim of a second full-unit run after that edit.
The unit run emitted two SQLAlchemy transaction/savepoint warnings in existing
health/logging fixtures; strict ResourceWarning checks did not fail.

Commands (each prefixed with the `uv run` invocation above):

```text
pytest --cov=project_workflow --cov-report=term --timeout=60 -q -x -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
pytest -q -m integration tests/test_postgres_integration.py --timeout=120
pytest -q -m integration tests/test_postgres_integration.py --cov=project_workflow --cov-append --cov-report=term --cov-fail-under=94 --timeout=120
pytest -q tests/test_runtime_api.py tests/test_pm_execution.py tests/test_pm_execution_edges.py tests/test_ui_schemas.py tests/test_runtime_capabilities.py --cov=project_workflow --cov-report=term --cov-fail-under=0 --timeout=60 -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
coverage combine --append --keep .coverage
coverage report --fail-under=94
ruff check .
mypy project_workflow scripts
```

The focused coverage/combination commands used
`COVERAGE_FILE=.coverage.pm-final`; full-unit data was read from `.coverage`.
The final PostgreSQL run used default `.coverage` and combined all collected
data, enforcing 94 with a final result of 94.79%.
The threshold override on the deliberately partial focused run is not the
gate: the merged report enforced 94. PostgreSQL used dedicated ports 55437,
then 55438 for the final supplement and full coverage rerun. The owned Compose project
`workflow-pm-contract` uses override ports 55438/18812; its API OpenAPI URL is
`http://127.0.0.1:18812/openapi.json`. No Docker removal/prune/down commands
were run, and no Fleet or unrelated containers were removed by this task.
Browser checks are not applicable: no UI/templates/static assets changed.

## Modified Files

Backend/schema:

```text
project_workflow/application/pm_execution.py (new)
project_workflow/application/task.py
project_workflow/config.py
project_workflow/domain/pm_execution.py (new)
project_workflow/domain/runtime_assignment.py
project_workflow/infrastructure/db/models.py
project_workflow/infrastructure/db/migrations/versions/0005_pm_execution.py (new)
project_workflow/infrastructure/pm_readback.py (new)
project_workflow/interfaces/ui/app.py (backend route registration only)
project_workflow/interfaces/ui/routes/pm_api.py (new backend machine API)
project_workflow/interfaces/ui/routes/runtime_api.py
project_workflow/interfaces/ui/schemas.py (runtime request schema only)
project_workflow/supervisor/core.py
project_workflow/supervisor/evaluate.py
.env.example
docker-compose.yml (backend settings forwarding only)
```

Tests:

```text
tests/test_pm_execution.py (new)
tests/test_pm_execution_edges.py (new)
tests/test_initial_migration.py
tests/test_postgres_integration.py
tests/test_runtime_capabilities.py
tests/test_runtime_api.py (ordinary command hash compatibility)
tests/test_session_and_templates.py (migration-head expectation only)
```

Documentation:

```text
docs/pm-continuation-contract.md (new)
docs/pm-continuation-verification.md (new)
docs/runtime-assignment-contract.md
docs/architecture.md
README.md
```
