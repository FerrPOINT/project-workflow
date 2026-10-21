# Runtime-call catalog validation reuse

Baseline f33b6e0d73b1e974de2ba4d41d28f0ad8cbb8e1a, atop master f73f2b2.
No migration, manifest, lock, API signature, Hermes or installed-state change.
This followup is local source; Main owns PG admission and Build/Apply.

## Actual evidence and correction

The unchanged f33 instrumented PG retained-unbound case passed (69.630s),
not a full18 qualification. Protocol66.309s/CPU48.709s,19990 SELECT.
Last step4446 SELECT/18.562s; terminal read1427 SELECT/7.356s.
Own Python cgroup throttled0.016710s,peak218640384 of2147483648 bytes;
no sampled PG blockers. Previous failed120 cause remains unproved.

Host probe of the existing retained-unbound terminal test measured167 observe
calls. Last step37 calls,4487 SQL,1147 relationship loads; terminal read12 calls,
1437 SQL. Whole host scenario20874 SQL. This is a separate SQLite test, not PG.

## Source change

- Explicit runtime_catalog_read scope on existing runtime/PM bridge UoWs only.
- First observation still takes the same schema-scoped shared advisory lock,
  refreshes, verifies every profession and matches one complete sealed family.
- Only that installation result is reused in the same Session transaction and
  savepoint. Returned objects are independent deep copies. Assignment, current
  run, permission, token, native proof, scope and fence checks still execute.
- Scope exits unconditionally; commit/rollback/savepoint boundaries require
  another fresh validation. Real intermediate Supervisor commits remain.
- ORM/Core/direct Connection catalog writes invalidate; opaque SQL (including
  driver SQL), embedded text and writable CTEs invalidate conservatively.
  Pending catalog ORM changes also prevent reuse. Other normal task writes
  do not invalidate an unchanged catalog. Outside this explicit scope the old
  observe_installation behavior is unchanged, including same-UoW drift tests.
- Existing catalog lock uses a structured SELECT with the exact same
  current_database() || ':' || schema hash,seed0 and shared/exclusive functions.
  No lock removal, TTL, cross-call cache or global memoization.

## Host regression and measured followup

49 focused tests PASS (60.55s): new23 scope cases plus existing16 batching and10
retained compatibility cases. Final query-ceiling assertion on the retained
terminal test was rerun separately after adding counters; result reported in
the terminal handoff. Full mypy142 source files PASS; full Ruff and diff checks
PASS. No new full-host/cov gate: earlier f33 host timeout evidence is retained.

Same instrumented host case after source changes: PASS,5643 SQL versus20874.
Last step733 SQL/CPU0.719s versus4487/3.516s; terminal read187 SQL/CPU0.203s versus
1437/1.016s. Last step has8 fresh validations because intermediate transactions
cannot share authority; terminal read has1. Regression requires distinct
transaction identities,<=800 SQL per step and<=200 for terminal read.

Whole host wall time was33.48s versus23.09s, with isolated low-CPU pauses in
bind/rebind. Thus no overall wall-time improvement, PG timeout fix or external
network cause is claimed. CPU/SQL metrics are inclusive, not additive.

Private probe files remain in existing workflow-bootstrap-current-pg-qa packet:
host-f33-observe-count.json SHA778710431d5bbc0e03f897a5269b1f39809ba57ae0fc42bd1188a1343081ba36;
host-scoped-observe-count.json SHAb7aa70bf48fc8fff538e49e2d6c21d68583ea584f54c6d494853886605732387.

Next Main-controlled PG check: the existing failed retained-unbound exact case
on this committed source with existing telemetry/timeout120, not a blind full18
rerun. PostgreSQL advisory-lock execution and real wall-time remain UNRUN for
this followup; host dialect compilation only verifies the lock expression.
