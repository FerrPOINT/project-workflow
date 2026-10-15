# Installed Workflow Predecessor: 16 October

An actual read-only inspection of sdlc1 completed through the existing Base
maintenance helper, using qualified abe4 Workflow image371c and Base dd194.
No service was stopped, no migration/catalog initialization ran, and accepted
images, configuration and database rows were not changed by the inspection.

PostgreSQL confirmed `transaction_read_only=on`, `REPEATABLE READ`. Observed
revision is `0001_initial`; target0015 is not an installed-schema claim.
The sole default workflow has ID1. All nine legacy tables exist.

| Existing data | Rows |
| --- | ---: |
| Workflows | 1 |
| Projects | 1 |
| Phases | 19 |
| Phase instructions | 23 |
| Phase checks | 59 |
| Phase evidence requirements | 37 |
| Tasks | 0 |
| Step history | 0 |
| Phase events | 0 |

Default row SHA256:
`78298a076babc957b48d8e77e48b272e1ff6ceff6b6eed55334d8ea49da7e109`.
The private retained receipt records per-table row hashes, not row bodies,
prompts, credentials or connection details. It is an MVCC observation, not a
backup or guarantee that a later maintenance-window snapshot is unchanged.

Payload SHA256:
`e2f00e621d3c9ebfa06c47b1c4f4c0dfd6c40aa0e3bf2d87cf1ef1bf1dbe6bdc`.
Helper project `sdlc-qa-install-66f34820d306` has v2 journal phase cleaned;
journal SHA256 `30f589942f2d52a704799ebed6fccb4c77547c7792a7a2dc306eb3a0f1bb78a8`.
Fresh Docker readback finds zero helper containers and zero helper networks.

The new typed image-build instructions are a separate source cohort. Do not
relabel the earlier image, old catalog hashes or this predecessor receipt as
qualification of that successor. Its generated fixtures, populated migration,
image provenance, explicit family installation and authenticated server readbacks
remain required before seven-agent live activation.
