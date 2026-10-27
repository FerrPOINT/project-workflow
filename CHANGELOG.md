# Changelog

Все значимые изменения проекта документируются здесь.
Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование — [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

### Added

- Configured PM final judging is precommit-only: valid full saved requirements,
  resolved feedback/questions and exact actual owner consent in Draft. The
  worker retains its full terminal-receipt/Tracker completion commands, but the
  judge cannot require those future effects before its verdict. Known retained
  terminal/check/evidence variants are projected without changing the legacy
  catalog or custom security constraints. No forced PASS or new authority.
  All35 configured tests and independent review pass on210db1; normal
  Workflow-only installation preserves all nine history tables. The SAME real
  PM11/FLEETQA-8 then produced PASS/complete=true/version14/history13 and an
  authoritative terminal receipt. PM submitted Tracker completion through CLI;
  Backlog/Ready, one completion and zero downstream assignments/intents were
  verified, including original-key replay. This is assisted existing-task live
  acceptance, not fresh autonomous or full release qualification.

- Configured PM preparation instructions distinguish the independently generated
  Workflow execution_ref from Tracker assignment.execution_id, and Workflow
  cursor versions from Tracker assignment versions. Match task/assignment/agent
  identities by authority; do not rebind or invent IDs to make unrelated IDs
  equal. Eight focused source tests pass, including evaluator prompt coverage.
  The instruction corrections are installed with210db1. In the existing
  live PM chat, an explicit explanation allowed the agent to submit a corrected
  report and advance PM-DRAFT-01 to PM-DRAFT-02; that assisted check is not full
  autonomous PM or Backlog acceptance.

- Opt-in configured-cli-v1 for new PM tasks: existing trusted assignment and
  direct step/history endpoints with a dedicated per-agent Auth PAT, current
  Tracker assignment validation, version/key replay and actual owner-confirmed
  terminal receipts. No temporary CLI files, native/Fleet callback or human-route
  machine admission. Legacy records and applied schemas/catalogs are unchanged.
  Host qualification is scoped; PostgreSQL, packaged/integrated and live gates
  remain open. See docs/configured-cli-v1.md for wire and deployment dependencies.

- Обновлён штатный SSR export Base: страницы ошибок больше не показывают лишний заголовок None. HTTP-регрессия проверяет единственный правильный h1 и возврат к списку как в корне, так и под UI_BASE_PATH.

- Навигация и редактор учитывают UI_BASE_PATH: смена профессии со страницы фазы сбрасывает прежние workflow/mode и сохраняет проектный контекст; порядок инструкций сохраняется без повторного префикса, а возврат со страницы ошибки остаётся внутри приложения.

- Штатный SSR export Base сохраняет размеры полей без внешнего CSS reset. Регрессия редактирования namespace проверяет сохранение как default, так и custom workflow.

- Резервное меню сервисов сохраняет локальную навигацию Workflow. Неподтверждённые
  адреса других приложений недоступны; после восстановления каталога Admin
  и обновления страницы ссылки снова доступны.

- Форма Workflow блокирует поля, повторную отправку и смену выбранного процесса
  до завершения записи и обновления данных. Ошибка сохраняет введённые значения;
  поздний ответ больше не стирает новый ввод. Защита процесса по умолчанию сохраняется.

- Платформенные UI/SDK imports и пути переведены на PDLC и `base-modules/ui`; совместимые readers сохраняют прежние credentials/транзакции. Нормативные термины и границы описаны в `docs/PDLC_BASE_INTEGRATION.md`; установка и включение новых writers выполняются отдельно.

- Оболочка не загружает Google Fonts: использует локально доступные шрифты и
  существующие системные fallback, сохраняя работу без внешней сети.

- Логотип оболочки использует общий размер Base 40 px; компактный сайдбар равен высоте хедера (60 px).

- Base SSR export закреплён на `5b460dd20eea`: WebKit сохраняет click по
  ссылке выхода при переносе фокуса на родительский main. Fingerprint обновлён
  штатным export; включены актуальные Base shell tokens.

- Runtime CLI `step` forwards the supplied operation key, frozen request and scoped token;
  it requires an explicit service URL and never sends execution credentials to the legacy default endpoint.

- Namespace cohort: стабильные refs, локальные binding projections и lifecycle guards; аддитивные migrations, совместимый rollback и отдельные execution v2 gates. Runtime-приёмка ещё не завершена.


### Changed
- Configured PM first-step reports explicitly include the already observed CLI
  stdout fields and Tracker task/input references. CLI JSON is flattened; do not
  invent HTTP ok/result wrappers or a future report verdict as evidence. Existing
  verifier/check lists remain unchanged. Fifty-one focused tests and Ruff pass;
  the current instruction update is installed; full live acceptance is separate.
- Actual retained0015-copy migration-only qualification passes on `6c98e83`:
  two existing `ensure_migrated()` calls preserve old data/catalog/PM history,
  add only four identity tables and reach0019; outer cleanup is verified.
  Full retry host module39 plus11 adjacent cases pass with scoped Ruff/mypy.
  `init_db()` seeding failures remain retained; image/install, full gates,
  authenticated PM HTTP and live owner-confirmed Backlog/Ready remain open.
- PM terminal resume retry preserves the single trusted observation's null or
  exact inherited source checkpoint marker without treating it as own progress.
  The populated0018 upgrade plus six affected PostgreSQL cases pass on `6c98e83`
  (7/7, cleanup verified); foreign markers and genuine rebound targets remain
  rejected. Full gates, Fleet transactional recovery and live PM acceptance
  remain open; the earlier PG7 keeps its historical scope.
- The normal migration entrypoint accepts0018 as the predecessor of0019.
  Seven actual PostgreSQL retry/migration/concurrency tests pass, including
  retained receipts, rollback refusal and observed row-lock waits. These
  source checks do not claim an installed or live PM business result.
- Documented the opt-in PM terminal resume retry V1 command, distinct receipt,
  scoped readback and additive migration 0019. Source/SQLite and reported Fleet
  golden verification are separated from open PostgreSQL/deployment/live gates;
  retained operation history is never deleted to permit downgrade.
- PM Draft assignments accept the actual Tracker reservation and input snapshot
  without inventing future queue/workspace refs. Additive migration 0009 preserves
  existing assignment history; bind keeps the original agent and generic steps,
  replacement and rebind cannot bypass verified PM enrollment.
- Namespace/workflow context sits beside account on the right; compact sidebar
  applies the Base SSR scope and shrinks with its labels and content offset.
- Mobile service menu stays inside the viewport; namespace selection and history
  update both desktop and drawer selectors.
- Header matches the Base product/service/context/account order; page actions
  leave the global header. Account menu consumes the pinned Base SSR theme
  primitive and synchronizes the browser preference with React products.
- Standalone Compose forwards optional `AUTH_*` settings without changing the empty-issuer default; Central Auth SSO has a documented deployment matrix, container-reachability requirement and browser acceptance path.
- Documentation audit is clean: README has an H1; runtime/auth, quality, reset and historical plans have cross-links and explicit security/runtime boundaries.
- Added regression coverage that proves an empty `AUTH_ISSUER` leaves UI/API open in standalone mode.
- Standalone-режим: репозиторий собирается и запускается без соседнего `services-base` (убраны extra `cli-platform`, uv source, Docker additional_context и CI checkout). Token-режим CLI без `sdlc-cli-core` выдаёт понятную ошибку; запуск без `AUTH_ISSUER` работает без авторизации.

### Fixed
- Machine namespace authorization accepts Base's optional `display_name`
  introspection metadata while preserving required identity/grants, registered
  subjects and rejection of unknown claims.
- Phase saves bind returned check/evidence IDs to the submitted rows, even when
  the list changes during the request. A temporarily blank saved row is not
  silently deleted by saving another field. Health SQL runs in FastAPI's thread
  pool so a slow probe does not stall unrelated requests.
- Legacy v2 runtime steps consume saved instruction/check/evidence text from the
  database; readiness validates the saved phase graph, role ownership and skill
  limits. Valid reordering, parallel execution and added phases do not disable
  the role merely because the graph differs from the seed catalog.
- Runtime discovery ignores presentation changes and unrelated workflows;
  readiness checks the calling managed role. Synchronous human API and HTML
  routes use FastAPI's thread pool. Rejected instruction saves retain entered text.
- Installed catalogs allow normal phase, instruction, agent and namespace edits.
  Saving and reopening retain the new values; startup and migration reruns keep
  saved edits. Packaged executor compatibility is checked at the runtime API,
  independently of editor availability.
- Base binding OpenAPI keeps its published 422 description independent of the
  Python standard library status phrase; validation status and DTO are unchanged.
- Index PM operation history by execution and kind so checkpoint uniqueness
  checks do not scan other executions while holding the task lock. Keep the
  ORM and pending PM migration schema in sync.

- Namespace owner verification bounds streamed responses and the complete
  command with a total deadline, sharing one request-owned HTTP pool.
- Immutable image builder закрепляет Git EOL-настройки только для archive:
  один commit даёт одинаковые source/bundle digests независимо от пользовательских
  `core.autocrlf` и `core.eol`; явные repository EOL rules и binary bytes сохранены.
- Central-mode SSO session, OIDC transaction and namespace selector cookies are scoped to the configured public issuer and Workflow origin, preventing collisions between local ports. Middleware retains its installation-time settings; logout clears only its own session and pending transaction with the configured cookie attributes. Standalone mode and machine-token APIs are unchanged; legacy central-mode cookies require a fresh SSO redirect.
- Task detail partial-verdict использует читаемый основной текст, сохраняя жёлтые фон и рамку: summary и activity badges проходят контраст светлой темы без изменения других verdict-типов (#93).
- Заблокированный статус и список блокеров на task detail используют читаемые цвета текста во всех темах; красные фон и рамки сохранены, включая рамку статуса (#94).
- Номера фаз на task detail читаются как «Фаза N» без недопустимого `aria-label` на generic spans; последовательные и параллельные карточки сохраняют компактные индикаторы.
- SSR-переключатель берёт текущий Workflow и его health из runtime-каталога,
  без hardcoded healthy. Полный fallback из шести UI остаётся unknown при
  сетевой ошибке, пустом или невалидном ответе; TTL cache разделён по URL.
- Immutable image builder передаёт PAX-first tar через deterministic gzip;
  Docker распознаёт stdin как context, а не Dockerfile. Source/bundle digests
  и manifest contract не меняются.
- SQLite migration test закрывает UoW и гарантированно освобождает собственный
  engine; строгий ResourceWarning gate не зависит от момента garbage collection.
- Меню сервисов не перекрывается sidebar и помещается на низком экране;
  локальные переходы сохраняют канонический `localhost` для общей SSO-сессии.
- Standalone Compose получает runtime-каталог через `host.docker.internal`,
  а пример `.env` больше не подменяет этот адрес контейнерным `localhost`.
- Workflow shell синхронизирован с документированным контрактом: header 60 px,
  desktop sidebar 264 px, tablet rail 72 px и mobile drawer только ниже 768 px.
- Workflow shell доступен с touch и клавиатуры (#49); улучшены phase controls и accessibility (#48).
### Added
- Central SSO и token-mode CLI transport (`feat/central-sso-cli`, #43): browser-сессии central auth и personal tokens как транспорт CLI.
- Hosted CI (quality + compose-readiness) на каждый push/PR.

### Changed
- UI `/phases`: длинные цепочки открываются компактным списком с переключением на схему; единственный воркфлоу больше не дублируется в навигации.
- UI `/phases`: быстрый переход к фазе в длинном списке с фокусом на выбранной фазе; иконки пространства в header сохраняют цель 40 px.
- UI: улучшен контраст dark brand subtitle (#44).

### Removed
- Мобильные галереи и auth-скриншоты из README — desktop-only evidence standard.
- Explicit Base control-plane image variant закрепляет private Base package
  и candidate 7/11/33 без подключения legacy execution bridge. Default каталог
  прежних installations остаётся неизменным; автономное исполнение не включено.
