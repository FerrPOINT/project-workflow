# PM bootstrap: reader и внутренний successor

Продолжение source-only boundary `fe8aa0fc6ab22b83e04e4e75e6163f69be554277`.
Ни один новый route пока не зарегистрирован. Shared DTO/client, Fleet composite
producer и Tracker lease-retry интегрирует Main с A/C; этот пакет их не имитирует.

## Узкая граница

`PMBootstrapService` работает только с initial single-task PM Draft. Canonical
Tracker task/root, assignment, execution и owner_version сохраняются. Тот же local
Workflow task получает новый immutable assignment с local revision/attempt +1.
Прежние assignment payload/bind/key/hash, task history и phase остаются прежними.
Task не маркируется done; checkpoint, critical review и Workflow receipt не создаются.
Результат successor — **unbound assignment**, не разрешение отправить PM run.

`BootstrapMapping` в новом payload явно сохраняет predecessor key/payload hash,
предыдущую и новую sink revision, canonical assignment **operation key и revision**,
bootstrap attempt и hash принятого composite proof. Под task lock PM enrollment
разрешает CURRENT local assignment и проверяет всю hash-bound predecessor chain
до original `pm-draft:<assignmentUUID>`. PM identity/native callback сохраняют этот
canonical key/revision; обычные runtime bind/step используют local child key/revision.
Произвольный old key или child key не становится PM authority.
Новый PM bind всё ещё обязан получить actual `running` proof. Старый запоздавший
bind отвергается как stale даже при предоставленном running observation.

## Предлагаемый GET

Main registration на существующем FastAPI app:

```python
from project_workflow.interfaces.ui.routes import pm_bootstrap_api
app.get("/internal/runtime/pm-bootstrap/predecessor", response_model=None)(pm_bootstrap_api.predecessor)
```

Query: `task`, `assignment_operation_key`, `assignment_revision`. Только existing
PM **assignment** credential; runtime/catalog/foreign role не авторизованы. Ответ
`{ok:true,result:{...}}` содержит task/project, canonical references/context,
current local assignment revision/attempt/payload hash, immutable original bind
request, actual stored `bind_request_sha256`, `initial_phase_id`, status/cycle/phase,
`pm_enrolled`, `step_state`, `initial_phase` и SHA256
всего snapshot без самого SHA. Credentials, env и private request files отсутствуют.
Все ответы no-store. Not found/stale/unknown различаются: 404/409/503. Timeout не
превращается в empty/absent result.
Реально unbound assignment имеет `binding=null`. Partial custody — отказ, не
fallback в absent. Guarded retry принимает finalized Present И authoritative
unbound Absent: во втором случае все пять stored binding-полей должны быть NULL.
Original native run/binding тогда берутся только из trusted Fleet composite,
дополнительно сверенного с configured native readback, не из caller assertion.
Никакие отсутствующие DB binding-поля не синтезируются. Если original generic bind
успел до successor lock, snapshot изменится и retry откажет. После successor insert
запоздавший original generic bind stale и не сможет заполнить predecessor.

Reader берёт existing namespace lock, затем `SELECT Task FOR UPDATE`. Эти же locks
в том же порядке берёт initial `PMExecutionService.bind`. Проверяются durable
PMExecution (для task И canonical execution), step rows и phase events. Никакая
новая persisted inflight-система не добавляется. PostgreSQL transaction-local
lock/statement budgets 3s/10s ограничивают ожидание; ошибка даёт unknown/rollback.
Snapshot не гарантирует будущее отсутствие enrollment после отпускания lock.

## Внутренний producer

```python
PMBootstrapService(uow).retry(project_id, task, request, read_current)
```

`BootstrapRetry` — application-internal, не shared HTTP DTO. Поля:
`predecessor_operation_key`, `predecessor_sha256`, новый `operation_key`,
`bootstrap_attempt_ref`, `proof_sha256`. Нет caller `no_step`, status override,
skip-running или request-supplied URL/credential.

`read_current(request) -> BootstrapProof` — доверенный интеграционный callback,
НЕ обработчик переданного клиентом proof JSON. Он должен читать существующий
Fleet composite/configured proof-source: actual Tracker current assignment/lease,
original operation reconciliation, отсутствие business result и exact original
terminal native custody. Callback выдаёт typed proof и его actual hash. Вложенный
context — существующий `SingleTaskContext`; canonical assignment/execution refs
сверяются с predecessor. Оба owner_version должны быть actual retained/current
Tracker values и совпасть; original profile не хранит owner_version локально.
Нельзя заменить этот readback caller assertion или конструировать недостающую
authority. Pending/unknown original operation не может стать `settled` от timeout.

Метод дополнительно получает native observation через существующий configured
`pm_readback.observe_run`, сверяет полный identity/run/binding/dispatch/fence и
принимает только completed/failed/cancelled/stopped initial run, checkpoint=None.
Ссылку observation разрешено обновить, но не custody/status/authority поля.

Оба remote readback выполняются ДО task lock: Fleet composite может сам запросить
reader. Затем под namespace/task lock пересчитывается exact predecessor snapshot,
проверяется digest/no-enrollment/no-step, и в той же транзакции вставляется successor
и обновляется только current assignment pointer/local revision. Поэтому old bind,
который выиграл раньше, закрывает recovery; проигравший после insert видит stale
assignment. Два разных successor на одном predecessor не допускаются. Original
operation replay сверяет сохранённый request и не вызывает новый readback/эффект.

## Проверки и пределы

Focused tests используют реальные isolated SQLite ledgers и обычные TestClient
bind endpoints, synthetic native/Tracker readbacks. Покрываются terminal statuses,
unchanged history/canonical identity, explicit key/revision mapping, live running
requirement, stale old bind, enrollment до lock, durable progress, conflict,
transaction rollback и protected reader/no-proof-on-timeout. Actual TestClient
цепочка new local bind -> canonical PM bind/readback -> local steps -> typed
confirmation/resume/rebind -> terminal receipt/readback проверяется для обоих
Present/Absent predecessor. Receipt сохраняет local bind/result и canonical
`binding.pm.identity` раздельно; `single_task_terminal` не требует подмены key.
Это не PostgreSQL concurrency qualification и не live retry acceptance. Новые
routes/DTO/producer wiring требуют интеграции Main до публикации coherent пакета.

Предыдущий run commit `2b8900b` (17 PASS) НЕ доказывал canonical-key compatibility:
positive fixture ошибочно подменяла native/PM key на local child. Этот результат
сохранён как исторический; новая regression использует unchanged canonical root.
Финальный corrected host run: **41 PASS / 189.80s**, без skips:

- `tests/test_pm_bootstrap_retry.py`: 33 cases;
- `test_pm_execution.py::test_wait_resume_new_run_survives_sessions_and_replays`: 1;
- `test_pm_review_revision_bridge.py::test_review_authority_sink_binding_and_restart_remain_independent`: 2;
- `test_pm_review_revision_bridge.py::test_review_checkpoint_resume_and_terminal_use_authoritative_revision`: 1;
- `test_single_task_runtime.py::test_profile_pm_readback_resolves_original_assignment_family`: 3;
- `test_single_task_pm_terminal.py::test_pm_actual_seal_readback_replay_restart_and_exact_wire_fixture`: 1.

Scoped mypy трёх source files, Ruff четырёх Python files и `git diff --check` PASS.
Единственный warning — existing Starlette/AnyIO deprecation. Никаких Docker,
PostgreSQL, model/live calls, builds, installs или push не выполнялось.
