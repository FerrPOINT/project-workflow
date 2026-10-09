# Changelog

Все значимые изменения проекта документируются здесь.
Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование — [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

### Changed
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
