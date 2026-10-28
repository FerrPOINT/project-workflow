# UI Shell Contract

`project-workflow` is server-rendered, but follows the Base [UI Shell
Standard](https://github.com/FerrPOINT/services-base/blob/main/docs/platform/UI_SHELL_STANDARD.md).
The implementation keeps the shared 264 px/72 px left sidebar, 60 px header
and full-width right work area across authenticated routes. Jinja templates must
preserve this DOM and behavior contract rather than create route-local shell
variants or project-local content-width classes.

**Implementation status (2026-10-09):** the global header uses the Base slot
order: product mark and service switcher on the left, namespace/workflow
context beside account on the right. The selector changes namespace context;
the workflow label describes its existing binding and never changes that binding.
Page titles and local actions are below it. Theme selection lives in the account
menu. Mobile namespace selection remains in the navigation drawer.

The browser theme runtime and SSR account primitives are exported from the exact
Base UI commit in `.base-ui-revision`; `templates/base/fingerprint.json` attests
the generated assets. The same preference script is consumed by React products.
`sdlc-ui-theme` is a host-only browser preference, not account data; Cookie Store
events synchronize open documents and focus/visibility refreshes restore it.

## Page Geometry

В текущем source-кандидате общий заголовок использует base-page-title, заголовки
разделов dashboard и истории — section_header. Heading IDs и связи aria-labelledby
сохраняются. Ссылки dashboard используют text_link с прежними namespace-aware URL;
пустые секции — state. Ссылка со знаком платформы использует button(href=...)
с native anchor, доступным именем и icon hit target; локальный brand-link CSS удалён.

Shared page-frame/page-wide/page-detail/page-readable/page-split declarations
are consumed from the Base stylesheet. The product does not repeat them in
base.html. Retired brand-text/header-actions/theme-select/namespace-icon-action,
phase-detail-header and tabs/tab skins have no active source references and are
removed. Timeline/phase execution rules remain product-owned. This cleanup keeps
the template markup, navigation and scripts unchanged; generated assets and
installed runtime acceptance remain separate gates.

- Dashboard, tasks, workflows, phases, instructions and the CLI reference use `wide`.
  CLI command cards fill that work area through the shared Base page stack;
  the reference is structured operational UI, not a bounded reading column.
  Tables, lists and timelines use `minmax(0, 1fr)`; technical horizontal
  scrolling remains local to its data container.
- Profession, workflow and phase editors use `reading/form`: only the
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
- Base SSR scope owns sidebar sizing: 72px with accessible hidden labels on
  768–1279px, 264px with visible labels from 1280px. Text and icons use the
  shared 14px/20px rhythm; hidden labels never leave an expanded-width rail.
- The mobile drawer is the same navigation, not a second route menu. It opens
  from the header, traps focus, closes with Escape and restores trigger focus.
- Mobile service popover is bounded by viewport gutters; desktop and drawer
  namespace selectors share the selected namespace and refresh their options
  together after edits, browser history and reload.
- Services, namespace context and account are global header/drawer controls.
  Theme and logout live only in the account menu. Route title, breadcrumbs, filters and CRUD actions are page-owned
  content below the header; page actions must not make the global header wrap.
- At narrow widths actions move to a labelled local row below the page header.

## Evidence

The native service catalog includes the current Workflow record and preserves
its runtime health. A failed, empty or invalid catalog returns the six-entry
unknown-health fallback, never expired health presented as current. Cache entries
are scoped to the catalog URL. API-only entries have `ui_url=null` and are not
navigation targets. The compatibility `load_other_services` helper still omits
Workflow; the UI uses the full `load_service_catalog` result.

The [catalog regression evidence](assets/screens/2026-10-01-service-catalog/README.md)
covers runtime and real network refusal. This narrow correction does not replace
the native header/sidebar with the shared Base SSR Header or accept full SSO and
page geometry. Those integration gates remain separate.

Any shell, header, sidebar or content-geometry change is verified in a real
browser at 375, 1440 and 2560 px. Evidence covers direct-route active navigation,
mobile drawer keyboard behavior, one intended header row, no document-level
overflow, and the page-appropriate content width. Themes remain consistent with
the active namespace contrast contract.

## References

- [Architecture](architecture.md) — UI ownership and selected namespace context.
- [Quality Gate](quality-gate.md) — browser smoke commands.
- [Base UI Shell Standard](https://github.com/FerrPOINT/services-base/blob/main/docs/platform/UI_SHELL_STANDARD.md) — fleet contract.

## Показатели dashboard

Dashboard использует общий `metric` из штатного SSR export Base. Существующие
подсчёты и подписи не переносятся в UI-библиотеку. Вердикты преобразует Workflow:
blocked → danger, rollback → warning, delegate → info, остальные → default.
Идентификатор/имя вердикта не определяет общее поведение Base; новые вердикты
сохраняют своё значение и читаемую подпись без подстановки другого статуса.
Нулевое значение остаётся нулём. Внешняя dashboard-grid остаётся продуктовой,
а локальные metric-card/label/value/verdict skins удалены.

Оформление state и кнопки/ссылки повтора совпадает с React через канонические
tokens Base. Проверять полный SSR export вместе с legacy adapter, а не отдельный
фрагмент stylesheet. Потеря доступа и ошибка не показывают прежние закрытые
показатели; read_state и разрешённый retry_url выбирает владелец данных.


## Incremental workflow editor

The initial `/workflows` request renders the shell and editor. Subsequent workflow,
mode and phase updates request the same scoped owner route with
`X-Workflow-View: editor-v1`. It returns only the editor with the same marker,
`Cache-Control: private, no-store` and `Vary: X-Workflow-View`. Full and fragment
views use the same context, Jinja macros and server-side grouping. Error,
redirect and unsupported-version responses cannot be installed as fragments.
This is a product view protocol, not a replacement for the existing JSON APIs.

The shell, admission renewal and leave guard stay mounted. The fragment contains
only inert JSON state and existing UI markup; scripts are never evaluated. A late
read cannot replace a newer selection or resurrect content after admission
retirement. Mode/phase refresh preserves the workflow form. Changing workflow
requires confirmation for dirty input; edits made while loading also prevent
replacement. History traversal restores the matching owner view; cancellation
undoes traversal rather than overwriting another entry. Embedded routing keeps
using the Base navigation bridge.

Writes continue through existing APIs. Phase mutations are serialized. If a
write may have succeeded but the UI cannot read its result, further writes are
blocked and the visible action retries only the owner read. This does not add
backend idempotency to legacy write endpoints. A transport failure before a
workflow-create acknowledgement still has an unknown outcome and must not be
resolved by automatically repeating creation.

Manual integration gate (no production/dev data; dependencies are reused):

```sh
python scripts/serve_workflow_incremental_fixture.py \
  --data-dir /path/to/new-disposable-fixture --port 18418
# In another terminal, with the existing qualified tooling package:
node scripts/check_workflow_incremental.mjs \
  --tooling-from /path/to/base-modules/ui --fixture-url http://127.0.0.1:18418
```

The fixture binds loopback, selects a fresh SQLite database, disables external
Auth and refuses an existing fixture DB. The integration command requires its
explicit fixture marker. `--tooling-from` resolves the existing jsdom package;
it does not install dependencies. Browser acceptance remains a separate IAB gate.
## Persistent application shell

All ordinary owner routes use `X-Workflow-View: page-v1`: dashboard, professions,
creation, workflows, phase detail, instructions, tasks/details and CLI reference.
The server renders the same `Base.app_main` and owner context. Header/sidebar,
Base SDK, branding and original admission clock are installed once. Page controllers
are scoped factories: explicit event callbacks are exported, window/document
listeners use an AbortController, and timers/observers/drafts are disposed before
replacement. Incoming controllers mount only after the swap settles and the old
main is removed; synchronous inline scripts must not initialize outgoing controls. Base menus and other controls use their public init/destroy APIs.

The pinned, unmodified htmx 2.0.11 runtime is served locally from `ui-assets`.
It handles HTML swapping and controller script installation. It does not own
history, request authorization or forms: the existing Base bridge owns routes,
the owner still checks every request, and write endpoints remain unchanged.
htmx history/storage caching is disabled. Session/access changes retire the
protected document; login/logout and other applications retain their explicit
navigation boundary. Before fetching, confirmed navigation commits the target URL, sidebar, heading
and a Base loading work area. Previous page data and controller callbacks are
disposed at that boundary. A failed read keeps the target route with Base error
and an explicit read retry; superseded responses cannot change a newer route.
Dirty cancellation preserves the original form and URL. Pending writes
block a departure; acknowledged writes can request a work-area readback.

Run `scripts/check_workflow_application.mjs` with the same `--tooling-from` and
`--fixture-url` arguments for whole-app routes, repeated lifecycles, history,
creation, failed/stale reads and access retirement. Both manual integration gates
are separate from default build/check. IAB acceptance must traverse every sidebar
section on the final installed artifact; editor-only proof is insufficient.


## Fast navigation and immutable controllers

Ordinary page reads still use the same protected owner route and private,
no-store HTML. Fragments do not read the service catalog for a header they do not
replace. Authorization, view data, identity and original admission deadlines are
checked as before; protected HTML is not put in browser history or a shared cache.

Request-independent controller templates live in `templates/controllers/`.
The existing Jinja engine produces a fixed user/admin code variant, addressed by
SHA256. Only code and public icon constants enter these immutable responses.
Private page configuration is an inert JSON block in the owner HTML. The four
controllers load once with deferred scripts before initial page mounting; later
page reads carry only a small bootstrap and data. No new build tool or dependency
is required. The existing scoped mount/dispose contract remains authoritative.

An already-open inline-controller shell upgrades once by document navigation.
A shell-code fingerprint or asset-set change also upgrades the document after current authorization is
confirmed. Ordinary navigation on a compatible shell remains partial. A failed
asset load shows an error and does not enter an automatic reload loop.

Pending reads render inert templates composed with the public Base `app_main`,
`page_header` and `state` macros. Route descriptors supply only generic headings
and layouts; names and records arrive from the owner. No toast, old-page overlay,
HTML history cache, background polling or second router is used. Loading and
error states remove outgoing data. After a successful read, owner metadata and
page controllers replace the loading area, keeping the persistent shell intact.
The manual gate deliberately holds the data response unresolved and checks the
new URL, selection, heading and loading state before releasing it. It also checks
failure/retry, cancelled departure, stale reads, history and admission retirement.
The child workflow editor keeps its independent form-preserving/late-edit guard.
