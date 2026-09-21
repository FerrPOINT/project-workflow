# UI Shell Contract

`project-workflow` is server-rendered, but follows the Base [UI Shell
Standard](https://github.com/FerrPOINT/services-base/blob/main/docs/platform/UI_SHELL_STANDARD.md).
The implementation keeps the shared 264 px/72 px left sidebar, 60 px header
and full-width right work area across authenticated routes. Jinja templates must
preserve this DOM and behavior contract rather than create route-local shell
variants or project-local content-width classes.

## Page Geometry

- Dashboard, tasks, workflows, phases, instructions and agents use `wide`.
  Tables, lists and timelines use `minmax(0, 1fr)`; technical horizontal
  scrolling remains local to its data container.
- Namespace, workflow, phase and agent editors use `reading/form`: only the
  inner form column is bounded to 760 px. It never constrains task lists,
  dashboards or phase timelines.
- Task/phase details use `detail-with-aside`: a fluid primary column plus a
  320 px contextual rail; supporting content moves below it before document
  overflow.
- Every page keeps `main` and page containers shrinkable (`min-width: 0`).
  No route may widen `body` beyond the viewport.

## Navigation And Header

- Desktop uses the same expanded sidebar order, active route state and global
  context on every private route.
- The mobile drawer is the same navigation, not a second route menu. It opens
  from the header, traps focus, closes with Escape and restores trigger focus.
- Theme, services, namespace selection and logout are global header/drawer
  controls. Route title, breadcrumbs, filters and CRUD actions are page-owned
  content below the header; page actions must not make the global header wrap.
- At narrow widths actions move to a labelled local row below the page header.

## Evidence

Any shell, header, sidebar or content-geometry change is verified in a real
browser at 375, 1440 and 2560 px. Evidence covers direct-route active navigation,
mobile drawer keyboard behavior, one intended header row, no document-level
overflow, and the page-appropriate content width. Themes remain consistent with
the active namespace contrast contract.

## References

- [Architecture](architecture.md) — UI ownership and selected namespace context.
- [Quality Gate](quality-gate.md) — browser smoke commands.
- [Base UI Shell Standard](https://github.com/FerrPOINT/services-base/blob/main/docs/platform/UI_SHELL_STANDARD.md) — fleet contract.
