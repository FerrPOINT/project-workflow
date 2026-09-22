# Project Workflow README Evidence Plan

> **Status 2026-09-22:** historical record of the initial README migration. The active Base contract is desktop-only; responsive browser checks remain UI QA and do not generate README evidence.

## Evidence Decision

- Keep the repository-local banner: it is the established product identity.
- Use `namespaces.png` because its fixture shows only generic namespace configuration and neutral UI-testing copy, without credentials, task keys, URLs or runtime paths.
- Keep narrow-viewport checks in browser/UI tests; do not capture them into the README evidence set.
- Keep the full screenshot collection outside root README; `docs/quality-gate.md` documents how it is generated and verified.

## Execution

1. Replace the root README's exhaustive screenshot gallery with source-verified overview, boundaries, local launch and quality information.
2. Extend `tests/test_docs_quality.py` so the existing CI quality job validates the root README anchors, reviewed evidence and no local-path/placeholder leaks.
3. Capture and inspect only desktop product surfaces through an isolated fixture.
4. Run documentation tests, full project quality gates, Compose health and hosted CI before publishing to `master`.

## References

- [README](../../README.md) — current curated evidence.
- [Quality Gate](../quality-gate.md) — screenshot capture and verification.
- [Architecture](../architecture.md) — product boundaries.
