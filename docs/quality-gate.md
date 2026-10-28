# Quality Gate

Подготовка без тестов и HTML из готовых данных: [дополнительные команды](quality-auxiliary.md).

Обязательная политика уровней: [TESTING](TESTING.md).
Автоматический ci.yml выполняет `make quality`: unit + ruff/mypy, без БД.
Ручной release.yml выполняет `make release`: один полный non-PostgreSQL pytest
с coverage >=94%, XML, strict warnings и двумя workers; затем PostgreSQL 16
отдельно, serial, с прежними timeout и integration assertions.
Make, scripts/quality.ps1 и CI используют scripts/quality.py, frozen uv.lock
и constraints.txt. `coverage` — ручная полная non-PostgreSQL проверка.
Далее описаны ручные release/diagnostic сценарии, а не обязательная работа
после каждого изменения. Unit fixture не создаёт SQLite/UI state.

Canonical quality runner готовит frozen Python 3.11.15 project environment один раз
на операцию; pytest, Ruff и mypy используют подготовленный interpreter.
Между операциями uv заново проверяет определяющие inputs.
Пользовательский WORKFLOW_QUALITY_UV сохраняет собственную семантику запуска.

`test-verbose` во всех helpers делегирует canonical runner и меняет только
подробность unit-вывода. Reviewed files из `tests/lanes.json` передаются до
collection; integration/slow модули не импортируются ради marker deselection.
При scoped unit с одними flags действует тот же reviewed default через
`testpaths`; явные paths/node IDs выбирает parser pytest. Подробности и controls
в [TESTING](TESTING.md).

## Navigation unit contract

`node scripts/test_profession_navigation.mjs` выполняет шесть изолированных
unit cases без Python, browser, install, network или application build. Его
пять входов — descriptor, сам executor и три template — заданы общим списком
в executor и проверяются против `frontend:navigation`. Не расширять чтение,
не обновив этот контракт. Independent unit gate использует `execution_slot: none`.

`node scripts/test_profession_navigation.mjs --context` наблюдает version,
platform/architecture и SHA-256 фактического Node executable; Base повторно
проверяет context до reuse и после исполнения. Injected modules/Node flags
отклоняются. PDLC3 сохраняет дополнительный platform-navigation bootstrap в inputs.
Его новый пятифайловый профиль выполняется свежим (`cacheable=false`) до
отдельной exact caller/receipt qualification; прежний четырёхфайловый proof
не переносится автоматически. Base сохраняет полный
environment digest и ограничивает unit receipt тем же commit и clean tree.

`node tests/node/test_navigation_inputs.mjs` — CI entrypoint для изменений:
он один раз выполняет те же шесть кейсов в закрытой file fixture и добавляет
пять contract controls, включая отказ при повреждённых inputs и assertion failure.
Не запускать оба entrypoint подряд без отдельной диагностической причины.
Изменение backend/docs вне inputs не меняет content portion ключа; новый commit
всё равно требует нового unit receipt. Это не cross-commit artifact reuse.

## Базовый gate

Перед тестами проверить экспорт общего namespace из чистого sibling Base,
закреплённого в `.base-revision`:

```bash
python ../services-base/scripts/verify_base_revision.py --base ../services-base --revision .base-revision
python ../services-base/scripts/export_python_namespace.py --out project_workflow/infrastructure/platform_namespace.py --check
```

Это независимый SDK pin для подготовленного модуля без внешних зависимостей.
`.base-ui-revision` закрепляет SSR/UI; skills и candidate-каталог имеют собственные
источники. Web runtime не обязан устанавливать HTTP SDK ради классификации PAT
или чтения env. В CI checkout SDK использует read-only deploy key `SERVICES_BASE_DEPLOY_KEY`.

```bash
python scripts/quality.py release
```

Make, PowerShell и CI делегируют `scripts/quality.py`. Он выполняет один полный
pytest с coverage >=94%, XML, строгими ResourceWarning/unraisable flags и durations,
отдельный PostgreSQL integration, ruff/mypy и git diff check. Окружение
`.local/quality-python/<OS>/3.11.15` постоянно; frozen `uv.lock` и overlay
`constraints.txt` сохраняются. Неизменившиеся зависимости повторно не устанавливаются.
Scoped пример: `python scripts/quality.py test -- tests/test_quality_runner.py`.
Полный coverage запускает два worker в load mode с общим отчётом и прежним
порогом 94%; scoped и PostgreSQL integration выполняются последовательно.
Для явного override prefix использовать WORKFLOW_QUALITY_UV; переменная UV
может содержать только путь binary, выставленный самим uv.


Ожидаемый результат:

- обычный pytest проходит без падений; PostgreSQL integration tests в нём
  показываются как deselected;
- отдельный PostgreSQL integration gate проходит на реальном PostgreSQL;
- coverage остаётся не ниже текущего локального baseline `94%`;
- `ruff`, `mypy` и `git diff --check` не находят ошибок.

На Unix-like окружении тот же набор доступен через `make release`; на Windows
без `make` используйте `pwsh -File scripts/quality.ps1 release`. Дополнительные
цели `warnings` и `compose-ready` есть и в `Makefile`, и в PowerShell helper.

## ResourceWarning Gate

Ручной `release` выполняет строгую проверку предупреждений внутри единственного
coverage-прогона. После его успеха полный pytest повторно не запускать.
Обычный `quality` выполняет unit + lint/types без полного coverage.
Самостоятельная строгая диагностика reviewed unit без coverage:

```bash
python scripts/quality.py warnings
```

Этот прогон должен проходить без SQLite connection warnings, включая
`PytestUnraisableExceptionWarning`, и без зависаний на повторных миграционных
кейсах. Если тест создаёт `SAUnitOfWork` вручную, он должен использовать context
manager или закрываться через общий pytest lifecycle в `tests/conftest.py`. Если
тест создаёт SQLite engine напрямую, engine должен быть disposed в teardown.

## PostgreSQL Integration

Integration tests требуют локальный PostgreSQL с правом создавать и удалять
временные базы:

```bash
PGHOST=127.0.0.1
PGPORT=5432
PGUSER=project_workflow
PGPASSWORD=project_workflow
PGDATABASE=project_workflow
```

Набор `tests/test_postgres_integration.py` проверяет реальный путь CLI
subprocess -> PostgreSQL -> тестовый OpenAI-compatible HTTP endpoint ->
Supervisor -> PostgreSQL. Это deterministic runtime integration, а не полный
business E2E с настоящим исполнителем.

Полный executor-driven acceptance описан отдельно в
[`LIVE_TEST_PLAN.md`](../LIVE_TEST_PLAN.md).

## Compose Readiness

Для проверки локального runtime:

```bash
docker compose up --build -d --wait
curl --fail http://127.0.0.1:8812/health
```

Ожидается HTTP `200`, `database=ok`, `schema=ok`. Стандартный Compose публикует
PostgreSQL и API только на loopback. Для стандартного compose-ready должны быть
свободны `127.0.0.1:5432` и `127.0.0.1:8812`; если порт 5432 занят другим
PostgreSQL, integration gate можно запускать с `PGPORT`, указывающим на
отдельный тестовый PostgreSQL.

## UI Smoke

Регрессии общей шапки на отдельной smoke-базе проверяются командой
`SMOKE_BASE_URL=http://127.0.0.1:8812 node scripts/check_ui_shell.mjs`.
Это project-owned automated Playwright runner: два namespace selectors,
history/reload, service popover на 320/375/767/768/1920/2560 и mobile drawer.
Ручная визуальная приёмка использует Codex in-app Browser.
На нейтральном smoke-каталоге `workflow-dev` / `workflow-qa` флаг
`--owned-fixture` дополнительно создаёт и удаляет только собственное пустое
пространство и проверяет оба selector после удаления; исходные записи сохраняются.

После любых изменений UI/templates/static JS:

Подготовить отдельную нейтральную smoke-базу, чтобы скриншоты не зависели от
дефолтного runtime-каталога и показывали две независимые записи для одной
внешней задачи:

`prepare_ui_smoke_data.py` намеренно принимает только отдельную SQLite smoke-базу
в `.smoke/ui-smoke.db` или файл `ui-smoke.db`; обычную runtime-БД он отклоняет.

```bash
export DATABASE_URL=sqlite:///$PWD/.smoke/ui-smoke.db
rm -f .smoke/ui-smoke.db
python -m scripts.prepare_ui_smoke_data
python -m project_workflow.interfaces.ui --host 127.0.0.1 --port 8812
```

В другом терминале:

```bash
npm --prefix .smoke install playwright
SMOKE_BASE_URL=http://127.0.0.1:8812 node scripts/capture_ui_screenshots.mjs
```

PowerShell:

```powershell
$env:DATABASE_URL = "sqlite:///$PWD/.smoke/ui-smoke.db"
Remove-Item -LiteralPath .smoke/ui-smoke.db -ErrorAction SilentlyContinue
python -m scripts.prepare_ui_smoke_data
python -m project_workflow.interfaces.ui --host 127.0.0.1 --port 8812
```

В другом PowerShell:

```powershell
npm --prefix .smoke install playwright
$env:SMOKE_BASE_URL = "http://127.0.0.1:8812"
node scripts/capture_ui_screenshots.mjs
```

- открыть `http://127.0.0.1:8812/`;
- открыть `http://127.0.0.1:8812/namespaces`;
- открыть `http://127.0.0.1:8812/namespaces/new`;
- открыть `http://127.0.0.1:8812/tasks`;
- открыть `http://127.0.0.1:8812/tasks?namespace_id=<qa-id>`;
- открыть `http://127.0.0.1:8812/phases`;
- открыть `http://127.0.0.1:8812/settings`;
- открыть detail одной задачи в двух выбранных неймспейсах, если менялись selector,
  task links, theme или данные выбранного неймспейса;
- открыть `http://127.0.0.1:8812/workflows`, если менялись workflow controls,
  фазы или CRUD workflow;
- проверить, что верхний selector переключает выбранную профессию, её иконку и цвет
  в самом selector, список задач, dashboard stats и `/phases`; логотип приложения
  и общие стили кнопок сохраняются;
- проверить, что страницы загрузились без console/network ошибок;
- сохранить full-page screenshot evidence через `scripts/capture_ui_screenshots.mjs`;
- убедиться, что screenshot evidence сделан на полной нейтральной smoke-fixture
  с задачами, фазами и двумя профессиями, а не на пустой дефолтной
  базе;
- проверить, что screenshot evidence не содержит старое дефолтное имя или
  runtime-specific упоминания конкретного внешнего исполнителя, включая
  старые `flow-*` ключи и прочие внутренние labels; CLI settings должен
  показывать выбранную wrapper-команду.

Для backend-only тестовых или документационных изменений browser smoke не
обязателен.

## CLI Wrappers

После изменений в CRUD неймспейсов, bootstrap или CLI selector path дополнительно
проверять генерацию пользовательских команд:

```bash
python scripts/install_namespace_clis.py --bin-dir <dir>
```

Скрипт читает неймспейсы из PostgreSQL, создаёт wrapper-команды из
`cli_command`, выставляет `PROJECT_WORKFLOW_NAMESPACE_ID=<id>` и вызывает
только `project-workflow step/history`. `project-workflow` не получает новых
публичных команд: wrapper names являются пользовательской CLI-командой нужного неймспейса.

## References

- [README](../README.md) — launch modes and command overview.
- [Architecture](architecture.md) — runtime and auth boundaries.
- [Live Acceptance](../LIVE_TEST_PLAN.md) — executor-driven E2E evidence.
- [Database Reset](database-reset.md) — clean local Compose baseline.

## Одно frozen Python-окружение

Canonical quality использует `uv run --python 3.11.15 --frozen --all-extras`:
один постоянный project environment, затем pytest/Ruff/mypy через тот же
interpreter. `uv.lock` согласован с версиями общих пакетов `constraints.txt`;
requirements overlay не создаётся. Docker dependency locks и build isolation
сохраняют свои прежние inputs; constraints-only build tools не становятся
зависимостями тестов только из-за присутствия в constraints.

Runner проверяет совпадение общих exact pins и нормализованные дубликаты до
подготовки UV на Python >=3.11 и до первого tool в pinned child. Для launcher
Python3.10 TOML-проверку выполняет pinned3.11 child. Проверка не заменяет
freshness lock относительно pyproject и не доказывает полноту dependency graph.
При сознательном обновлении зависимостей согласовать lock/constraints, сохранив
markers/extras; не возвращать полный constraints как `--with-requirements`.
Пользовательский override prefix сохраняет собственную семантику.

Полезные UV cache и `.local/quality-python/<OS>/3.11.15` сохраняются. Warm run
должен обходиться без повторного install/build неизменившихся packages.
Существующий environment может содержать лишние пакеты: штатный `uv run`
синхронизирует inexact. Не удалять общий cache ради проверки чистого состава;
новое owned environment для qualification проверяется отдельно. Conditional
dependencies сохраняются в universal lock; Windows package count не является
контрактом Linux или всех поддерживаемых Python.
