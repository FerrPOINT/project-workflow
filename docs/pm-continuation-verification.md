# PM Continuation Verification

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
