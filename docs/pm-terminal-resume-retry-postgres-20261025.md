# PM Resume Retry PostgreSQL Evidence

## Historical PG7: e4963a7

Source: `e4963a78a3fdc1fd49eca7df56291db1aa881b44`.
Base: `2bb386503eeb009e2238160e88970eae0fab2824`.
Python3.11.16, frozen uv lock; seven selected tests pass on actual disposable
PostgreSQL17. Native callback responses are synthetic, not live model evidence.

### Verified In The Historical Run

- Populated0018 upgrades through normal `ensure_migrated` to0019, preserving
  all retained rows. Repeated up is idempotent. Down/up works before a retry;
  retained retry receipts prevent downgrade without deleting history.
- Retry, restart and original-key readback preserve the distinct receipt.
- A bootstrap child's canonical identity survives terminal-resume retry.
- Concurrent identical keys produce one receipt/callback. Competing target
  commands produce one winner. The tests observe actual PostgreSQL lock waits
  through fresh monitoring transactions, not only sequential HTTP results.
- Fresh schema matches ORM metadata; concurrent initialization is idempotent.

Actual result: **7 passed,0 failed,0 skipped**,37.43seconds. One third-party
Starlette/AnyIO deprecation warning is retained in the test output.

ComposeHelper v2 uses a separate temporary project, private PostgreSQL without
published ports, source exported from the exact Git commit and pinned Base CLI.
All source/environment hashes remain unchanged. Disposable volumes/containers,
exported inputs and the generated database password are removed in finally;
runtime services, history, backups and external caches are untouched.

Result SHA256:
`1b7ecfba17f61527561d027e2a267093e32d2ef7b7c2d7be6f694239cb33a058`.
JUnit SHA256:
`af5c33eab9a13c1a8eff0610223b910cfa1691995c9957f1e05cf10abadf7836`.

## Inherited Checkpoint PG7: 6c98e83

Source: `6c98e83cda049303fed02ef42342e1284ad810e2`.
Tree: `cc85ec2469d3de38987f5cb9b2b492e57227aa41`.
Base remains `2bb386503eeb009e2238160e88970eae0fab2824`.
Saved evidence directory:
`.local/single-task-sdlc-20261013/workflow-pm-retry-pg-qa-20261025/run-6c98e83-a06`.

The inherited-checkpoint producer follow-up accepts a failed observation with
either null or the exact retained source marker, without rewriting the received
proof. The seven-case result above predates that change and remains historical.
This separate actual PostgreSQL run contains the populated0018 upgrade case
plus six affected cases in `tests/test_postgres_pm_resume_retry.py`: the existing
replay and canonical-bootstrap tests plus:

- `test_retry_preserves_failed_terminal_checkpoint_marker_on_postgres[absent]`
- `test_retry_preserves_failed_terminal_checkpoint_marker_on_postgres[inherited-source]`
- `test_retry_rejects_foreign_checkpoint_marker_on_postgres`
- `test_retry_rejects_genuine_rebound_pm_run_on_postgres`

Actual result: **7 passed,0 failed,0 skipped**,47.35seconds in `output/tests.log`
(JUnit47.348seconds). `result.json` records `passed=true`,
`cleanup_verified=true`, `input_cleanup_verified=true`, `live_acceptance=false`.
`output/preservation.xml` independently records seven cases with no failures,
errors or skips. This scope does not rerun the earlier concurrency/fresh-init
cases. It reuses disposable-PG fixtures and synthetic native callbacks; no live
runtime or source checkpoint is modified to obtain evidence.

Result SHA256:
`c44423867ffd46ec4905446a35afd03c5a2a2f64bea1d3c301ec048b7efd68b9`.
JUnit SHA256:
`817013027ea08eb5a88d41ea90779ab44dbb2379c2d60a9410e53d1ec9f2a9e1`.

Focused SQLite/TestClient validation of the follow-up: **15 passed**, including
single-observation/raw replay, both allowed markers, scoped-field mismatches,
genuine rebind refusal, unknown callbacks and canonical bootstrap identity.

## Full Retry Module And Adjacent Host Cases

On documentation head `04f400bf7453bd4cb281ecb91efec0114dd1e313`, production and
test files remain identical to `6c98e83`. The prepared Python3.13.13 host venv
ran the entire `tests/test_pm_resume_retry.py`: **39 passed**. Eleven adjacent
network-readback, native-ref/terminal and current-run scope cases also passed:
**50 passed,0 failed,0 errors,0 skipped**,102.19seconds. One third-party
Starlette/AnyIO deprecation warning remains. This is host SQLite/TestClient
evidence, not an additional PostgreSQL run.

Saved evidence directory:
`.local/single-task-sdlc-20261013/workflow-pm-retry-host-checks-20261025/run-04f400b-a01`.
`command.json` records the exact interpreter, arguments and four adjacent test
selectors; `pytest.xml` separates39 retry,7 execution and4 execution-edge cases.
Scoped checks also passed:

```text
ruff check project_workflow/application/pm_resume_retry.py tests/test_pm_resume_retry.py tests/test_postgres_pm_resume_retry.py
python -B -m mypy --follow-imports=silent project_workflow/application/pm_resume_retry.py
git diff --check
```

Host result SHA256:
`8ec0f0808451bf570d20afd07faa8db535233069a21fc6321894c3e616329d21`.
JUnit SHA256:
`5e25f53bb6f3040c740793e8457fde43546a6a6f6f2fa8b6a4521f138a7b5350`.

## Actual0015 Copy: Migration-Only Entry Point

Source remains `6c98e83cda049303fed02ef42342e1284ad810e2`. A genuine retained
installed0015 dump was restored only into disposable PostgreSQL. Saved evidence:
`.local/single-task-sdlc-20261013/workflow-pm-copy-qualification-20261025/run-6c98e83cda04-3394b62d1e/evidence`.
The existing migration-only entry point ran twice, both with exit0:

```text
python -B -c "from project_workflow.infrastructure.db.session import ensure_migrated; ensure_migrated()"
```

The head advances to `0019_pm_terminal_resume_retry`. All20 existing tables
remain present; old columns/rows are unchanged except the intended Alembic head
update. Exactly four identity tables are added: `identity_owner_command_authorizations`,
`identity_legacy_issuer`, `identity_fence_epoch`, `identity_deletion_operations`.
Only the fence singleton has initial data (`singleton=1,revision=1`); the other
three are empty. Catalog and PM execution/history family hashes are unchanged.
The second migration call changes no table data. The public health handler
returns200 with database/schema/catalog `ok` and changes no rows; this is a
direct handler check, **not authenticated HTTP/Auth or PM endpoint acceptance**.

`copy-result.json` records `passed=true`, `prior_rows_unchanged=true`,
`replay_unchanged=true`, and unchanged source/environment inputs. Only after the
outer run completed did `result.json` confirm `phase=complete`, `passed=true`,
`cleanup_verified=true`, `input_cleanup_verified=true`, `stand_modified=false`,
and `live_acceptance=false`.

Outer result SHA256:
`228f4dd1501858d804d4d55b012b4596e7e3255b89ff657aeb87207cd8f9df58`.
Inner copy result SHA256:
`d84270691b2ad1f401677d7a3c3a29489d1fef0f0144748f757e8f502f698602`.

Use `ensure_migrated()` for this populated-history boundary, not `init_db()`:
the latter also seeds data and added seven legacy professions in the earlier
failed copy attempts. Those failures remain failures and are not waived by this
migration-only PASS. No new controller or replacement initialization path is added.

## Still Open

The actual0015 copy is qualified only for migration-only preservation and the
direct health handler above. Full repository gates, normal image packaging,
installation, authenticated retained PM readback/history HTTP, Fleet
transactional/consumer recovery and live CLI/model work remain open. FLEETQA-3
still requires useful PM dialogue, requirements and genuine owner confirmation
before Backlog/Ready. No Analysis or Analyst acceptance is implied.
