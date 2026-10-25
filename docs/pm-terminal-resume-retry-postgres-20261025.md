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

## Still Open

This does not qualify an actual installed0015 database copy, all repository
gates, deployment, Fleet transactional/consumer recovery or live CLI/model work. FLEETQA-3
still requires useful PM dialogue, requirements and genuine owner confirmation
before Backlog/Ready. No Analysis or Analyst acceptance is implied.
