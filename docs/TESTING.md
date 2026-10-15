# Тестовые уровни

Обязательная общая политика: [Base TESTING](https://github.com/FerrPOINT/services-base/blob/c9e4182e460ee57ac38a0ab1a866ce9626d297a4/docs/TESTING.md).
Выбор компонентов и native commands: `.quality-gate.json`.

## Разработка и сборка

`python scripts/quality.py unit` (или `quality` для unit + ruff/mypy).
Ручные уровни: `integration`, `slow`, `test-integration` (PostgreSQL), `release`.
Release выполняет единый coverage >=94% и PostgreSQL отдельно.
Классификация — tests/lanes.json; unit не инициализирует SQLite/UI fixture.

## Ручная релизная проверка

Полный прежний набор сохранён в `.github/workflows/release.yml`: только
workflow_dispatch на exact ref. Автоматический CI не поднимает PostgreSQL
и не запускает длительные/browser/live тесты.

Required security/data/compatibility checks и thresholds сохраняются.
Unit success не заменяет ручную приёмку; NOT RUN не означает PASS.
