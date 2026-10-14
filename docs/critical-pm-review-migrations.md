# Critical PM Review And Legacy Metadata

## Implemented Source

The single unreleased `0015_single_task_assignments` migration supports subsequent
PM executions for the same Tracker task/concrete agent. Existing namespace locks
and the actual prior Workflow/native terminal checks remain required. Original
PM executions, operation replay and history are not rewritten or resumed as new
assignments. Released migrations0001-0014 are unchanged.

Read-only inspection of the accepted database found head `0001_initial`, seven
legacy agent records and nineteen non-NULL phase-agent links. Released0013 removes
those legacy columns/tables, so an empty-agent fixture is not sufficient evidence
for that upgrade.

The existing `ensure_migrated` entrypoint now retains exact legacy values in
`legacy_agent_metadata` and `legacy_phase_agent_links` before executing the released
chain. Both archives share the existing initialization transaction; a failure
rolls back the archives and migration changes together. Source/archived joins are
checked without exporting row contents. Existing partial, foreign, changed or
unguarded archives fail without repair/overwrite. Only the validated archive pair
is excluded from ordinary runtime table comparison. Fresh databases need no
archives; already-lost metadata is not manufactured.

Use the supported migration entrypoint, not raw Alembic that bypasses preservation:

```python
from project_workflow.infrastructure.db.session import (
    ensure_migrated,
    get_engine,
    initialization_transaction,
)

with initialization_transaction(get_engine()) as connection:
    ensure_migrated(connection)
```

This is a migration-only example, not an installation command executed against
the accepted stand. Profile/catalog adoption and pinned images remain separate.

## Qualification Boundary

Source packet29c1a58 passes78 affected SQLite/HTTP cases, scoped Ruff and mypy.
Cases include populated seven-agent/nineteen-link preservation, restart, readonly
guards, refusal of foreign/partial metadata and rollback after released0013 has
actually removed its source objects inside the transaction. SQLAlchemy/application
files retain those exact source bytes after integration and upstream UI merging.

Nine PostgreSQL cases passed against immutable source
`49a5fa9ada90a868ad00b70b559f13efd7495862`: **9 passed, zero failures,
errors or skips**. The [qualification record](critical-pm-preservation-postgres-20261015.md)
lists the exact selected cases, source/toolchain seals and verified cleanup.
The cases cover populated preservation, transactional rollback, archive guards
and refusal of foreign/partial/changed metadata. They were selected individually;
the equivalent bounded selector is:

```text
pytest tests/test_postgres_integration.py -m integration -k 'legacy_agent_archives or legacy_archive' --timeout=120 -p no:cacheprovider
```

This qualifies the selected PostgreSQL preservation behaviors on synthetic
populated data, not an upgrade of the accepted database. Populated accepted-data
upgrade, whole-repo gates and live subsequent-PM execution remain unqualified. Earlier b7 companion
image/provenance results do not qualify this new migration/preservation source.
Neither accepted stand nor its data/images have been changed by this packet.
