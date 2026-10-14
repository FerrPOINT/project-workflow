# PM Terminal Receipt

PM single-task-v1 использует existing
`POST /internal/runtime/terminal-receipt/readback`. Request/response envelope,
selectors, schema, reference format и canonical hash не меняются. Registrations,
новые DTO, table/migration, controller, credential или CLI command не нужны.
Legacy/Base пути не получают новый producer автоматически.

## Producer

Final `PM-DRAFT-03` report проходит existing current PM scope и typed confirmation
gate. Accepted PASS, полный frozen evaluation/contract, done cursor, completion
event и terminal seal сохраняются в existing transaction. Build/seal failure
откатывает final history/event/cursor вместе. `complete=true` не публикуется без
durable receipt. Сам terminal receipt не доказывает native exit.

Existing CLI возвращает `workflow_receipt` в JSON root:

```text
project-workflow --json step --task <actual-workflow-key> --report <exact-report> --operation-key <original-key> --runtime-request <request.json> --execution-token-file <private-token-file>
```

Exact key/body replay валидирует сохранённый seal без нового evaluator call.
Старые terminal PM history без seal/frozen inputs возвращают409; readback/replay
не создаёт retrospective receipt и не переписывает историю.

## Readback Для Fleet

Authorization: existing `project_manager` runtime bearer плюс
`X-Workflow-Execution-Token` текущего PM execution/run. Assignment/catalog token
не разрешён. Task key берётся из Tracker-owned execution, не из chat UUID.

```json
{
  "task": "<actual SDLC-ordinal>",
  "step_operation_key": "<original final step key>",
  "instruction_profile": "single-task-v1",
  "instruction_manifest_sha256": "<actual installed manifest SHA256>",
  "session_run_id": "<current Fleet PM run UUID>",
  "single_task_context_sha256": "<current PM-enrolled context hash>"
}
```

Existing reference/hash selector также работает. Ответ:
`{ok:true,complete:true,workflow_receipt:{reference,sha256},receipt}`;
`Cache-Control:no-store`. `sha256=payload_sha256(receipt)` без self-hash поля.
HTTP401/403/404/409/422/503 сохраняют existing contract.

PM добавляет только `receipt.binding.pm` и четыре current-run поля в
`receipt.result`. Non-PM receipt serialization/hash не меняются. В `binding.pm`:

- `identity`: existing PMIdentity; task/root/project/assignment/execution/agent.
- `namespace_ownership_ref`: actual retained namespace owner ledger ID.
- `execution_version`, `execution_fence`, `session_run_id`, `binding_ref`,
  `hermes_run_ref`: current PM execution/run, не initial general bind.
- `checkpoint`: existing typed checkpoint с non-null requirements revision/hash;
  clarification fields явно null, confirmation не выдаётся за answer.
- `resume_input`: actual saved typed confirmation UUID и input receipt ref/hash.
- `resume_operation_key`, `resume_request_sha256`: accepted resume operation pins.

Builder/readback сверяют checkpoint/input с immutable accepted resume result,
current namespace owner, execution version/fence, actual current PMRun fence,
final step/response и unique completion event. `binding.request` намеренно
сохраняет initial bind; после resume current run берётся только из `binding.pm`
и matching result. PM version/fence не являются Tracker lease version/fence.

Config pins: installed profile/manifest, workflow/mode cursor и frozen evaluated
contract/evaluation hashes. Base config/admission не придумывается. Raw report,
provider inputs, messages и credentials в receipt не копируются.

Typed input принят existing trusted Fleet assignment adapter. Workflow receipt
не заменяет fresh owner confirmation/latest requirements readback у Tracker.
После separate actual native terminal Fleet валидирует Workflow receipt и
вызывает existing scheduler-only Tracker CompletePmDraft; PM не получает этот
credential. Analyst discovery следует только за accepted Tracker completion.

## Fixture И Проверки

Для original CLI final report Fleet может использовать тот же readback endpoint
с `current_run=true` вместо неизвестного ему operation key. Task/run/profile/hash
и scoped token обязательны; server находит ровно одну фактическую terminal запись
текущего PM binding. Это read-only selector, не дополнительная tool-прослойка,
новый CLI, storage или разрешение самостоятельно подтвердить требования.

Exact actual request/response из SQLite/TestClient:
[`single_task_pm_terminal_readback.json`](../tests/fixtures/single_task_pm_terminal_readback.json).
Tracker inputs и native observations синтетические; это не live runtime proof.
Headers содержат только placeholders, issued secrets не сохранены. Fixture
проверяется полным equality и canonical receipt hash в PM-focused test.

```text
python -m pytest -q tests/test_single_task_pm_terminal.py tests/test_single_task_terminal.py tests/test_single_task_runtime.py tests/test_single_task_pm_producer.py --timeout=60
```

Пакет покрывает seal/readback/reference/replay/restart, current versus initial
run, atomic rollback, stale/tampered owner/execution/version/fence/checkpoint/
confirmation/evaluation/history/event/cursor/assignment и old unsealed records.
SQLite coverage не заявляется actual PostgreSQL или full live SDLC acceptance.
