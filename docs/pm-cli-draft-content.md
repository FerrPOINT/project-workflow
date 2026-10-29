# PM CLI draft content v1

Историческое предложение, которое не было установлено. Старые file-token команды
и ограничения CLI ниже не действуют. Текущий путь описан в
[едином CLI/API](configured-cli-v1.md); устаревший JSON и его неиспользуемый
генератор удалены из поставки.

Опциональный [архивный content patch](https://github.com/FerrPOINT/project-workflow/blob/a3ccb03150172edbc25e54c77a5d430bbaaebf70/project_workflow/references/pm_cli_draft_mode_v1.json)
для PM **catalog v2**, mode `draft`, scope `business`. Это не catalog v3,
не loader и не готовое тело PUT: числовые DB IDs в пакете отсутствуют.
Пакет не был установлен; эти сведения сохранены только для истории решения.

| Существующий phase code | Содержание |
| --- | --- |
| `PM-DRAFT-01` | Первый CLI `step` без `--report`; intake из owner input и фактических authorized receipts. При отсутствии typed PM context — stop. |
| `PM-DRAFT-02` | Typed requirements/revision/question CLI отсутствует; не заявлять сохранение и не заменять его generic CRUD/comments. |
| `PM-DRAFT-03` | Report только с уже полученными evidence; затем actual returned verdict/status. Exact human confirmation той же revision/hash остаётся owner/server operation. |

Сохранены codes, порядок, mode metadata, skills и по две строки instructions,
checks и evidence в каждой фазе. Hermes вызывает existing service CLI через terminal;
новый MCP, Hermes hook или CLI subcommand не добавляется.
PM не подтверждает требования за владельца и не запускает Analyst. Trusted verifier
и checklist/prerequisite gates сохраняются; Workflow completion их не заменяет.

## Фактические команды и границы

Source inventory: Workflow CLI candidate `2c9d62475098be99c411f7e61450a4d9a4f624bf`,
`project_workflow/interfaces/cli/{core,ui}.py`; Tracker main
`72a10381117efb70cbb89ec09c91be1e4f5ef399`, `backend/cli/src/{main,commands}.rs`.
Это provenance чтения source, не repin или доказательство установленного бинарника.

```text
project-workflow --json step --task <workflow-task-key> --operation-key <original-key> --runtime-request <private-request-json> --execution-token-file <private-token-file>
project-workflow --json step --task <workflow-task-key> --operation-key <original-key> --runtime-request <private-request-json> --execution-token-file <private-token-file> --report <report-text>
project-workflow --json history --task <workflow-task-key> --n 20
task-tracker --output json issue get <issue-id>
```

Workflow machine `step` с тремя flags требует явно заданный непустой
`PROJECT_WORKFLOW_URL` (без адреса по умолчанию) и использует
`POST /internal/runtime/step` без `/api` prefix. Нужны actual role runtime bearer
в `SDLC_API_TOKEN`, supplied scoped token в приватном файле и полный существующий
`RuntimeStepRequest`: assignment revision/ref, binding/run refs, mode/cycle/attempt,
expected phase/status и применимые Base config/session fields. Task/report/key
должны совпадать с frozen JSON. Сохранить исходные assignment, operation key, body
и token; не создавать их моделью и не менять для повтора. Сервер выбирает namespace
по runtime credential и проверяет fence; `PROJECT_WORKFLOW_NAMESPACE_ID` не
подменяет machine assignment. Без полного context/token — stop, без DB fallback.
Чтение фазы и report — разные intents: каждый требует своего supplied snapshot/key;
нельзя переиспользовать ключ чтения с изменённым report body.

Команд по-прежнему две: `step` и `history`. Legacy human `step` без runtime flags
идёт через `POST /api/cli/step`, а `history` — через `GET /api/cli/history`;
их human namespace selector и наличие HTTP transport не квалифицируют PM machine
execution. Локальный DB mode этот пакет не разрешает как fallback. Отказ означает
stop, не смену identity/namespace.

Tracker CLI использует API и поддерживает `comment list/add` и generic CRUD/status
transitions, но не имеет PM SDLC context, typed requirements revision, durable
question/checkpoint, exact confirmation или original-operation readback команд.
Они **не заменяются** comment, issue update/transition или board move. Issue GET
не подтверждает current assignment fence, saved requirements/hash или saved answers.
При отсутствии необходимых receipts PM останавливается, не выдаёт фазу за завершённую.

Workflow CLI принимает original operation key и supplied assignment fence, а
существующий runtime API проверяет их и поддерживает keyed replay. CLI **не реализует
checkpoint/readback**, отдельную original-key operation readback команду или
автоматический retry. После unknown report acceptance **не повторять report вслепую**:
нужен existing authorized original-intent readback вне этих CLI команд; history
не доказывает принятие конкретного original body. Эти CLI gaps остаются открыты;
content patch не делает текущий PM lifecycle исполнимым
целиком и не заявляет transport/API эквивалентность прежнему MCP path.

## Подготовка через существующий aggregate API

Применение выполняет уполномоченный оператор, не PM machine credential.
Сначала нужен controlled fresh **Workflow task/cycle без прежнего evaluation coverage**.
Новый Hermes run сам по себе недостаточен. Общий workflow нельзя редактировать
посреди старых незавершённых заданий: изменения видны всем его задачам, а ранее
покрытые criterion IDs могут быть переиспользованы. Принятые receipts не переписывать.

1. Через `GET /api/namespaces` и `GET /api/namespaces/{namespace_id}` определить
   существующий PM workflow. Прочитать
   `GET /api/phases?namespace_id=<id>&workflow_id=<id>&mode_id=<id>` и
   `GET /api/phases/{phase_id}`. Сопоставить exact codes из таблицы с mode `draft`;
   проверить role/skills, порядок, graph и ожидаемые 2/2/2 вложенные строки.
   При drift остановиться, не угадывать IDs и не создавать replacement rows.
2. Для каждого code наложить только новый текст на соответствующие **существующие**
   упорядоченные rows из readback. Instructions: сохранить `id`, `execution_type`
   и неизменные `skills`, заменить `description`. Checks/evidence: сохранить `id`,
   заменить `description`. Проверить точное соответствие количества строк;
   не отправлять `id=null`. JSON strings checks/evidence нужно представить как
   существующие API rows `{id, description}`, а не передавать напрямую.
3. В `PUT /api/phases/{phase_id}?namespace_id=<id>` передать только полные arrays
   `instructions`, `checks`, `evidence`. Не включать mode/phase identity или graph.
   Пропущенные rows внутри переданного array означают удаление, не частичное обновление.
4. Прочитать каждый aggregate обратно и сверить весь контент, IDs, skills,
   execution types и graph. Единого atomic update/CAS трёх фаз нет: сериализовать
   конфигурацию до начала нового задания. Затем отдельно проверить actual
   CLI instruction delivery в API mode и owner confirmation в локальном runtime;
   не проводить acceptance до закрытия указанных PM SDLC CLI gaps.

Не переключать namespace workflow, не выполнять rebootstrap и не менять
active catalog version, Base/Workflow/Fleet pins автоматически. Content package
не является runtime acceptance или разрешением обойти authorization/recovery gates.

Локальные pure-проверки пакета:

```bash
python -m unittest discover -s tests -p test_pm_v2_cli_content.py -v
python -m ruff check tests/test_pm_v2_cli_content.py
```

Тесты проверяют content и synthetic ID-preserving aggregate projection, но не
применяют конфигурацию и не доказывают PG/evaluator/Hermes execution.
