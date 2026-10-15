# Быстрые повторные проверки и сборка

Применить [стандарт Base](https://github.com/FerrPOINT/services-base/blob/2a8b5e905ab2a6fd4c12d0d2a70d9436e745765d/docs/BUILD_PERFORMANCE.md) без изменения runtime и SDK/UI/skills pins.
Product-owned команды описаны в .quality-gate.json. Сохранять полный обязательный
CI/DB/security/compatibility набор на интегрированной вехе. Во время реализации
scoped tests, reuse только deterministic exact-candidate evidence.
Проверить no-change, один компонент, dependency/toolchain change и corrupt output;
измерить duration и cache hit/miss. Сохранять прогретые caches и чистить own scratch.

Общий UI fixture создаёт начальную SQLite schema/catalog один раз за pytest
session и seed digest. SQLite backup фиксирует committed WAL в неизменяемом
шаблоне; каждый тест получает отдельную копию, собственные settings/UoW и cleanup.
Изменения теста никогда не попадают в шаблон. Прямые schema/migration tests
по-прежнему выполняют настоящую подготовку через prepare_sqlite_uow.
Профилировать setup отдельно от call/teardown; миграционные и PostgreSQL gates
не заменять snapshot-копией. Регрессия: tests/test_runtime_fixture_isolation.py.
