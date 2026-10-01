# PM Continuation Verification

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
