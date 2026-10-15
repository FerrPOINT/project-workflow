# Быстрые повторные проверки и сборка

Применить [стандарт Base](https://github.com/FerrPOINT/services-base/blob/197ead9d9b6cf6901e8f9dd31f43f719885502c3/docs/BUILD_PERFORMANCE.md) без изменения runtime и SDK/UI/skills pins.
Product-owned команды описаны в .quality-gate.json. При разработке/сборке —
unit/static; integration/slow/full coverage — вручную перед релизом.
Security/data/compatibility/live gates сохранены; reuse только для допустимых
deterministic exact-candidate проверок.
Проверить no-change, один компонент, dependency/toolchain change и corrupt output;
измерить duration и cache hit/miss. Сохранять прогретые caches и чистить own scratch.

Общий UI fixture создаёт начальную SQLite schema/catalog один раз за pytest
session и seed digest. SQLite backup фиксирует committed WAL в неизменяемом
шаблоне; каждый тест получает отдельную копию, собственные settings/UoW и cleanup.
Изменения теста никогда не попадают в шаблон. Прямые schema/migration tests
по-прежнему выполняют настоящую подготовку через prepare_sqlite_uow.
Полный pytest/coverage использует ровно два pytest-xdist worker в load mode:
каждый case выполняется один раз, pytest-cov объединяет coverage до порога 94%.
Scoped test и PostgreSQL integration остаются последовательными. Зависимости
pytest-xdist/execnet закреплены в pyproject, constraints и frozen uv.lock.
WORKFLOW_QUALITY_UV — отдельный override команды; переменная UV, которую сам uv
передаёт дочерним процессам как путь к binary, не заменяет canonical arguments.
Основание: [pytest-cov](https://pytest-cov.readthedocs.io/en/stable/xdist.html),
[pytest-xdist](https://pytest-xdist.readthedocs.io/en/latest/distribution.html).
Локальная квалификация на двух CPU: полный coverage около 19 минут, отдельный
PostgreSQL около 10 минут. Общий CI budget — 40 минут; индивидуальные timeouts
60/120 секунд и специальные 240-секундные E2E limits сохранены.
Профилировать setup отдельно от call/teardown; миграционные и PostgreSQL gates
не заменять snapshot-копией. Регрессия: tests/test_runtime_fixture_isolation.py.
