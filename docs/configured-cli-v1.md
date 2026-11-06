# Единый CLI/API Workflow

## Analyst Research: coordinated instruction revision

The single-task Analyst still has three phases: research approved PM input and
internal/public sources; analyze rules/scenarios/acceptance; produce one analysis.md
and use the existing accepted-report/comment/proposal sequence. It does not conduct
a second PM interview or request owner consent for the analysis. It never returns
the task to PM. Contradictions and missing facts stay in this task's analysis;
missing mandatory facts keep the analysis unfinished.

The Analyst allowlist additionally permits wiki-operator and forge-operator from
the reviewed Base package. The identity donor and its historical catalog are not
rewritten. Migration `0024_analyst_research_catalog` upgrades an exact sealed native
catalog and keeps task IDs, phase IDs, reports and previous profile artifacts.
Partial or customized catalogs fail transactionally instead of being overwritten.
Migration `0027_analyst_no_pm_return` removes the Analyst PM-review instruction
without rewriting saved tasks, reports or historical profile artifacts.
Published migrations remain unchanged. Other professions keep their modes
and allowlists. PM instructions verify the immutable Backlog/Ready completion while
allowing fresh Tracker context to show the automatically queued Analysis.

This source revision requires coordinated Tracker/Fleet/Base qualification; it is
not an activation or live acceptance record.

Срез реализации `a32f110d` содержит новый каталог 0027. CLI и сервер должны
поставляться из согласованного среза: прежняя проверка CLI `bace3fee` / server
`a002eaf0` не подтверждает совместимость с новым manifest. Полный прогон дал
3298 passed и три падения тестовых ожиданий; после исправления эти три теста
прошли отдельно. Покрытие 94.068%, Ruff, mypy, navigation и четыре проверки
миграции/истории на настоящем PostgreSQL прошли. Это результаты прежнего среза.
При последующем совмещении с `master` (`c715a032`) сохранены evaluator v15,
структурированный отчёт `source`/`result`/`unresolved` и историческое чтение v10
наряду с остальными поддержанными версиями. Клиент и сервер поставляются вместе;
старый plain-text отчёт не заменяет требуемый JSON. Проверка миграции теперь явно
охватывает сохранение checks/evidence IDs при переходе 0026 → 0027.
PR остаётся Draft, живая приёмка учитывается отдельно. Версии и открытые пункты:
[совместная поставка Base #443](https://github.com/FerrPOINT/services-base/pull/443).

В объединённом offline-прогоне прошли 3840 tests; два падения ожиданий исправлены
и перепроверены по затронутым файлам: 24 PM-contract tests и один AST-baseline test.
Прежние контрольные хеши canonical parser сохранены: нормализованы только пустые
поля AST, представление которых зависит от версии Python. Baseline шести non-PM
workflows учитывает согласованный каталог Analyst. Покрытие 94.2912%, Ruff, mypy
(171 source files) и navigation прошли. PostgreSQL, реальные агенты и модель
в этой доработке не запускались.

## Общий контракт

Source-контракт для семи профессий и восьми режимов. Установка, полный gate и
живая приёмка подтверждаются отдельно. До переключения должны быть удалены
оставшиеся старые исполняющие маршруты и завершены прежние активные попытки.

Source-кандидат диагностики advisor использует prompt v16 и opt-in
`project-workflow --json history --task <key> --diagnostics --n 1`.
Точная запись входов, попыток и причин не вызывает модель повторно и не меняет
вердикт. Подробности и ограничения: [диагностика](evaluator-diagnostics.md).
Это не установленная версия и не устранение всех ложных PARTIAL.

Workflow хранит фазу, оценку отчёта и историю. Tracker владеет назначением,
требованиями, комментариями и атомарными переходами. Fleet проверяет реальный
terminal процесса. Native run ID не является идентичностью задачи Workflow.

## Installed v12 Checkpoint 2026-10-31

Source `fb983944b1b3a393ff1b8946f66c674e03f2abb2` установлен normal Workflow-only
Apply **COMPLETE** `82089f04ed294324a5d4b820a71a4884`. Image
`sha256:39d33eebd591a97404c6e351087c5dd695d72a1e191d7540928bae21fc910ba1`,
container `22a64cc52c4e9a6a155379941c62185a697ea12d1354427c5fc006b9bd8fa5ee`;
actual readback показывает `supervisor-evaluator-v12`, health/database/schema/catalog
OK. Fleet backend не изменён. Catalog7/hash
`0434499f6baa99ff71e3e92cc6b46d7262c98f30bd4edcd3f72f503c432e3da3`
оставался active во время Apply; старый SDLC-15 CLI history byte-equivalent, version6.

Ранее опубликованный PM artifact принят штатным API как catalog10, normalized hash
`ae220f915d33987f1ed9b13e39d9a4c3a82ea5d8db133638a6a06f384ae249ef`.
Три фазы сокращены до контекста, подготовки требований и отдельного owner consent.
Техническую identity/namespace/access проверяет сервер; PM не пересказывает все
API-поля и не просит владельца повторно заверять настройки. Counts/scopes/skills
не изменены, инструкции14632 ->5868 символов. Семь scoped tests/Ruff pass; новый
код или образ не требуются. Full-brief SDLC-22 завершена PM самостоятельно:
context130/preparation131/terminal135 PASS, req1/hash898f7e7e, separate owner
receipt853d9814, actual Backlog/Ready. Независимый read-only PG подтверждает
owner/hash и ноль Analyst/Analysis. Final PARTIAL132-134 исправлены самим PM,
без технических подсказок; эта задержка не выдана за устранённую нестабильность.
Sparse SDLC-23 завершена в Backlog/Ready: revision3, отдельное точное owner
confirmation, terminal PASS163; независимый PG подтверждает owner/hash и ноль
Analyst/Analysis. Лишние PARTIAL5/12/8 сохраняются как открытый дефект качества.
Fleet initial POST replay после completion даёт409 на прежней установке;
исправление проверено в исходниках, но ещё не принято на стенде.
Текущий artifact в репозитории имеет hashba81253 и пока не опубликован;
кандидат evaluator v15 также не установлен. Новые результаты и открытые gates:
[публикация и приёмка](managed-catalog-publication.md).
SDLC-21 на9 сохранил PARTIAL128 с лишним namespace attestation, без подмены фактов.

Предыдущая редакция9, normalized hash
`a85f4a78d79aa28efd5e577db24b5eb7a204cccff54b8ad6352a3ee9b37f4209`.
Фаза3 называется Owner-confirmed requirements, без legacy "before final Workflow
report". Check5 проверяет конкретные разделы спецификации, а не принятие текущего
отчёта. Catalog8/hashbd0e6d6e и SDLC-20 сохраняются: требования1 и exact owner
consent существуют, но PARTIAL120-125 повторно требовали будущего принятия отчёта.
Его последний run штатно остановлен, Fleet terminal cancelled подтверждён.
Phase02 достаточно actual publication/readback data с той
же revision/hash и одной FULL копии документа: полные raw CLI JSON дубли и stdout
attestation не требуются. Checks1-4, actual presentation, owner/identity guards и
инструкция реального Workflow -> Tracker completion/readback сохранены.
Publication operation readback и active hash совпадают. Семь scoped регрессий9
проходят с synthetic peers; начата NEW full-brief QA, sparse и реальные
Backlog/Ready результаты ещё не приняты. Код/образ при публикации не менялись.

v12 исключает только собственный submission/read-verdict/terminal-receipt отчёта
из precommit evidence. Business commands/results, required external readbacks,
FULL content, exact owner confirmation и fingerprint/coverage guards сохраняются;
исторические v11 terminal receipts читаются без переоценки. Auto-PASS нет.

Фактическая локальная квалификация source `fb983944`:

- Targeted main: **159 passed**. Worker119 и четыре frozen-proof случая
  перекрываются с этим набором; их нельзя прибавлять к159. Ruff all и mypy
  **165 source files PASS**.
- Full non-PG: **3193 passed, 73 subtests passed, 15 skipped, 132 deselected**;
  line coverage **94.02997164844066%** при пороге94%. JUnit `tests=3281`
  включает73 subtests и15 skips, это не3281 passed. Skips:11 Playwright,
  3 explicit private-package opt-ins,1 NTFS executable-mode; не выполненные gates.
- Dedicated PostgreSQL: **132 passed, 0 skipped/failures/errors**. Обе собственные
  БД, включая отдельную пустую clock fixture, использованы; cleanup и scratch
  cleanup true. Все53 pins сохранены, source head unchanged в обоих receipts.
- Exact-image smoke: fresh `0023_catalog_publication_author`, health/DB/schema/catalog
  OK,45 HTTP OpenAPI paths/6 catalog operations, PASS и cleanup `cleaned`.
  Этот QA receipt отдельно фиксирует `installed=false` и не заменяет Apply receipt.

Локальные receipts под evidence root интегратора, указанным ниже:
`evidence/workflow161-v12-bb3522b670/result.json`,
`pm-runtime-recovery-20261030/workflow-precommit-install.json`,
`pm-runtime-recovery-20261030/verifier-v12-qualification-20261031/{pg,full}.json`
и `full.log`. Данные runtime/credentials и raw business transcripts не публикуются.

Live checkpoint: SDLC-18 сохраняет ту же task/execution, req1/hash
`0a36da8cb4e9e2c6493427dc1fb37e3000f8f0af9c1e63076de3865169aed52d`
и actual owner receipt. v11 final history106 ошибочно требовал собственный будущий
submission result; normal Stop подтверждён native cancelled. После установки v12
обычное продолжение дошло до history115 PARTIAL: final check требовал readbacks
ещё не существующих completion operations как negative absence proof.
**Tracker Backlog / Ready НЕ принят**. Sparse SDLC-19 дал первый полезный вопрос,
requirements ещё нет. QA18/19 сохраняются на catalog7 без переписывания истории;
следующая приёмка выполняется на NEW задачах после отдельной публикации9. Это не модельная
приёмка по mocked tests или historical assisted PM13. Full/sparse business results,
семь ролей/Rework, Kubernetes, rollback и остальные release gates отдельно открыты.

## Настройка агента

Владелец конфигурации заранее задаёт `PROJECT_WORKFLOW_URL`,
`PROJECT_WORKFLOW_API_TOKEN`, `PROJECT_WORKFLOW_NAMESPACE_ID`, `FLEET_AGENT_ID`.
PAT принадлежит служебной identity, секреты в Fleet задаются через `secret_ref`.
Адреса и credentials не создаются для каждого сообщения. CLI использует общий
Base `pdlc_cli_core`; явный токен не подменяется глобальными aliases.
Отсутствующий доступ запрещает вызов без обращения к локальной БД.

| Профессия | Режим | Текущая стадия Tracker |
| --- | --- | --- |
| Project Manager | draft | Draft; Backlog только для чтения/повтора завершения |
| Analyst | analysis | Analysis |
| Architect | decomposition | Architecture |
| Developer | initial / rework | Development / Rework |
| Reviewer | delivery | Review |
| Tester | delivery | Testing |
| DevOps | delivery | Deployment |

Ключ `SDLC-N` берётся из `task-tracker sdlc context --task <Tracker-UUID>`,
поле `workflow_task_key`. Его нельзя вычислять из номера задачи или native run.
Профессия и режим определяются установленным каталогом и проверенным назначением.

`workflow_key` выбирает воркфлоу из коллекции назначенной профессии; запуск не
привязан к её прежнему полю дефолтного воркфлоу. Режим должен существовать в выбранном
воркфлоу и соответствовать назначению. Для встроенного `single-task-v1` дополнительно
проверяются sealed hashes каталога. Пользовательские воркфлоу используют тот же
CLI/API и те же проверки доступа, назначения, версии и повторов.

Миграция `0021_profession_task_workflows` убирает только старую привязку сохранённой
задачи к дефолту профессии. Идентификаторы, отчёты и коллекции не переписываются.
Проверка текущей принадлежности остаётся на границе исполнения. После удаления
воркфлоу из коллекции новый шаг запрещён, но прежняя авторизованная история читается.

## Служебный доступ

Central Auth проверяет service-account PAT заново для каждого запроса, включая
повтор enrollment и чтение сохранённого receipt. Развёртывание регистрирует UUID
контроллера и его профессию в `PROJECT_WORKFLOW_BASE_READER_SUBJECTS_JSON`.
Регистрация subject не заменяет scope: enrollment требует `project-workflow:write`,
история и receipt — `project-workflow:read`. Read-only контроллер не создаёт
назначение; каталог имеет отдельную роль `catalog`. Старые карты opaque role tokens
не читаются. Агент без регистрации контроллера читает только собственное проверенное
назначение. Отзыв PAT запрещает чтение; изменение текущего бизнес-состояния не
переписывает сохранённый terminal receipt.

Для чтения Tracker Workflow использует отдельную постоянную service-account
identity с единственным scope `task-tracker:read` и явным доступом к проекту.
Её credential не принадлежит PM и не даёт прав выполнять работу за агента.
Параметры: `PROJECT_WORKFLOW_CONFIGURED_TRACKER_URL` и
`PROJECT_WORKFLOW_CONFIGURED_TRACKER_READ_TOKEN`. Один этот read-only канал
проверяет назначения всех профессий, а не только Project Manager.

## Команды

API-контракт генерируется из действующих моделей и маршрутов:
`python -m scripts.export_runtime_openapi`; проверка совпадения — с `--check`.
Результат: [runtime-openapi.json](runtime-openapi.json). Старый
`pm-continuation-openapi.json` сохраняется как исторический снимок.

```sh
project-workflow --json step --task <workflow-task-key>
project-workflow --json step --task <workflow-task-key> --operation-key <stable-key> --expected-version <version> --report -
project-workflow --json history --task <workflow-task-key> --operation-key <original-key>
project-workflow --json history --task <workflow-task-key> --n 100
project-workflow --json history --task <workflow-task-key> --before-history-id <next_before>
```

Отчёт поступает текстом или на stdin. Чтение фазы не меняет версию. Запись требует
ключа, точного payload и ожидаемой версии. Повтор возвращает исходный сохранённый
ответ; другой payload с тем же ключом конфликтует. При неизвестном HTTP-результате
сначала читать исходную операцию. `next_before=null` означает конец истории;
нельзя считать первую страницу полным набором предыдущих результатов.

`--runtime-request`, `--execution-token-file` и файловый bootstrap отсутствуют
в агентном CLI. HTTP-ошибка не включает скрытый переход к БД, новый ключ или retry.
При ошибке после отправки записи `acceptance_unknown=true` требует readback.

## Назначение и продолжение

Fleet использует существующий `POST /internal/runtime/assign` со служебным
assignment-токеном соответствующей профессии. Агент не назначает себя.
Закрытый payload `ConfiguredAssignment` содержит protocol, task, namespace,
workflow/mode/role, operation key, assignment/execution/version Tracker,
конкретного агента, machine subject, business task/root UUID, owner и Workflow CAS.

Перед принятием назначения, чтением и отчётом Workflow сверяет актуальный context
Tracker. Служебное чтение context проверяет также текущие проектные права
назначенного producer; права самого reader их не заменяют. После оценки моделью
назначение, версия и права проверяются повторно перед commit.

Новое разрешённое назначение продолжает незавершённую фазу. После завершённого
режима новое назначение может начать следующий цикл, включая Developer rework.
Первоначальный enrollment result хранится для исходного operation key.
Tracker assignment version и Workflow cursor version — разные счётчики.

Исторический single-task assignment допускает только чтение и явное принятие
новым проверенным назначением с текущим CAS. Его payload/hash и custody должны
совпадать; старый native fence не сравнивается с новой версией Tracker.
История и прежние assignment rows сохраняются. Это не разрешение продолжать
прежний native run: его безопасное завершение обязательно до переключения.

## Принятие отчёта и бизнес-завершение

`--report -` читает обычный TEXT/Markdown из stdin; `--json` задаёт формат вывода,
а не JSON envelope отчёта. JSON на stdin у отдельных команд Tracker остаётся
их собственным mutation-контрактом. Отчёт содержит фактические результаты и
evidence текущей фазы, а не инструкции вместо выполненной работы.

Контракт фазы содержит текущую работу и уже существующие evidence. Он не требует
собственного будущего receipt, ещё не опубликованного комментария или будущего
перехода статуса. Reviewer/Tester могут полностью выполнить проверку и вернуть
бизнес-результат rework; это не означает принятие дефектного кандидата.

Evaluator `supervisor-evaluator-v12` сохраняет строгий LLM verdict, но учитывает
достаточность evidence, явно заданную контрактом. Если фактические скопированные
readbacks и сверка identity достаточны, отдельная attestation запуска команды
не требуется. Если контракт не требует независимого presentation receipt или
transcript, полный сохранённый документ, matching saved confirmation настоящего
владельца и конкретное описание фактического показа могут быть достаточны.
Намерение показать документ не равно показу; summary не заменяет FULL content.
Отсутствующий или несовпадающий consent, ошибочные команды, identity mismatch
и противоречия остаются недостаточными evidence. Нет auto-PASS или обхода LLM.
Собственный submission и чтение будущего verdict/receipt текущего отчёта являются
report protocol, а не работой/evidence до этого verdict. Это не освобождает от
бизнес-команд или внешних readbacks, уже требуемых контрактом текущей фазы.

У финального PM отчёта обязательны `--requirements-revision` и
`--requirements-sha256`. Tracker должен подтвердить последнюю полную редакцию,
точный hash, владельца и его настоящий consent до оценки и перед commit.
Ожидание ответа оставляет фазу незавершённой, без native rebind/checkpoint.

Принятый terminal ответ хранит три отдельные части:

- `terminal_receipt`: неизменная идентичность принятого результата;
- `workflow_receipt`: соседнее поле `{reference,sha256}`, не вложение terminal receipt;
- `completion_instructions`: действия после commit.

Агент публикует проверяемый обычный итоговый комментарий текущего назначения и
редакции, читает его operation receipt, затем выполняет разрешённый Tracker CLI.
Редактирование/удаление комментария блокирует новую передачу. Tracker проверяет
сохранённый Workflow receipt server-to-server через существующий
`POST /internal/runtime/terminal-receipt/readback`, а не доверяет вставленному JSON.

PM вызывает `sdlc pm completion submit`; исторический receipt сохраняет
Backlog / Ready. Для включённого single-task проекта Tracker атомарно ставит
Analyst в очередь Analysis / Ready; актуальную стадию читают из context задачи.
Техническая роль публикует typed result с ключом
`delivery-result:<assignment_id>` и завершает run; Fleet проверяет реальный
terminal и ресурсные доказательства перед Tracker Complete. Исправленный кандидат
повторно проходит Review и Testing. Ни принятый отчёт, ни proposal сами не переходят стадию.

Analyst не возвращает задачу PM. При критическом бизнес-возврате другой роли
PM читает `critical_review` из актуального context
Tracker и сверяет выбранный blocker, его версию/hash и исходную редакцию.
Используются те же фазы, CLI и точное новое подтверждение владельца. Обычное
системное сообщение Fleet не содержит второй копии инструкций. Завершение
атомарно разрешает blocker; дальнейший переход определяет Tracker по актуальной
конфигурации проекта.
Этот путь требует PostgreSQL и живой квалификации вместе с остальным кандидатом.

Отдельный [ручной сценарий и бизнес-оракул](../manual/configured-workflow-proof/README.md)
расположены вне обычной suite. Оракул проверяет фактический установленный сервис;
прохождение всех профессий, происхождение артефакта и native terminal требуют
собственных доказательств. Сценарий не помечен выполненным по наличию исходников.

## Каталог и переход данных

`load_single_task_professions` собирает единственный канонический набор фаз;
сборщик профиля только добавляет происхождение и hashes. Подмена инструкций
во время исполнения отсутствует. Base хранит общие role/CLI инструкции.

Forward-миграция `0020_configured_cli_catalog` заменяет только полный известный
sealed каталог. Частичная установка или пользовательские изменения блокируют
миграцию без переписывания данных. Сохраняются task/phase IDs, отчёты, assignment
rows и migration ledger. Предыдущие manifest/catalog сохраняются byte-exact в
`references/retained`; применённые миграции не редактируются.

Обычный unit/static gate не запускает живой Hermes. Ручной all-role/Rework прогон
PDLC1, PostgreSQL на заполненной и новой БД, упакованные CLI, происхождение
установленного образа и rollback остаются обязательными отдельными проверками.

## Scoped PM13 Evidence 2026-10-30

Исторический checkpoint: это отдельные уровни доказательств, не один общий gate.
Текущий v12 checkpoint приведён выше. Product/test source этого результата
зафиксирован на `861e08c028985ff4cf717cabf9be98d0c60a42d0`; последующее
документирование не меняет его, pins или установленный образ.

- Source: `python -B -m pytest -q tests/test_llm.py tests/test_supervisor_reliability.py --timeout=60 -x`
  дал **113 passed in 21.04s**. Это mocked evaluator и synthetic SQLite fixtures,
  не реальный LLM/PG. Ruff, scoped mypy `llm.py`, diff/hygiene прошли;
  все 53 dependency pins совпали. Полный suite/coverage/PG заново не выполнялись.
- Exact image:
  `sha256:5f25de5fc2d9f960a70a4d18bb35d1f8e531e7b07e57c181d3f143cbfe3f45c7`.
  Отдельная QA на свежей БД прошла startup/migrations до
  `0023_catalog_publication_author`, health database/schema/catalog и HTTP OpenAPI
  (45 paths, 6 catalog operations); cleanup `cleaned`. Этот QA result сам
  фиксирует `installed=false`, `live_publication_accepted=false`: это не live proof.
- Установка подтверждена отдельно: normal Workflow-only Apply
  `b32727db1be04068a2ae1fb10232fdb7`, journal phase `complete`.
  Fleet/Hermes для этого evaluator fix не пересобирались.
- Реальный LLM/CLI: SAME synthetic PM13 / `SDLC-13`, Tracker task
  `01a18d7d-0d40-7452-8030-659cbe8b00cb`, Workflow execution
  `29cc7a4f-adf0-46bd-ab5a-337c24c43973`, namespace/workflow `2`,
  published catalog v3 / mode `22`. После установки v11 final history `70`
  вернул `PASS`, `complete=true`, cursor `23`, status `done`; старые PARTIAL
  и предыдущие попытки сохранены, не переименованы в успешные.
- Tracker CLI завершил PM в Backlog/Ready. Независимый read-only PG snapshot
  только этой task подтвердил revision `1`, `exact_owner_confirmation=true`,
  одинаковый requirements/confirmation hash
  `edceaf25fe74411c9ba2f6cad148c3d7eee5f8723c9d28827498d58e1e26f8c1`
  и `analyst_assignments=0`, `analysis_intents=0`, `analysis_lifecycle_rows=0`.

Это **assisted core-path acceptance** существовавшего task/execution: оператор
помогал с evidence/presentation, владелец реально прочитал полный документ
и сохранил точное подтверждение. Это не fresh unassisted acceptance и не
доказательство, что одной смены prompt достаточно для всех модельных ответов.
QA11/12 не объявляются успешными. Семь ролей/Rework, все release gates,
Kubernetes, rollback и другие задачи этим результатом не квалифицированы.

Локальные evidence интегратора находятся под
`C:/git/azhukov/sdlc/.local/single-task-sdlc-20261013/phased-agent-release-20261029/`:

- `evidence/workflow161-73b4f1bba1/result.json` (QA only), raw SHA256
  `0d06c78b35bc1c4853856925b10185a7e775294804bf39729cc89bc6096206f8`;
- `pm-runtime-recovery-20261030/synthetic-pm-v3-workflow-history.json`
  (same execution, final history70);
- `pm-runtime-recovery-20261030/synthetic-pm-v3-tracker-verify.json`
  (independent task-scoped PG readback), raw SHA256
  `093d667d92ceaf6929f5024ea316efd8361d35196be28a4facbc03a1b9258c71`.

Apply journal хранится отдельно под
`services-base/deploy/.local/workspace-updates/b32727db1be04068a2ae1fb10232fdb7/journal.json`
основного workspace. Секреты, runtime DB и raw transcripts не публикуются
в репозитории; исходные evidence не редактируются ради документации.

## Локальный gate PR #161, 2026-10-31

Исторический source861/7c gate, не результат нового v12 source `fb983944`.
Актуальная полная квалификация v12 приведена выше; старые результаты сохранены.

На head `7c771c9736a5147752f41c39626275d380e096eb` product/test trees
совпадают с source861 и результатом read-only merge с текущим `master`.
Полный non-PG прогон: **3183 passed, 73 subtests passed, 15 skipped,
132 deselected**; неокруглённое line coverage **94.03807209396517%** при пороге
94%. Skips: 11 требуют Playwright, 3 — opt-in private package, 1 — Git executable
bit, который NTFS не представляет. UI этим evaluator diff не изменяется.
Ruff проходит; mypy проверил 165 source files. Все 53 dependency pins сохранены.

На отдельном PostgreSQL 17.6 полный integration-прогон дал **131 passed,
1 skipped**. Последний тест request clock отдельно прошёл с явным URL собственной
пустой `request_clock_fixture`: **1 passed**. Оба временных Compose-проекта,
их сети, volumes и scratch очищены; постоянный runtime совпал до/после проверок.

Для CLI отдельно установлен Base `pdlc-cli-core` из
`64c960464205edae6d85d5f297c1ae6b99ae0371`; его tree совпадает с Base main.
SDK pin не изменён. Первый full run без этого optional transport завершился
14 отказами и coverage 93.9166%; те же отказы воспроизведены на `master`.
Пакет из старого SDK pin также не поддерживает новый configured API. После
установки нужного CLI-пакета проходят все 26 transport tests и полный gate выше.
Прежние отказы сохранены, порог и assertions не ослаблялись.

Общий Docker grouping audit не зелёный: 26 прежних нарушений process name/manifest
и 2 недоступных runner endpoints. У QA-контейнера этого PR нарушений нет.
Установка, новая live model acceptance, семь ролей/Rework, Kubernetes и rollback
этим локальным gate не квалифицированы; прежняя assisted PM13 evidence сохраняет
свои границы. Последующее документирование не меняет product/tests или pins.

## Фактические инструкции в UI

`GET /api/phases/{id}` и `/instructions` при явном `namespace_id` возвращают
`effective_view` для подтверждённого установленного PM binding. Это та же
сохранённая фаза, которую читает агент, без подмены текста во время исполнения.
UI показывает один набор инструкций; редактирование sealed PM каталога запрещено.
Обычные пользовательские workflow сохраняют редактор. Ошибка проверки профессии
или каталога не открывает редактор и не разрешает запись.

## Immutable image

Producer принимает `--catalog-variant single-task-v1` без `--skills-root`.
Он читает каталог и manifest из точного Git-архива, проверяет sealed hashes и
семь профессий / восемь режимов, затем включает `runtime-compatibility.json`.
Дескриптор `configured-workflow-cli/v1` фиксирует source SHA, каталог,
instruction manifest и возможности API. Native skills revision в нём отсутствует:
инструкции этого пути принадлежат установленному пакету Workflow.

При проверке образа Base сравнивает дескриптор с фактически установленным
пакетом, сохраняя проверки image ID, source archive и runtime bundle. Сохранённые
legacy/base-дескрипторы читаются своим закрытым форматом; это не второй
исполняющий путь и не автоматический выбор старого протокола.
