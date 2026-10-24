# PM Resume Retry PostgreSQL Evidence

Source: `e4963a78a3fdc1fd49eca7df56291db1aa881b44`.
Base: `2bb386503eeb009e2238160e88970eae0fab2824`.
Python3.11.16, frozen uv lock; seven selected tests pass on actual disposable
PostgreSQL17. Native callback responses are synthetic, not live model evidence.

## Verified

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

## Still Open

This does not qualify an actual installed0015 database copy, all repository
gates, deployment, Fleet consumer recovery or live CLI/model work. FLEETQA-3
still requires useful PM dialogue, requirements and genuine owner confirmation
before Backlog/Ready. No Analysis or Analyst acceptance is implied.
