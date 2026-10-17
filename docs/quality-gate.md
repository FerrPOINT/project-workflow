# Quality Gate

Этот файл фиксирует обязательный локальный quality gate для `project-workflow`.
GitHub Actions в `.github/workflows/ci.yml` сохранён как опциональное зеркало:
job `quality` запускает тесты и статический анализ с PostgreSQL 16, а
`compose-smoke` собирает стек и проверяет `/health`. Для локального выпуска
результаты оплачиваемых hosted jobs не требуются; `[skip ci]` предотвращает
их запуск на push/PR. Перед commit и merge проверки ниже выполняются локально.

Общий лимит hosted job `quality` — 35 минут: он покрывает последовательные
unit/UI и PostgreSQL наборы со статическими проверками. Индивидуальные таймауты
тестов остаются 60/120 секунд, два multi-process E2E — 240 секунд; локальный
порог coverage остаётся 94%.

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
uv run --isolated --with-requirements constraints.txt --all-extras pytest -q --timeout=60
uv run --isolated --with-requirements constraints.txt --all-extras pytest -q -m integration tests/test_postgres_integration.py --timeout=120
uv run --isolated --with-requirements constraints.txt --all-extras pytest --cov=project_workflow --cov-report=term --timeout=60
uv run --isolated --with-requirements constraints.txt --all-extras ruff check .
uv run --isolated --with-requirements constraints.txt --all-extras mypy project_workflow scripts
git diff --check
```

Ожидаемый результат:

- обычный pytest проходит без падений; PostgreSQL integration tests в нём
  показываются как deselected;
- отдельный PostgreSQL integration gate проходит на реальном PostgreSQL;
- coverage остаётся не ниже текущего локального baseline `94%`;
- `ruff`, `mypy` и `git diff --check` не находят ошибок.

На Unix-like окружении тот же набор доступен через `make quality`; на Windows
без `make` используйте `pwsh -File scripts/quality.ps1 quality`. Дополнительные
цели `warnings` и `compose-ready` есть и в `Makefile`, и в PowerShell helper.

### Windows И UTF-8 В Тестовых Subprocess

JavaScript передаётся в Node через stdin с явным `encoding="utf-8"`.
Один `text=True` использует системную кодировку Python и на Windows cp1252
не может передать кириллицу. Не обходить ошибку изменением assertions или
таймаутов. Исправленный `test_editor_failed_save.py` проходит14 случаев даже
при `PYTHONUTF8=0` и locale cp1252, без изменения `PYTHONIOENCODING`.

Локальный полный прогон sourceab3 был остановлен после955 проходов,13 отказов
этого файла и4 skips. Причина13 отказов подтверждена отдельным traceback и
устранена только в четырёх тестовых subprocess-вызовах. Ruff и mypy137 исходных
файлов проходят.

После исправления полный non-PG gate source
`50ae18efebb5f8ffc56c682ce90b1bc5bdb13a41` прошёл:2910 passed,5 skipped,
95 deselected,60 subtests passed,0 failures; coverage94.17% при baseline94%.
Пять skips относятся к optional private Base-source checks и не считаются
выполненными.95 deselected являются отдельным PostgreSQL integration gate,
а не пропущенной частью успешного non-PG результата. Исторический отказab3
не удаляется; текущий non-PG PASS не заменяет PostgreSQL/image/live-приёмку.

## ResourceWarning Gate

После изменений в тестовой инфраструктуре, SQLAlchemy layer, UI request
lifecycle или CLI session lifecycle дополнительно запускать:

```bash
uv run --isolated --with-requirements constraints.txt --all-extras pytest -q --timeout=60 -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
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

### Локальная Квалификация 15 Октября

Все96 PostgreSQL integration cases прошли,0 skipped,0 failures/errors, на
immutable source `188b6bf0ed429293bf75486c2e7363b43777343c`. Включены прежние95
сценариев и новый side-by-side adoption текущего семейства7be/999 поверх
сохранённых legacy rows/history, с повторной установкой и readback persisted IDs.
Тестовый/production closure интегрированного `82b3e7a` идентичен этому source;
дополнительное отличие относится только к документации результатов non-PG gate.

Использованы frozen Python3.11/uv dependencies и закрытый PostgreSQL без host
ports. Base-v2 project `sdlc-qa-workflow-preservation-0837242884ae` и собственные
disposable ресурсы очищены; evidence сохранено. Controlled OpenAI-compatible
HTTP peer в тестах не является live model, installed catalog или семиролевой
SDLC/deployment приёмкой. Production dependencies, catalog и manifest не менялись.

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
