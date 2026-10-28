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

Контракт фазы содержит текущую работу и уже существующие evidence. Он не требует
собственного будущего receipt, ещё не опубликованного комментария или будущего
перехода статуса. Reviewer/Tester могут полностью выполнить проверку и вернуть
бизнес-результат rework; это не означает принятие дефектного кандидата.

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
