# Base Catalog Adoption

The explicit `ensure_managed_catalog(uow, CANDIDATE_PATH)` source path supports
an append-only transition from canonical managed v2 to the Base v3 candidate.
It does not change the default catalog, install an image, authorize execution,
or provide a public user/API/CLI operation.

## Transaction Boundary

The caller owns the transaction and must roll back an interrupted append before
retrying. The existing schema-scoped catalog lock serializes competing writers.
Before any write, all seven v2 workflows, roles, profiles, namespaces, active
modes, phases, instructions, checks and evidence must match packaged v2.
Missing/mixed/unsupported predecessor versions and partial v3 rows are rejected.
Drift in the final role cannot leave earlier roles changed in the open transaction.

V3 modes and phases are appended with new IDs. Workflow IDs, agent/profile IDs,
namespace IDs and historical mode/phase rows are retained. The current workflow
description and active catalog pointer select the candidate; assignments, task
cursors, reports, events and all frozen input/compatibility fields are untouched.
The active inventory remains 7 workflows / 11 modes / 33 phases; retained v2
rows do not masquerade as additional active workflows. Repeating the operation
does not append another copy.

Catalog validation compares the exact active version as well as semantic content.
A different version with identical mode/phase bodies cannot impersonate v2 or v3.

## Remaining Native Work

This source-level persistence path is not a production installer or admission ACK.
Default startup still selects v2, and immutable image compatibility/build selection
for v3 remains required. Running a default-v2 validator against a v3 installation
fails closed rather than silently downgrading or accepting the wrong catalog.

`require_owner_execution_evidence` remains unconditional: trusted Tracker binding,
Fleet frozen execution/config ACK and Forge receipt lookup are still prerequisites.
Tests exercise persistence and rollback only, not native executor-driven acceptance.
No runtime database, pinned image, public backend contract or migration is changed
by publishing this source. Production rollout must qualify the installed image and
owner protocols, retain protected backups, and use the agreed release procedure.

Regression coverage lives in `tests/base_candidate/test_adoption.py`; actual
PostgreSQL cases cover retained bound/completed history, concurrent idempotent
adoption and rollback/retry after an interrupted append.
