# Тестовые уровни

Обязательная общая политика: [Base TESTING](https://github.com/FerrPOINT/services-base/blob/ad724088e9a63b1e353fb5b28e4308e9ae6f45ae/docs/TESTING.md).
Выбор компонентов и native commands: `.quality-gate.json`.

## Разработка и сборка

`python scripts/quality.py unit` (или `quality` для unit + ruff/mypy).
Ручные уровни: `integration`, `slow`, `test-integration` (PostgreSQL), `release`.
Release выполняет единый coverage >=94% и PostgreSQL отдельно.
Классификация — tests/lanes.json; unit не инициализирует SQLite/UI fixture.
По умолчанию unit/test/quality/warnings передают reviewed unit files в pytest
до collection, не импортируя остальные integration modules. Пустой/неверный
список завершает запуск ошибкой. `unit -- <test-path>` сохраняет явный выбор
pytest; release coverage по-прежнему собирает полный non-PostgreSQL набор.

## Ручная релизная проверка

Полный прежний набор сохранён в `.github/workflows/release.yml`: только
workflow_dispatch на exact ref. Автоматический CI не поднимает PostgreSQL
и не запускает длительные/browser/live тесты.

Required security/data/compatibility checks и thresholds сохраняются.
Unit success не заменяет ручную приёмку; NOT RUN не означает PASS.
