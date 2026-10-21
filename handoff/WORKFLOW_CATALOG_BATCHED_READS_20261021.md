# Managed catalog content batching

Checkout: `C:/git/azhukov/sdlc/.local/single-task-sdlc-20261013/workflow-catalog-batched-reads-20261021`
Branch: `fix/catalog-batched-reads-current-20261021`.
Parent: current GitHub master `f73f2b2ffff4ce1cbb127410e7851d39ed143e22`.
Initial investigation/test baseline: `8e27ac52cfeb82908d6b7911bcc102d9a295e488`.
PR137 is merged; do not push to its old branch. No PR created or remote push performed.

## Change

Only `managed_catalog._assert_existing_workflow` changes production behavior:
reuse existing repository `list_for_phases` for instructions/checks/evidence,
across all modes of one workflow, on the existing UOW/session/connection.
Three ordered SQL read sets replace three reads per phase. The editable managed
branch still checks only instructions/skills, as before. No cache, TTL, new
repository API, migrations, timeout changes, commits/rollback, or lock changes.
All mode/phase/identity/content/skill/order comparisons remain in place.

## Actual Host Evidence

On 8e27, the new query-count test was RED for both current and retained families:
Developer has two modes/six phases, and each content table was read six times
(18 SQL total). With the patch each table is read once (3 SQL total).
The test instruments actual SQLAlchemy reads and repository methods, checks the
same connection/session, compares each ordered batch with the original per-phase
results, and verifies unchanged persisted rows. This is per workflow, not three
queries for the entire catalog.

Final f73-based source, host Python:

```text
python -B -m pytest -q tests/test_catalog_batched_reads.py --timeout=60
16 passed, 0 failed/errors/skipped, 11.52s
python -B -m mypy project_workflow/infrastructure/db/managed_catalog.py --follow-imports=silent
Success: no issues found in 1 source file
python -B -m ruff check project_workflow/infrastructure/db/managed_catalog.py tests/test_catalog_batched_reads.py
All checks passed!
git diff --check
PASS
```

Python: existing `C:/git/azhukov/sdlc/project-workflow/.venv/Scripts/python.exe`;
PYTHONPATH is this checkout, PYTHONDONTWRITEBYTECODE=1. Synthetic SQLite only.
Four test functions, parametrized to 16 cases: fixed SQL sets/ordered equivalence;
missing and reordered instructions/checks/evidence; next-UOW committed drift.
Each runs against current and retained families.

Additionally, before the master sync: existing managed_catalog,
managed_catalog_hardening, managed_catalog_editing, single_task_installation and
single_task_profile_compatibility modules: 136 PASS on the patched 8e27 source.
That is not a fresh 136-case gate on f73 (which also changes UI/config).
The affected DB/application/terminal source is byte-identical between those bases.

## Remaining

No PostgreSQL, Docker, build, install, API or live runtime actions performed.
No Build/Apply pointer touched. Workflow b5 stays held.
This proves removal of the targeted per-phase SQL amplification, not resolution
of the historical 120-second timeout. Main owns the failed retained-unbound PG
case and ten unrun health cases on the new source, plus final qualification.
