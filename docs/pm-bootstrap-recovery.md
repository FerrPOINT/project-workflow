# PM bootstrap: reader и внутренний successor

Продолжение source-only boundary `fe8aa0fc6ab22b83e04e4e75e6163f69be554277`.
GET predecessor и POST retry зарегистрированы в существующем Workflow app.
Fleet composite producer/route и Tracker lease-retry интегрирует Main с A/C;
этот пакет не имитирует их actual runtime authority.

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

## Зарегистрированный GET

Registration в существующем FastAPI app:

```python
from project_workflow.interfaces.ui.routes import pm_bootstrap_api
app.get("/internal/runtime/pm-bootstrap/predecessor", response_model=None)(pm_bootstrap_api.predecessor)
app.post("/internal/runtime/pm-bootstrap/retry", response_model=None)(pm_bootstrap_api.retry)
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

Flat reader contract для A/C: `assignment_operation_key`/`assignment_revision` —
CURRENT local sink, `canonical_assignment_operation_key`/`canonical_assignment_revision` —
retained canonical root. `bind_request_sha256` — stored SHA256 или NULL,
`binding` — original bind request или NULL; это НЕ envelope `{request,sha256}`.
`initial_phase_id` — actual first mode phase ID или NULL при отсутствии phase,
`current_phase_id` — actual task cursor. `initial_phase=false` не даёт retry permit.

## Внутренний producer

```python
PMBootstrapService(uow).retry(project_id, task, request, read_current)
```

`POST /internal/runtime/pm-bootstrap/retry` принимает closed `BootstrapRetry`. Поля:
`predecessor_operation_key`, `predecessor_sha256`, новый `operation_key`,
`bootstrap_attempt_ref`, `proof_sha256`. Нет caller `no_step`, status override,
skip-running или request-supplied URL/credential.
Namespace/task разрешаются из stored predecessor через существующую PM assignment
credential; caller не выбирает другой task/project. Ответ — standard assignment
result, без execution token. Ошибки/успех no-store; readback failure даёт 503 без
публикации successor. Exact replay не делает новый proof/native HTTP request.

Зарегистрированный POST использует `pm_readback.bootstrap_proof`. Origin и token
берутся из существующих `PROJECT_WORKFLOW_PM_READBACK_URL/TOKEN`. Fixed GET:
`/internal/runtime/v1/pm/bootstrap-retries/{bootstrap_attempt_ref}/workflow-proof`.
Ответ — RAW `BootstrapProof`, не `{ok,result}`. Это frozen permit из durable Fleet
attempt ПОСЛЕ Tracker retry ACK плюс fresh current lease/owner validation на Fleet.
Configured proxy environment отключён, redirects запрещены, transport budgets 3s/10s.
Новых credentials/URLs/settings нет. Pre-renew witness route
`/internal/runtime/v1/pm/runs/{old}/bootstrap-retry?barrier_id&next_session_run_id`
остаётся отдельным C contract: его expired witness не принимается как post-renew permit.

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
Эти host tests отдельно не являются PostgreSQL concurrency qualification или live retry acceptance.
Fleet/Tracker producer wiring требует интеграции Main до coherent live acceptance.

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
PostgreSQL, model/live calls, builds, installs или push на этом host-этапе не выполнялось.

## Registered transport follow-up

Source baseline: `e2abddf4d1833a6758032621110d978a955b1e51`; canonical/unbound fix:
`12679d91c6731b5fd1f5fd4e3fd959d80ac36097`. Fresh remote master `c24c252` добавил
только recovery handoff; production bytes baseline не менялись.

После registrations/adapter: **47 host PASS / 125.05s** без skips — 33 bootstrap,
12 HTTP transport и 2 retained native-readback/OpenAPI tests. Scoped mypy 4 source
files, Ruff 7 Python files, diff-check PASS. Loopback HTTP — synthetic Fleet,
не real runtime/model calls. Полный quality gate/coverage/PG/live не запускались.

Первоначальные PG fixtures были authored/collected, но ещё UNRUN на transport-этапе.
Их последующий actual isolated Compose/helper v2 результат приведён ниже отдельно.
Fixtures проверяют real PG locks/rows через registered endpoints и synthetic
configured Fleet HTTP, без installed runtime/LLM/native effects.
Fleet post-renew proof route обязан сам проверить durable retry ACK/current lease;
его server-side реализация и Tracker producer не квалифицированы этими host tests.

PG acceptance follow-up (test-only): positive Present/Absent проходят весь normal
canonicalRoot PM bind/step/readback/typed confirmation/terminal flow через configured
loopback native HTTP. Concurrent successor теперь параметризован обоими binding
states: итог **6 PG executions**, не пять. Первоначальный authored/collected scope
впоследствии исполнен отдельным actual PG gate ниже.
Shared host/PG terminal assertion helper + HTTP smoke: 4 host PASS / 37.50s.
Отдельный instruction/catalog audit production source `4e82326`: 66 host PASS / 23.12s.

## Actual PostgreSQL acceptance

Qualified immutable source: `a7b805d4efc3d486aef400947a8da38201a46a8f`,
tree `ebb432a2e5289b7cecb33a485a8ab4b8841ce6d4`. Следующий docs-only commit
не меняет эти source labels и не объявляется новым выполненным PG run.

2026-10-21: **6 PASS / 0 failures / 0 errors / 0 skipped, 158.877s**, один запуск
в isolated ComposeHelper v2. Exact collection и JUnit совпали:

| Selector в `TestPostgresPMBootstrap` | Seconds | Result |
|---|---:|---|
| `test_registered_retry_preserves_predecessor_and_fences_late_bind[bound]` | 57.985 | PASS |
| `test_registered_retry_preserves_predecessor_and_fences_late_bind[unbound]` | 59.636 | PASS |
| `test_concurrent_successors_have_one_locked_publication[bound]` | 8.096 | PASS |
| `test_concurrent_successors_have_one_locked_publication[unbound]` | 7.314 | PASS |
| `test_enrollment_during_composite_http_read_prevents_successor` | 10.215 | PASS |
| `test_predecessor_lock_timeout_is_unknown_not_absent` | 12.031 | PASS |

Файл: `tests/test_postgres_integration.py`. Реальный disposable PostgreSQL,
registered HTTP endpoints и configured loopback proof/native HTTP; installed
Fleet/Tracker/model не вызывались. Оба positive paths проходят unchanged
canonicalRoot PM bind/step/readback/terminal, без подмены на local child identity.

Actual full OpenAPI export: **61 operation IDs / 61 unique**, обе bootstrap
routes и closed five-field `BootstrapRetry`. Existing consumer exporter дал
byte-identical committed Git/LF JSON; старые routes/schemas не изменены.

| Artifact | SHA256 |
|---|---|
| Terminal result | `fc2318cfb88908e5c92b9d3e91815abcb6429dc20661a0f196717049e04804a1` |
| JUnit | `e5d83f30f64a6bc2831d32db0376cdb4fd3b368513756cc0b6ac21cef49e507f` |
| Actual full OpenAPI | `45fd92723d7bafde760079e947730461cbe48d07ff515c69ea4a341fe3f17da0` |
| Actual/committed consumer OpenAPI | `843880b6347ea343dff69158522b7ec9e603c6adee6694734e5f72d9c235e93d` |
| Executed runner | `edcd83adcf67f596d8c7db2283e2e1fd2adc9d062a05aef8a00e2f1449e45f34` |

Fresh disk/RAM/route/IPAM admission passed; preparation/download/PG использовали
явные отдельные `10.246.6/7/8.0/24`, egress удалён до PG/tests. Journal v2 cleaned,
`cleanup_verified=true`, `input_cleanup_verified=true`; exact-project readback
подтвердил отсутствие own containers/volumes/networks. Raw source/helpers/logs
сохранены вне disposable inputs. Результат не включает full repository gate,
coverage, release/image build, install или live technical-retry acceptance.
