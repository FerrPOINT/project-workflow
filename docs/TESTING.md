# Тестовые уровни

Обязательная общая политика: [Base TESTING](https://github.com/FerrPOINT/services-base/blob/ad724088e9a63b1e353fb5b28e4308e9ae6f45ae/docs/TESTING.md).
Выбор компонентов и native commands: `.quality-gate.json`.

## Разработка и сборка

`python scripts/quality.py unit` (или `quality` для unit + ruff/mypy).
Ручные уровни: `integration`, `slow`, `test-integration` (PostgreSQL), `release`.
Release выполняет единый coverage >=94% и PostgreSQL отдельно.
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

`dependency-wheels.json` фиксирует reviewed metadata closure для
`cpython-311-bookworm-amd64`:37runtime/UI wheels и6build wheels. Версии остаются
каноническими в constraints.txt; helper проверяет их против наблюдённых metadata
и выпускает отдельные exact/hash requirement files. Это не перенос versions из
uv.lock. Изменение selected pin, root, backend или dependency edges требует
обновлённого metadata proof и явного reviewed contract digest в helper. Dev-only
pins и package metadata не меняют install files. Новая JSON не входит в runtime
payload; её читает только dependency-inputs stage.

Runtime dependency stage проверенного target использует binary wheels без
build-essential/libpq-dev. Для других архитектур helper явно возвращает полные
constraints и прежнюю подготовку native build dependencies; это не qualified
fast path. Corrupt/неизвестный metadata contract не превращается в fallback.
Build tools готовятся отдельно в `/opt/build-venv`; wheel строится через
`pip wheel --no-build-isolation --no-deps`, затем устанавливается в runtime venv.
Wheel producer наследует только build-tools; runtime dependency layer не является
его parent. Отдельный installed stage получает один готовый wheel и runtime venv.
Изменение runtime dependency не должно повторять Hatchling build неизменного wheel.
Не полагаться на наследование PIP_CONSTRAINT из isolated pip build: этот путь
использует явно подготовленный backend. Финальный image сохраняет прежние шесть
runtime payload paths, без build venv и без изменения source/provenance guards.

Scope source unit:

```bash
python scripts/quality.py test -- tests/test_dependency_locks.py
```

В этот pure unit файл перенесён Docker/venv constraint guard из смешанного
test_runtime_cleanup.py: build feedback не импортирует SQLAlchemy/DB tests ради
проверки recipe. Native cache/installed/wheel/profile qualification нового
recipe выполняется отдельно на согласованной вехе. Metadata observation и
source guards сами по себе не доказывают pip target solve, cache hit или RAM.

`wheel-inputs` содержит `pyproject.toml`, README, LICENSE и весь `project_workflow/`:
текущий закреплённый Hatchling использует default package selection, без hooks,
dynamic metadata или дополнительных include rules. `scripts/` и `alembic.ini`
добавляются только в `application-inputs`; их изменение не меняет parent wheel
builder. Миграции внутри Python package остаются входами wheel. Изменение build
backend, metadata hooks или include rules требует новой квалификации этой границы.
Unit guards проверяют конфигурацию и зависимости стадий, а не содержимое wheel.

Поздний `runtime-inputs` наследует установленный и очищенный venv из installed,
получает полный `/app` из `verified-inputs` и выполняет installed compatibility
proof. Финальный образ получает весь прежний runtime payload только из этой стадии.
Копировать venv поверх venv из dependency stage нельзя: directory merge может
восстановить удалённые pip/setuptools/wheel. Перенос scripts после установки в
одной стадии не подходит: manifest должен проверяться до установки пакета.
Native qualification на вехе должна отдельно подтвердить inventory wheel, reuse
при изменении только scripts/alembic и отказ на неверном manifest при прогретом
wheel. Source checks не доказывают BuildKit cache hit или ускорение.

## Проверки runner через отдельные процессы

`tests/test_quality_process.py` сохраняет два прежних black-box controls: verbose
collection и четыре scoped pytest cases с реальными fresh interpreters/plugins.
Это integration boundary runner, поэтому обычный unit/build не запускает его.
Файл по умолчанию относится к manual integration и собирается полным release
coverage. Быстрые unit contracts выбора файлов, flags, frozen pins и prepared
interpreter остаются в `tests/test_quality_runner.py`.

Ручной scoped запуск: `python scripts/quality.py integration -- tests/test_quality_process.py`.
Controls работают только с собственными temporary plugin files и child processes;
локальная autouse fixture исключает ненужную подготовку DB/UI, assertions не меняются.
Перенос tier не является новым PASS этих manual tests; прежний result сохраняется
для прежнего source, release проверяет актуальный candidate отдельно.

## Окружение host producer

`producer-environment.json` явно включает Base profile `locked-core-v1` для сборки
immutable image: Python3.11.15, `uv run --locked` без UI extra, один project environment
без requirements overlay. Нужен совместимый Base helper; старые exact tooling pins
самостоятельно не обновляются. Quality по-прежнему использует свой frozen profile
со всеми необходимыми test extras; producer не устанавливает их ради image.

Перед UV Base сверяет profile/pyproject/lock/constraints с выбранным Git revision
и проверяет общие версии constraints/lock. `--locked` сохраняет отказ на устаревшем
lockfile, как описано в [документации UV](https://docs.astral.sh/uv/concepts/projects/sync/).
Неизвестный profile, dirty inputs и mismatch запрещают подготовку вместо fallback.
Checkout без opt-in сохраняет прежний legacy requirements path. Approved prepared
context по-прежнему запускает stdlib producer без UV или новой установки.

Image producer использует core/catalog imports; FastAPI, Uvicorn, Jinja2, HTTPX
и JWT/crypto относятся к приложению. Их runtime/UI dependencies сохраняются.
`test_build_producer_imports.py` проверяет оба каталога с запрещёнными UI imports
без DB/runtime fixture. Старый `locked-ui-v1` остаётся совместимым Base profile.
Prepared environment с совместимыми дополнительными пакетами переиспользуется;
их наличие не означает import/RAM overhead и не требует профилактической очистки.

Source contracts проверены отдельно от native image/environment qualification.
Для нового profile ещё требуется одна cold/warm core preparation на согласованной
вехе; отсутствие overlay не выдаётся за уже измеренное ускорение приложения.

## Управляемый экспорт исходников

`scripts/vendor/base-controlled-git-archive.json` отдельно закрепляет Base helper
по commit и SHA256. Builder исполняет проверенные source bytes, исключая старый
checkout `.pyc`. Экспорт точного commit сохраняет pinned attributes, binary/EOL
и executable modes, исключая mutable refs, info/attributes и ambient Git env.
Новый profile явно задаёт modes 0644/0755; SDK/skills/quality pins не меняются.

`tests/test_controlled_source_archive.py` — reviewed unit lane с tiny Git fixtures,
без Docker/БД. Scoped запуск: `python scripts/quality.py test --
tests/test_controlled_source_archive.py tests/test_prepared_context.py`.
Новые receipts связывают archive policy/helper hash; прежние approved receipts
остаются читаемыми. Это source prerequisite: `environment_equivalence` остаётся
`UNQUALIFIED`, default owner/reuse и native qualification проверяются отдельно.
