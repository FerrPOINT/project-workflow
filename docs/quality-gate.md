# Quality Gate

## Дефолты фоновых профессий — 2026-11-09

Холодный platform bootstrap теперь создаёт девять профессий: семь прежних
стадийных и две фоновые. Только семь входят в sealed single-task installation;
её bindings, восемь режимов и 33 фазы не расширяются фоновыми стадиями.
В пустой БД активный каталог содержит девять workflow, десять режимов, 43 фазы
и не создаёт задач. Версионирование фоновых workflow сохраняет первые редактируемые
строки как историю и создаёт неизменяемую опубликованную редакцию: физически
хранятся 12 режимов и 53 фазы. Исторические результаты первоначальных дефолтов
относятся к прежней модели без публикаций; их evidence сохраняется.
Standalone по-прежнему не заполняется неявно.
Регрессии повторной/конкурентной инициализации проверяют оба inventory отдельно.

Git-экспорт для QA обязан сохранять байты и Unix modes: на Windows использовать
`git -c core.autocrlf=false archive`, извлекать tar в Linux либо восстанавливать
исходные executable modes. Синтетические Git hooks требуют исполняемого scratch.
Два архивных отчёта v18 записаны с CRLF и закреплены их исходными raw SHA-256;
точечные `-text` attributes сохраняют эти байты. Значения хешей и JSON-содержание
не пересчитываются ради проверки.

Ошибка глубины JSON проверяется управляемым `RecursionError` декодера, аналогично
ошибке разбора provider envelope: поддерживаемая глубина зависит от сборки Python.
Проверки технического результата, отсутствия продвижения, единственного вызова и
отсутствия повторов сохранены. Предметный лимит глубины или длины не добавляется.

Основной gate coverage остаётся 94%. Сбор coverage у целевой регрессии сам по себе
не является прохождением общего порога; объединять можно только datasets с теми
же исполняемыми исходниками и отдельно проверять общий отчёт.

Этот файл фиксирует обязательный локальный quality gate для `project-workflow`.
GitHub Actions удалены из репозитория. Все обязательные проверки выполняются
локально штатными командами ниже; workflows и обновления Actions не добавляются.

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

Optional HTTP transport должен поддерживать `max_response_bytes`, `trust_env` и
структурированный `ApiError`; совместимый baseline — Base
`64c960464205edae6d85d5f297c1ae6b99ae0371`. Квалифицированный producer ниже
содержит этот baseline; SDK/UI/skills pins ради окружения не меняются.

Для тестов configured CLI нужен отдельный квалифицированный Base producer
`25b0b2aafaa9feaa854ca86f11043ff825842229` (`workflow-cli-base-source`).
Этот producer добавляет явный token-free loopback transport для standalone;
платформенный transport по-прежнему требует PAT.
SDK checkout по `.base-revision` остаётся независимым: его старый `ApiClient`
не поддерживает `max_response_bytes`. Глобально установленный `pdlc_cli_core`
не является воспроизводимой зависимостью isolated uv-окружения.
Подготовить второй checkout один раз, не переключая SDK:

```bash
git clone --no-checkout --depth 1 https://github.com/FerrPOINT/services-base.git ../workflow-cli-base
git -C ../workflow-cli-base fetch --depth 1 origin 25b0b2aafaa9feaa854ca86f11043ff825842229
git -C ../workflow-cli-base checkout --detach 25b0b2aafaa9feaa854ca86f11043ff825842229
export WORKFLOW_CLI_BASE="$(cd ../workflow-cli-base && pwd)"
test "$(git -C "$WORKFLOW_CLI_BASE" rev-parse HEAD)" = 25b0b2aafaa9feaa854ca86f11043ff825842229
test -z "$(git -C "$WORKFLOW_CLI_BASE" status --porcelain --untracked-files=all)"
export PYTHONPATH="$WORKFLOW_CLI_BASE/base-modules/python/cli-core${PYTHONPATH:+:$PYTHONPATH}"
```

После этих проверок выполнять команды ниже или `make quality` в той же shell.
В PowerShell `scripts/quality.ps1` сам проверяет SHA/чистоту и добавляет core в
`PYTHONPATH` перед test/integration/coverage/warnings; по умолчанию использует
sibling `../workflow-cli-base`. Другой готовый exact checkout задаётся через
`WORKFLOW_CLI_BASE` или `-CliBase`:

```powershell
pwsh -File scripts/quality.ps1 quality -CliBase C:/sources/workflow-cli-base
```

CI получает тот же CLI producer вторым checkout и передаёт его `cli-core` через
job `PYTHONPATH` всем isolated uv-процессам, включая integration/subprocess tests.
`.base-revision`, `.base-ui-revision`, продуктовые зависимости и runtime не меняются.
Целевая проверка настройки без полного gate:

```bash
uv run --isolated --with-requirements constraints.txt --all-extras pytest -q tests/test_configured_cli_transport.py --timeout=60
```

```bash
uv run --isolated --with-requirements constraints.txt --all-extras pytest -q --timeout=60
uv run --isolated --with-requirements constraints.txt --all-extras pytest -q -m integration --timeout=120
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

Configured CLI/HTTP/PostgreSQL E2E также явно запускает дочерний Python с
`-X utf8`, поскольку subprocess читает и передаёт UTF-8. Настройка родительского
интерпретатора не наследуется как флаг дочернего. Без этого Windows cp1251
формирует JSON, не соответствующий указанному reader encoding; это ошибка
подготовки test transport, а не PostgreSQL. Два адресных сценария проверяют
сохранение кириллических отчётов, replay без дубликатов и отсутствие workflow
файлов. При повторе исходные failures сохраняются отдельно; неизменные130
integration cases не запускаются повторно.

После исправления полный non-PG gate source
`50ae18efebb5f8ffc56c682ce90b1bc5bdb13a41` прошёл:2910 passed,5 skipped,
95 deselected,60 subtests passed,0 failures; coverage94.17% при baseline94%.
Пять skips относятся к optional private Base-source checks и не считаются
выполненными.95 deselected являются отдельным PostgreSQL integration gate,
а не пропущенной частью успешного non-PG результата. Исторический отказab3
не удаляется; текущий non-PG PASS не заменяет PostgreSQL/image/live-приёмку.

### Квалификация общего UI — 24 октября 2026

Следующий полный non-PG прогон для переноса общего UI прошёл без отказов тестов:
3315 passed, 5 skipped, 120 PostgreSQL deselected, 97 subtests passed. Он включал
ResourceWarning и PytestUnraisableExceptionWarning как ошибки. Отдельный
Pydantic UnsupportedFieldAttributeWarning сохранён в отчёте; это не ResourceWarning.

Первичный raw line coverage составил 93.99660912453761%. При precision=0
pytest-cov завершился с кодом 0, хотя текстовый отчёт сообщил недостаточное
покрытие. Такой результат не считается прохождением порога. Теперь precision=4,
а fail_under=94 не изменён: результат ниже порога больше не округляется в PASS.

Добавлены четыре проверки реальной границы human display window: остаток меньше
1 ms отклоняется, достаточное малое окно сохраняется, при включённой и выключенной
application policy. Ещё три проверки используют действующий coverage predicate
и подтверждают отказ непосредственно ниже 94%. На неизменных 136 application
Python-файлах к копии полного coverage dataset добавлен только этот набор из
семи PASS. Итог — 12199 из 12976 statements, raw coverage 94.01202219482121%.
Первичный dataset сохранён отдельно; полный набор повторно не выполнялся.

Это 3322 уникальных non-PG cases и отдельный coverage proof; пять skips не
засчитываются как выполненные проверки. PostgreSQL 120, authenticated UI,
image/runtime и hosted CI этим результатом не подтверждены. UI producer
`2e13224836dda29ae863db407866ee2e6ae8bb42` экспортирует те же SSR bytes, что
предыдущий `15182d57`; штатная проверка fingerprints прошла. Новая browser-only
функция скачивания Blob не меняет Python/runtime и не требует повтора non-PG.

### Дополнение: полный PostgreSQL-срез того же кандидата

Реальный PostgreSQL 16.15 из существующего образа
`sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea`
подтвердил 114 cases основного модуля за 380.95 s. Пять дополнительных
admission/clock cases прошли сразу; один выявил дефект observer в тесте row wait.
Тест читал `pg_stat_activity` в одной транзакции и сохранял первый снимок,
так что настоящий waiter мог остаться невидимым. Только observer переведён в
AUTOCOMMIT согласно [модели статистики PostgreSQL 16](https://www.postgresql.org/docs/16/monitoring-stats.html#MONITORING-STATS-VIEWS).
Срок proof 0.6 s, ожидание истечения, требование реальной блокировки, SQLSTATE
42501 и проверка сохранности исходных данных не изменены.

Адресный повтор row-wait и соседнего deferred-COMMIT дал 2 PASS. Совокупный
результат — 120 уникальных integration cases, без skips; повтор соседа не
прибавляется к числу уникальных tests. Application Python не менялся, поэтому
исходные 114 не запускались повторно. Отказ первого observer сохранён отдельно.

Существующие Make, PowerShell и CI manual entrypoints теперь выбирают marker
`integration`, включая три модуля. Проверен actual PowerShell launcher на границе
native uv process: выбор всех integration и передача exit 0/9. Изменённый
документационный regression case прошёл; Ruff прошёл. Hosted CI не запускался.

Каждый прогон использовал собственный временный PostgreSQL на loopback,
512 MiB memory/memory+swap, 1 CPU и pids128; native launcher ограничен двумя
CPU affinity bits. OOM не было, контейнеры удалены. Это лимиты и isolated source
proof, а не потребление установленного приложения. Общие БД, runtime, credentials,
dev и production не использовались. Authenticated browser-проверка UI кандидата
остаётся открытой; успешная интеграция не заменяет визуальную приёмку.

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

Ручные `test-integration` и CI workflow_dispatch выбирают все tests с маркером
`integration`, без ограничения одним файлом. Срез кандидата содержит 114 cases
основного PostgreSQL-модуля, пять project-admission cases и один application-clock
case. Последние шесть не должны выпадать из gate при выборе старого файла.

Application-clock case требует явный `WORKFLOW_APPLICATION_CLOCK_TEST_URL` к
отдельной пустой QA-базе с точным именем `request_clock_fixture`; обычная
runtime-БД отклоняется. В CI эту базу создаёт manual step внутри свежего
PostgreSQL service. Для локального запуска её готовит владелец изолированного
QA-окружения; не создавать её автоматически в общей установленной БД.
Без URL тест явно пропускается, и такой skip не подтверждает COMMIT-clock gate.

Основной модуль `tests/test_postgres_integration.py` проверяет реальный путь CLI
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
только `project-workflow step/history`. Этот генератор не создаёт отдельные
подкоманды для каждой профессии: wrapper names являются пользовательскими
ярлыками существующих команд в нужном неймспейсе.

## Background Integration Qualification, 2026-11-14

Production tree `bf66b6eba109bc9575374e20f85f4b1376ac5def` is unchanged from
`24aad5d`. Its owned PostgreSQL baseline passed 217 cases, including the nine
background catalog cases. The missing application-clock case subsequently
passed on `b9564ac` with its own `request_clock_fixture`: 218 cases qualified
in total, with unchanged production inputs and verified owned cleanup.
Ruff and mypy pass.

The original non-PostgreSQL run records 5003 passed, four failed and 15 skipped,
with 93.9025% coverage. Test-only corrections retain the current forward-only
barrier and verify its unchanged schema/history. Programmatic migration tests
now exercise the actual Engine and caller-owned Connection instead of counting
internal Alembic calls. The Connection case prepares historical SQLite batch
DDL through the Engine before testing the new data-only join.

The four repaired cases, 11 existing background cases and 21 new negative cases
pass together: 36 passed. The new cases check foreign identity/publication,
changed custody, stale versions, missing conclusions, invalid history selectors
and canonical operation keys, with unchanged stored rows and valid neighboring
reads. Appending this scoped non-PostgreSQL run to the unchanged-production
baseline yields 13675/14547 statements, **94.0056%**, above the unchanged 94%
gate without new exclusions. This is composite evidence, not a new full run.

Three real pinned Base package cases also pass with controlled HTTP/SQLite
peers. Actual OpenAPI exporters match the tracked seven-path runtime and
one-path binding snapshots byte-for-byte after newline normalization; the
binding exporter removed one extra terminal newline. The full generated schema
contains 47 paths. All eleven committed Python Playwright browser cases passed
on `c3a973b`, with zero skips and unchanged source, using controlled HTTP/SQLite
peers and Chromium 1208. The POSIX executable-mode case also passed on Linux
on `e8de52a`, using an exact Git export, the unchanged Base QA tools recipe and
disposable scratch. All fifteen original non-PG skips now have passing receipts.

See [compact source evidence](evidence/background-v1-source-20261114.json).
Exact-artifact installation and real-agent acceptance remain
separate checks; these controlled evaluator/SQLite tests do not prove them.

## References

- [README](../README.md) — launch modes and command overview.
- [Architecture](architecture.md) — runtime and auth boundaries.
- [Live Acceptance](../LIVE_TEST_PLAN.md) — executor-driven E2E evidence.
- [Database Reset](database-reset.md) — clean local Compose baseline.
