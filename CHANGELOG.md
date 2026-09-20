# Changelog

Все значимые изменения проекта документируются здесь.
Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование — [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

### Changed
- Standalone Compose forwards optional `AUTH_*` settings without changing the empty-issuer default; Central Auth SSO has a documented deployment matrix, container-reachability requirement and browser acceptance path.
- Documentation audit is clean: README has an H1; runtime/auth, quality, reset and historical plans have cross-links and explicit security/runtime boundaries.
- Added regression coverage that proves an empty `AUTH_ISSUER` leaves UI/API open in standalone mode.
- Standalone-режим: репозиторий собирается и запускается без соседнего `services-base` (убраны extra `cli-platform`, uv source, Docker additional_context и CI checkout). Token-режим CLI без `sdlc-cli-core` выдаёт понятную ошибку; запуск без `AUTH_ISSUER` работает без авторизации.

### Fixed
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
