# Legacy metadata preservation: PostgreSQL qualification

## Result and Scope

The nine existing PostgreSQL preservation cases passed against immutable Workflow
source `49a5fa9ada90a868ad00b70b559f13efd7495862` (tree
`7d9e56504d7677335ef385bc0fda5aa28ec80e81`): **9 passed, 0 failed, 0 errors,
0 skipped**, in **15.498 seconds**. JUnit records suite start
`2026-10-14T21:44:19.524512+00:00`. One Starlette/AnyIO alias deprecation warning
was reported; it did not change the result.

This qualifies synthetic populated-legacy preservation through the existing
initializer on PostgreSQL. It does **not** establish an upgrade of the accepted
database, installation or catalog adoption, model execution, live PM completion,
runtime/native readiness, full PostgreSQL-suite coverage or full SDLC acceptance.
No accepted database data was used as a test fixture.

## Executed Cases

All node IDs below belong to
[tests/test_postgres_integration.py](../tests/test_postgres_integration.py).
They were selected explicitly, sequentially, with integration marker and timeout
120 seconds; the strict reader required exactly these nine unique cases and zero
skips, rather than accepting process exit alone.

1. `tests/test_postgres_integration.py::test_postgres_legacy_agent_archives_preserve_seven_agents_and_nineteen_links`
2. `tests/test_postgres_integration.py::test_postgres_legacy_archive_and_released_migrations_roll_back_together`
3. `tests/test_postgres_integration.py::test_postgres_legacy_archive_refuses_foreign_partial_or_changed_without_overwrite[partial]`
4. `tests/test_postgres_integration.py::test_postgres_legacy_archive_refuses_foreign_partial_or_changed_without_overwrite[unguarded]`
5. `tests/test_postgres_integration.py::test_postgres_legacy_archive_refuses_foreign_partial_or_changed_without_overwrite[view]`
6. `tests/test_postgres_integration.py::test_postgres_legacy_archive_refuses_foreign_partial_or_changed_without_overwrite[changed_source]`
7. `tests/test_postgres_integration.py::test_postgres_legacy_archive_refuses_foreign_partial_or_changed_without_overwrite[foreign_column]`
8. `tests/test_postgres_integration.py::test_postgres_legacy_archive_refuses_foreign_partial_or_changed_without_overwrite[missing_guard]`
9. `tests/test_postgres_integration.py::test_postgres_legacy_archive_guard_loss_at_head_is_not_readiness`

## Preserved Data and Refusals

The existing [assertion helpers](../tests/test_initial_migration.py) exercised
the [initializer preservation transaction](../project_workflow/infrastructure/db/session.py):

- Actual Alembic creation at `0001_initial`, then normal `ensure_migrated` to
  `0015_single_task_assignments` and repeated initialization. No stamp or
  hand-built head bypassed the released migration chain.
- Seven complete legacy agent rows and nineteen nonnull phase-agent links,
  plus an unassigned phase, retained in `legacy_agent_metadata` and
  `legacy_phase_agent_links`. Archived values and original phase-agent join
  tuples match exactly, including null profile and whitespace/newline values.
- Existing reflected table data, task/history identifiers and required mode
  backfill remain consistent; new authority fields do not fabricate assignment
  or native execution proof. Both archives reject INSERT, UPDATE, DELETE and
  PostgreSQL TRUNCATE.
- An injected failure after released migration 0013 rolls back migration effects
  and archive creation together to the original populated `0001_initial` state.
  Removing the injected failure permits the normal preservation upgrade.
- Partial, unguarded, view-shaped, changed-source, foreign-column and missing-guard
  states are refused without overwriting existing source or archive data.
- Removing an archive guard at head makes readiness false and initialization
  refuse, while retaining head and archived rows; it does not silently repair them.

Released migrations 0001-0014 were not modified by this qualification. Archives
preserve legacy metadata; they are neither a backup substitute nor execution proof.

## Evidence and Isolation

The retained local evidence packet is named `evidence-49a5-rootfix`. Its scoped
`result.json`, `output/source.json`, `output/prepared.json`,
`output/preservation.xml` and Base-v2 `compose/journal.json` were read back without
repeating tests. Important bindings are:

| Binding | Value |
| --- | --- |
| Runner SHA256 | `fce4f87cafe6a22a51424076046dd839e39fb84720a5b2be03ddb04976f1ab9e` |
| Source archive SHA256 | `22c636f495fdef4896b9cc992915127224457b37e99de2cb960e442f972ed650` |
| uv.lock SHA256 | `7b49b6fa06d115a0dc4d3f19e3ed71bfbb9b79453e7ce53457e8d87c1257a481` |
| Prepared inventory SHA256 | `a5e68e448727fc9a544a35ca70789273bd6379c53829e602c60ff482ccd6b8c3` |
| Python / uv | `3.11.16` / `0.10.10` |
| QA toolchain image | `sha256:93f5f005b10f81594dd68077b8cf771cc87bf44e8fde401efd67ef8377f687fb` |
| PostgreSQL image | `sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94` |

PREP used the frozen lock with dev/UI extras, no project installation/build,
lock update or constraints fallback. Its 53 recorded distributions were checked
against exact locked names/versions; uv checks artifact hashes. The frozen runner
rechecked source/environment attestation before the offline test stage. Readback
also verified inventory digest, source seals, case identities and manifest/journal
digest equality; deleted scratch is not claimed to have been independently reread.

Testing used a temporary Base-v2 Compose project with its own PostgreSQL, scratch,
synthetic credentials and internal test network. No accepted database or permanent
stand volumes were mounted. The final result records `cleanup_verified=true` and
`live_acceptance=false`; the original-daemon journal is `cleaned`. Generated inputs
and the synthetic secret are absent. The executing operator additionally verified
zero remaining owned containers. This document's readback did not repeat Docker
queries or tests.

## Earlier Startup Failure

The earlier `evidence-49a5-first` remains a failed proxy-startup attempt under runner
SHA256 `9007f77fe5ce2d7e92f94960bdd6a8350e0593f683335456224bd9b60f0e47b3`.
PREP and PG were not reached, and cleanup was verified. Its missing container
stderr is not reconstructed. Source inspection found global host-parent inference
raising IndexError at shallow container paths; the corrected runner confines it
to host execution and captures bounded private Compose logs before cleanup.
The later nine-case success is a separate result, not a relabeling of that failure.
