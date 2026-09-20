# Project Workflow README Evidence Plan

> **Status 2026-09-18:** active Base README migration wave. Scope is README curation, neutral browser evidence and an existing documentation-regression gate; it does not change task, Supervisor, API or database behavior.

## Evidence Decision

- Keep the repository-local banner: it is the established product identity.
- Use `namespaces.png` because its fixture shows only generic namespace configuration and neutral UI-testing copy, without credentials, task keys, URLs or runtime paths.
- Capture `mobile-namespaces.png` from a freshly prepared isolated SQLite smoke fixture at `390x844`; it proves the namespace editor's single-column mobile layout without publishing the task dashboard's task keys, backlog titles, verdict counts or blocked work.
- Keep the full screenshot collection outside root README; `docs/quality-gate.md` documents how it is generated and verified.

## Execution

1. Replace the root README's exhaustive screenshot gallery with source-verified overview, boundaries, local launch and quality information.
2. Extend `tests/test_docs_quality.py` so the existing CI quality job validates the root README anchors, reviewed evidence and no local-path/placeholder leaks.
3. Capture and inspect the mobile namespace page through an isolated fixture only.
4. Run documentation tests, full project quality gates, Compose health and hosted CI before publishing to `master`.

## References

- [README](../../README.md) — current curated evidence.
- [Quality Gate](../quality-gate.md) — screenshot capture and verification.
- [Architecture](../architecture.md) — product boundaries.
