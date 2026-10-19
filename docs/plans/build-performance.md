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

Scoped unit с одними pytest flags сохраняет reviewed default через `testpaths`.
Ранее bool(extra) убирал явные files даже для `-k`, заставляя pytest импортировать
integration modules до marker filtering. Новый regression останавливает первый
не-unit import; RED на test_admission.py, затем GREEN на flags-only, явном пути
после flags, node ID и file-shaped значении `-k`. 14 runner tests PASS; frozen
Python 3.11.15/pytest 9.1.1, существующее окружение без install. Модель env/reuse
не меняется: uv проверяет frozen inputs между операциями, unit cacheable=false
сохраняется до отдельной qualification exact environment/receipt.

## Независимые Python и Node gates

Причина лишней работы: общие `project_workflow/**` и `scripts/**` назначали
UI assets и Node navigation test владельцу backend; единый CI job затем всегда
выполнял `make quality` и Node navigation. `.quality-gate.json` теперь разделяет
Python/backend data и UI templates/assets, сохраняя общие CI/OpenAPI inputs,
смешанный выбор и conservative fallback для неизвестного пути. CI job сохраняет
имя и обычные проверки, но каждый preparation/command запускает только нужный
consumer: независимый Base SDK check, uv и Python quality для backend, Node
navigation для frontend. Продуктовые Python, Node и dependency pins не меняются.

Проверка среза — `ComponentSelectionContracts` в `tests/test_quality_runner.py`:
реальные packaged selector/CI outputs, UI assets, Python UI neighbors, backend
data, mixed/shared/unknown inputs и условия подготовки. До изменения source
пять methods дали18 causal failures; после исправления тот же набор PASS.
Это source/selection proof без install/build/полного pytest; ускорение в секундах
и hosted execution отдельно не измерены. Coverage94%, полный manual release,
PostgreSQL, Compose и необходимые security/data/live gates сохраняются.
