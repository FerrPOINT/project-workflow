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


## Phase and instruction card actions

`workflow-cards.html` renders the same five public Base icon buttons for phase
and instruction cards: add after, move up, move down, parallel mode and delete.
The icon, variant, order, size and tooltip contract have one source. Products
supply labels, permission and disabled state. Phase cards keep the toolbar outside
the native link; instruction cards contain it after editable content and skills.
The sole phase cannot be deleted; an instruction list may become empty.

Parallel frames use the same Base Card composition and the same product class.
Orange is an explicit domain presentation requirement, retained across themes;
Base's warning palette is not used because it becomes yellow in the gray theme.
The shared CSS sets only this semantic border color and toolbar geometry; Base
still owns control states, card geometry and typography. Dynamic instruction
regrouping clones the rendered frame template, retaining the same classes and
color after reorder. Sequential records are not shown as a parallel group.

Adding inside a parallel group preserves its execution context. Phase insertion
keeps the inserted phase in the same contiguous parallel run.
Instruction toolbar actions remain disabled until mutation/order acknowledgement;
uncertain writes are not repeated automatically. Pending writes and drafts still
block navigation. Default build/check does not run the manual DOM/API fixtures.

### Плотность карточек

Режим исполнения и общие действия располагаются в нижней строке карточки.
На узком экране строка переносится без наложений; размеры кнопок остаются Base.
Ссылка фазы и панель действий — соседние элементы внутри общей карточки,
без кнопок внутри ссылки. Оранжевая рамка относится ко всей параллельной группе.
Навыки инструкции имеют видимый лейбл над строкой, связанный с группой через
aria-labelledby. Удаление внутри плашки использует компактный Base BadgeButton appearance=inline
(цель24px), а «+» — BadgeButton appearance=badge. «+» находится в том же
wrapping-ряду сразу после последнего навыка, включая динамическое обновление.
Обе рамочные плашки26px, обычные Button40/44px не уменьшаются.
Кнопка «+» открывает Base BadgeInput в геометрии плашки26px; отдельных кнопок
сохранения/отмены нет. Enter добавляет, Escape отменяет. Клик по названию
открывает inline BadgeInput24px внутри той же Badge. Enter или blur сохраняет
переименование, Escape отменяет; пустое имя отменяет правку, дубль отклоняется.
Крестик удаляет навык и не сохраняет черновик переименования. В пустом наборе
остаётся «+». Обычные формы сохраняют стандартные размеры Input40/44px.
Добавление/переименование/удаление обновляют только подтверждённые сервером
плашки без перезагрузки. Ошибка сохраняет текст; записи одной инструкции
сериализованы существующим pending guard. Навык остаётся свободным именем.

### Шапка фазы

Верхний блок содержит только название, описание и ссылку «Назад к фазам».
Название/описание сохраняются после blur через существующую очередь и draft guard.
Режим исполнения задаётся на карточке списка; шапка сохраняет только текст.
Кнопки повторного сохранения/readback скрыты в обычном состоянии и появляются
только при незавершённом сохранении. Инструкции сохраняют собственные действия.

### Ширина редактора фазы

Редактор занимает всю ширину штатного Base PageFrame. Его grid — flex-child
с явным width:100%; auto margins и дополнительные max-width не используются:
они сжимают редактор по содержимому и оставляют пустые поля. Оглавление слева
занимает176px, gap24px, контент — minmax(0,1fr), без собственного max-width.
На узком экране оглавление заменяется существующим выбором раздела. Проверять
совпадение краёв редактора/контента с PageFrame и отсутствие overflow, а не
только наличие wide/detail класса. Сам PageFrame и общие gutters принадлежат Base.

### Additional browser origin

An operator-managed HTTPS alias may be listed explicitly in `AUTH_BROWSER_ORIGINS` (JSON array). The default is empty; the canonical AUTH_PUBLIC_ORIGIN remains accepted. Each entry must be an exact HTTP(S) origin with no wildcard, userinfo, path, query or fragment. Cookie writes require an exact Origin match; absent/foreign/scheme-or-port-changed origins remain forbidden. This setting does not change OIDC issuer, registered redirects, PAT scopes or roles. A proxy must preserve the browser's Origin header.

### Типографика подписей

«Навыки» использует общий Base Label с --base-font-label:12px standard/14px large.
Текст инструкции использует --base-font-body:14/16px. Размеры определяет branding,
а не локальная таблица Workflow; навыки остаются связанными с лейблом через aria-labelledby.

### Выравнивание текста фазы

Inline Input/Textarea используют общий Base appearance без горизонтального inset: текст инструкции совпадает с левым краем её содержимого. Строки проверок и подтверждений центрируют текст, действия и декоративные SVG 16×16 по вертикали; одинаковая геометрия сохраняется для одной и нескольких строк, admin и read-only. Обычные поля формы сохраняют штатные отступы.

### Интервалы карточек

Списки фаз и инструкций используют одну раскладку из workflow-cards.css:12px между
обычными блоками,10px внутри параллельных групп. Между карточками нет стрелок или
служебных spacer-узлов ни при SSR, ни после добавления, перестановки или изменения
параллельности. Компактный список фаз сохраняет свою плотную табличную раскладку.
Оранжевая рамка и смысл параллельной группы остаются прежними.

### Переключение параллельности фаз

Кнопка меняет только execution_type. Все соседние parallel-фазы входят в одну
группу до первой sync-фазы. Рамка берётся из подтверждённого readback с тем же
правилом, что Supervisor; старые скрытые связи не влияют на неё. /workflows и
/phases поддерживают editor-v1, проверки роли/контекста и private/no-store.
Сохранение не заменяет оболочку или черновик формы. Устаревший возврат заданий
удалён; [актуальный контракт](phase-execution.md).


### Панель над фазами

Название выбранного процесса, переключатель вида и переход к фазе составляют одну
адаптивную панель. Не добавлять второй видимый заголовок «Фазы процесса» и пустой
ряд действий. Общие SectionHeader/RadioGroup/Select остаются Base-компонентами;
их внешняя компоновка принадлежит Workflow. На узком экране разрешён естественный
перенос, длинные название/описание не должны перекрывать действия.


### Интеграция общего UI с внешними контроллерами

Immutable controllers получают приватные данные только через owner HTML config.
Namespace/instruction renderers клонируют штатные inert Base macro templates;
перенос JS в отдельный asset не возвращает локальные skins. Общая плотность
фаз применяется к самой focusable ссылке; соседний shell сохраняет только
предметную компоновку, без второго padding. Действия фаз/инструкций используют
workflow-cards.html, новые inline groups и прежние Base buttons. Изменение
вида сохраняет общие dividers и не делает запись при восстановлении.

Source integration:82 shell/namespace/view tests +39 subtests,9 grouping/card
contracts и3 immutable-controller/private-fragment checks. Это локальные
проверки; полный PostgreSQL/coverage gate и authenticated IAB нового комплекта
не объявляются закрытыми. UI pin обновляется отдельным шагом после Base-кандидата.

При согласовании с master 620f45cd сохранён readonly действующего каталога:
кнопки редактирования/удаления и добавление фазы не обходят предметный запрет,
но локальный workflow остаётся редактируемым. Общие кнопки и навигация остаются
Base. Вокруг навигации режимов используется обычная product layout-область;
доступный nav и его оформление создаёт section_navigation, без второго nav и
несогласованного закрывающего тега. В инструкциях сохранён effective read перед
разблокировкой старого редактора, а inert templates общих частей не копируются.

Scoped результат: 81 template/controller/effective-read/pending-save tests,
11 browser cases намеренно не запускались в этом промежуточном проходе.
Данные phase/profession проверяются в owner HTML config, синтаксис и поведение —
в фактическом вынесенном controller. Ruff изменённых тестов прошёл. Это не
замена полному PostgreSQL/coverage и IAB gate итогового комплекта.

Динамические effective instructions клонируют inert SSR template, созданный
штатными section_header(level=3) и prose(preserve_line_breaks=true) Base.
Ранее controller собирал похожие classes сам: h3 терял data-level и получал
неверный размер, а base-prose ставился на сам список вместо общего контейнера.
Теперь заголовки, переносы и интервалы принадлежат macro; Workflow сохраняет
данные, ol/ul, parallel/skills и textContent без исполнения полученного HTML.
Показ readonly не создаёт controls и не меняет admission.

На этом diff прошли 15 адресных effective/template/controller tests и Ruff;
11 native browser cases были исключены из первого промежуточного запуска.
Затем через общий execution slot исполнены 6 configured readonly cases:
phase/instructions на 375/1920/2560. Проверены реальный computed размер h3,
общий prose-контейнер, 1/3 списков, отсутствие edit controls, записей и overflow;
все 6 screenshots просмотрены. Оставшиеся 5 browser cases не объявляются
пройденными этим запуском. Это автоматизированный project test с собственным
TestClient, не authenticated IAB или установленный стенд. UI pin и installed
runtime этим изменением не обновляются.
