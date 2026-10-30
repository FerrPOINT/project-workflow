# Единый CLI/API Workflow

Source-контракт для семи профессий и восьми режимов. Установка, полный gate и
живая приёмка подтверждаются отдельно. До переключения должны быть удалены
оставшиеся старые исполняющие маршруты и завершены прежние активные попытки.

Workflow хранит фазу, оценку отчёта и историю. Tracker владеет назначением,
требованиями, комментариями и атомарными переходами. Fleet проверяет реальный
terminal процесса. Native run ID не является идентичностью задачи Workflow.

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

Evaluator `supervisor-evaluator-v11` сохраняет строгий LLM verdict, но учитывает
достаточность evidence, явно заданную контрактом. Если фактические скопированные
readbacks и сверка identity достаточны, отдельная attestation запуска команды
не требуется. Если контракт не требует независимого presentation receipt или
transcript, полный сохранённый документ, matching saved confirmation настоящего
владельца и конкретное описание фактического показа могут быть достаточны.
Намерение показать документ не равно показу; summary не заменяет FULL content.
Отсутствующий или несовпадающий consent, ошибочные команды, identity mismatch
и противоречия остаются недостаточными evidence. Нет auto-PASS или обхода LLM.

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

PM вызывает `sdlc pm completion submit` и заканчивает в Backlog / Ready, без
автоматического Analyst. Техническая роль публикует typed result с ключом
`delivery-result:<assignment_id>` и завершает run; Fleet проверяет реальный
terminal и ресурсные доказательства перед Tracker Complete. Исправленный кандидат
повторно проходит Review и Testing. Ни принятый отчёт, ни proposal сами не переходят стадию.

При критическом бизнес-возврате PM читает `critical_review` из актуального context
Tracker и сверяет выбранный blocker, его версию/hash и исходную редакцию.
Используются те же фазы, CLI и точное новое подтверждение владельца. Обычное
системное сообщение Fleet не содержит второй копии инструкций. Завершение
атомарно разрешает blocker и возвращает Backlog / Ready; Analyst не запускается.
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

Это отдельные уровни доказательств, не один общий gate. Product/test source
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
