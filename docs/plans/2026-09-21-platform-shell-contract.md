# Platform Shell Contract Implementation Plan

**Status:** completed.

**Goal:** align the server-rendered Project Workflow shell with its documented
60/72/264 px platform contract without changing route behavior or domain APIs.

## Scope

1. Keep a 264 px expanded sidebar on desktop and a 72 px icon rail on tablet.
2. Use the focus-trapped drawer only below 768 px and expose dialog semantics
   while it is in mobile mode.
3. Keep the global header at 60 px on tablet and desktop; route actions remain
   page-owned at constrained widths.
4. Preserve namespace, service, theme and logout access at every breakpoint.
5. Pin geometry, accessibility and responsive behavior with regression tests
   and browser evidence in all three themes.

## Result

- The shared Jinja shell now implements 60/72/264 px geometry and reserves the
  focus-trapped drawer for viewports below 768 px.
- Navigation labels remain accessible in the tablet rail; mobile controls meet
  the 40/44 px target contract and expose dialog semantics.
- Browser QA covered six routes, four viewport widths and three themes: 72/72
  page states had no overflow, shell target, label or runtime errors; all three
  drawer keyboard scenarios passed.
- Local verification: 1484 tests, 94.26% coverage, ruff and mypy. PostgreSQL
  integration and Compose readiness remain required CI gates because the local
  Docker CLI stalled while the default PostgreSQL port was already occupied.
- Evidence: `docs/assets/screens/2026-09-21-platform-shell/`.
