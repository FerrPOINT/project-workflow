# Runtime-call catalog validation reuse

Baseline f33b6e0d73b1e974de2ba4d41d28f0ad8cbb8e1a, atop master f73f2b2.
No migration, manifest, lock, API signature, Hermes or installed-state change.
Published as Draft PR141; Main owns PG admission and Build/Apply.

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

## Actual PostgreSQL followup

Main executed immutable7e7b78ce3907d5d1a469bb7bce326717e66052d0,
treeb664be20a5cf6259527c190a260d1341b05379cb (exact checked488 tree).
Retained-unbound pilot PASS1/0skip: protocol17.337s/CPU11.470s,5683 SELECT;
last step725 SELECT/1.623s and terminal read187 SELECT/0.596s. Baseline f33
protocol66.309s/19990 SELECT remains separate, not relabelled as this proof.

Subsequent affected full gate PASS18/0skip in138.243s: bootstrap6 +retained2
+health10, original assertions/timeout120 and real PostgreSQL. Actual OpenAPI
export checks and PM consumer byte parity passed; v2 cleanup/input cleanup true.
Evidence workflow-bootstrap-current-pg-qa-20261021/evidence-7e7b78ce-full18-a01;
result SHA256 de8d6092014871740d9992aea2e27a1f16c43ef4fb4675753e75b25db9f55d9a.
Runner SHA256 0a8df34dc5eba81686d0dccf5bf35a9489500e2158eaa2ba033445208879767d.

This is scoped PG qualification, not live acceptance or a full host-suite pass.
The separate host critical-review history case still times out at60s; cause is
unresolved. No all3105/coverage success, install, model or Kubernetes proof is
claimed. This evidence-only followup changes no production/test bytes; the
Build clone and runner stay at the actual qualified7e source.
