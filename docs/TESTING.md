# Тестовые уровни

Обязательная общая политика: [Base TESTING](https://github.com/FerrPOINT/services-base/blob/ad724088e9a63b1e353fb5b28e4308e9ae6f45ae/docs/TESTING.md).
Выбор компонентов и native commands: `.quality-gate.json`.

## Разработка и сборка

`python scripts/quality.py unit` (или `quality` для unit + ruff/mypy).
Ручные уровни: `integration`, `slow`, `test-integration` (PostgreSQL), `release`.
Release выполняет единый coverage >=94% и PostgreSQL отдельно.
`coverage-html` использует тот же canonical runner и prepared interpreter:
`python scripts/quality.py coverage-html` либо `make coverage-html` добавляет
HTML к прежним term/XML reports полного non-PostgreSQL coverage. Совместные
`make coverage coverage-html` и `make coverage-html coverage` выполняют одну
подготовку и один pytest, включая `make -j`; floor94%, strict warnings и два
workers сохраняются. `WORKFLOW_QUALITY_ENVIRONMENT` применяется тем же owner,
унаследованный workspace underlay не выбирается прямым uv вызовом из Make.
Custom `WORKFLOW_QUALITY_UV` сохраняет прежнюю семантику override.
Full release coverage включает docs contracts с integration marker; отдельный
docs job не повторяет pytest/uv и выполняет только stdlib README validator.
Классификация — tests/lanes.json; unit не инициализирует SQLite/UI fixture.
По умолчанию unit/test/test-verbose/quality/warnings передают reviewed unit files в pytest
до collection, не импортируя остальные integration modules. Пустой/неверный
список завершает запуск ошибкой. `unit -- <test-path>` сохраняет явный выбор
pytest; release coverage по-прежнему собирает полный non-PostgreSQL набор.

Flags-only, например `python scripts/quality.py unit -- -k phase`, сохраняет
reviewed collection через pytest `testpaths`. Pytest сам отличает пути от
значений options: путь после флагов и `file.py::test_name` сужают collection,
а похожее на путь значение `-k` не расширяет её до integration. Runner всегда
работает из корня продукта; этот default относится только к unit/test lanes.
Regression проверяет фактически импортированные модули в fresh pinned Python;
14 runner tests PASS, четыре дополнительных subprocess collection controls.
Ни app/runtime, ни полный coverage для этой qualification не запускаются.

`make test-verbose`, `python scripts/quality.py test-verbose` и PowerShell target
`test-verbose` используют тот же reviewed unit список с `-v`; дополнительная
подробность вывода не включает collection integration-модулей. Явные scoped
аргументы передавать через `test -- <test-path>`, а не через verbose target.

`tests/test_quality_runner.py` имеет одного владельца — `backend:unit`;
изменения runner/Makefile/его тестов выбирают этот lane без второго tooling gate.
Для точечного запуска сохраняется `python scripts/quality.py test -- tests/test_quality_runner.py`.
Docs-only CI выполняет stdlib README validator без uv bootstrap и pytest.

Пути для local selector и CI принадлежат `.quality-gate.json`: Python sources,
backend data и Python runner/tests выбирают `backend:unit`; UI templates/assets
и `scripts/test_profession_navigation.mjs` выбирают `frontend:navigation`.
Python handlers UI остаются backend inputs. CI выполняет pinned Base SDK check,
uv preparation и `make quality` только для backend; Node navigation — только
для frontend. Смешанные изменения, CI/OpenAPI и неизвестные пути сохраняют оба
набора. Ручной release остаётся полным, включая coverage94% и PostgreSQL.
Source/selector regression без подготовки окружения:
`python -B -m unittest tests.test_quality_runner.ComponentSelectionContracts -q`.

`python -B scripts/quality.py --inspect-environment` наблюдает metadata текущего
Python без подготовки/тестов; это не certificate пригодного environment или
test receipt. Команда и overlay boundary описаны в [quality gate](quality-gate.md).
Её model tests находятся в reviewed unit lane. Полный pytest/coverage ради
этой команды не требуется; порог coverage 94% и ручные release gates сохраняются.

## Подготовка fixtures только для потребителя

Root `tests/conftest.py` не импортирует DB/UoW/LLM и SQLite helpers при collection.
Autouse isolation сначала читает reviewed unit marker; для unit не запрашивает
`tmp_path`, `monkeypatch` и session UI templates. Integration получает эти
fixtures через `request.getfixturevalue()` во время setup, затем выполняет
прежнюю SQLite snapshot/isolation/teardown логику. LLM implementation загружается
только при запросе `supervisor_llm`. Fixtures не запрашиваются при teardown.

`tests/test_fixture_imports.py` проверяет эту границу в свежем interpreter с
запрещёнными application imports, а также сохраняет integration/LLM consumer
activation. Это короткий tooling unit с контролируемым Python subprocess,
без продукта/сервера/БД/сети. Pytest lane metadata включает его явно.
Scoped command: `python scripts/quality.py test -- tests/test_fixture_imports.py`.

Import-only pilot на Windows, existing prepared Python3.11.15/pytest9.1.1:
три fresh-process samples на каждую версию дали медианы wall0,903→0,183с,
own CPU0,906→0,188с, process peak working set79 638 528→30 273 536 B.
Измерены только definitions/import conftest, с одинаковой frozen lane metadata
и общим OS platform bootstrap до таймера. Dependency installation не выполнялась;
это не новый proof completeness uv lock или ускорение полного quality/build.
Peak — OS working set процесса с начала жизни, включая bootstrap, не unique RAM
приложения/хоста и не process tree. Cold filesystem cache не квалифицирован.
В измеряемой фазе guard запрещает DB/network/subprocess/file writes.

Реальные SQLite/PG/release coverage gates остаются отдельной ручной приёмкой.
Public UI exports и schema-only import имеют отдельный pilot ниже; его числа
не суммируются с fixture pilot и не относятся к полной сборке.

## Ленивые UI exports

`project_workflow.interfaces.ui` загружает public symbols при обращении к ним.
Schema-only import не готовит ASGI app/routes, DB или Uvicorn. `__all__`, `dir`,
wildcard import, service/template symbols и прежние имена сохраняются.
`_app_state`/`_AppState` остаются read-through, включая явные monkeypatch overrides.
Остальные exports сохраняют identity после первого обращения; новый app не
создаётся на каждое чтение атрибута.

`app` и `main` — legacy object/function exports с именами подмодулей. Обычного
`__getattr__` недостаточно: direct submodule import может записать module на
parent package. Стандартный ModuleType setter сохраняет legacy value только
для этих двух collisions. Direct importlib module access и остальные submodules
остаются обычными modules; ASGI app и CLI function не обёрнуты в proxy.
TYPE_CHECKING imports сохраняют static exports без runtime preparation.

`tests/test_ui_imports.py` проверяет package-first, legacy-first, submodule-first,
services-first, wildcard/state и настоящий schemas import с запрещёнными heavy
imports. Scoped run с существующими schemas/fixture tests дал48PASS; после
уточнения static exports final7 cases PASS за0,83с, scoped Ruff/mypy PASS.
Контролируемые modules проверяют Python binding, не HTTP semantics. Отдельный
read-only probe с actual app/main подтвердил обе import orders и прежнюю сигнатуру
60 routes без lifespan/server/DB/network. Browser/live acceptance этого source
кандидата остаётся на интегрированной вехе; старый runtime её не заменяет.

Schema import pilot в том же Windows Python3.11.15, три fresh-process samples:
median wall1,377→0,200с, own CPU1,250→0,203с, process peak working set
101 085 184→32 260 096 B. Общий platform bootstrap до timer; static app/route
parity проверяется после снятия метрик, вне schema-import boundary. Это не
startup/полная collection/build metric. Cold FS cache и unique RAM не измерены.
Изменён production module, поэтому applicable Workflow application image/UI
проверяется свежим на вехе; неизменные dependency graphs не готовятся повторно.

## Ручная релизная проверка

Полный прежний набор сохранён в `.github/workflows/release.yml`: только
workflow_dispatch на exact ref. Автоматический CI не поднимает PostgreSQL
и не запускает длительные/browser/live тесты.

Required security/data/compatibility checks и thresholds сохраняются.
Unit success не заменяет ручную приёмку; NOT RUN не означает PASS.

## Python dependency layers

Runtime Dockerfile выделяет `runtime-dependencies` до исходников приложения.
`scripts/dependency_inputs.py` выбирает только static runtime + UI requirements;
constraints, Python parent/ABI и platform остаются входами установки. Изменение
версии/описания пакета или неиспользуемого dev extra не переустанавливает runtime
dependencies; выбранный runtime/UI requirement инвалидирует слой. Проверки этой
границы входят в unit lane. Pip download store сохраняется в общем operator pool.
Application layer по-прежнему проверяет immutable manifest до установки пакета,
затем выполняет pip check и installed compatibility proof. Producer не заменяется
сборкой произвольного каталога; локальные `.local` environments исключены из context.
Проверка manifest передаёт installation stage bind witness с постоянными bytes:
новые revision/archive/descriptor обновляют provenance, сохраняя wheel layer при
прежних application inputs. Проверка всё равно выполняется для нового manifest;
неверный manifest блокирует и прогретый слой. SHA сам по себе не является причиной
повторной установки приложения, если он читается из отдельного runtime manifest.
