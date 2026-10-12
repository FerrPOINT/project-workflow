# PM MCP draft content v1

Опциональный [content patch](../project_workflow/references/pm_mcp_draft_mode_v1.json)
для PM **catalog v2**, mode `draft`, scope `business`. Это не catalog v3,
не loader и не готовое тело PUT: числовые DB IDs в пакете отсутствуют.
Пакет не установлен; default catalog, bootstrap, pins и history не меняются.

| Существующий phase code | Содержание |
| --- | --- |
| `PM-DRAFT-01` | Первый `workflow_step` с `report=null`; intake из owner input и фактических context/requirements/clarification receipts. |
| `PM-DRAFT-02` | Typed requirements revision/readback, current fence, исходный idempotency key и durable clarification вместо вымышленного ответа. |
| `PM-DRAFT-03` | Report с уже полученными evidence; затем Workflow receipt; exact human confirmation той же revision/hash остаётся owner/server operation. |

Сохранены codes, порядок, mode metadata, skills и по две строки instructions,
checks и evidence в каждой фазе. Используются только шесть существующих MCP tools.
PM не подтверждает требования за владельца и не запускает Analyst. Trusted verifier
и checklist/prerequisite gates сохраняются; Workflow completion их не заменяет.

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
   `workflow_step` instruction delivery и owner confirmation в локальном runtime.

Не переключать namespace workflow, не выполнять rebootstrap и не менять
active catalog version, Base/Workflow/Fleet pins автоматически. Content package
не является runtime acceptance или разрешением обойти authorization/recovery gates.

Локальные pure-проверки пакета:

```bash
python -m unittest discover -s tests -p test_pm_v2_mcp_content.py -v
python -m ruff check tests/test_pm_v2_mcp_content.py
```

Тесты проверяют content и synthetic ID-preserving aggregate projection, но не
применяют конфигурацию и не доказывают PG/evaluator/Hermes execution.
