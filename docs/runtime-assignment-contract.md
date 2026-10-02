# Runtime assignment binding contract

The opt-in PM clarification continuation contract is documented separately in
[PM continuation v1](pm-continuation-contract.md), with
[verification limits](pm-continuation-verification.md). Ordinary assignment,
bind, Supervisor step and history remain the default path.

Project-workflow — технический sink и cursor. Он не определяет роль, workflow
mode, execution scope, порядок очереди или следующий stage. Эти значения
вычисляет Relevanter Business из persisted Task/stage/decomposition state и
передаёт через защищённый `/internal/runtime/assign`.

Endpoint принимает только server-owned role credential из
`PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON`. Assignment credentials должны быть
уникальны и не могут совпадать с Hermes runtime или fleet catalog tokens; они
не передаются в agent shell.

Принятие и запуск разделены на две идемпотентные операции:

1. `/internal/runtime/assign` сохраняет `unbound` assignment до запуска Hermes;
2. после успешного `startOrResume` адаптер вызывает `/internal/runtime/bind` и
   прикрепляет реальные `binding_ref` и `hermes_run_ref`.

Эти endpoint и continuation `/internal/runtime/rebind` используют один role-scoped assignment token. Runtime token
агента не может создавать или связывать assignment. Синтетические binding/run
refs запрещены.

Перед dispatch Business adapter вызывает `GET /internal/runtime/capabilities`
тем же role-scoped assignment token. Успешный ответ имеет точный контракт:

```json
{
  "ok": true,
  "role_key": "developer",
  "credential_kind": "assignment",
  "capabilities": ["assign", "bind", "rebind"],
  "readiness": {"service": "ready", "schema": "ready", "catalog": "ready"},
  "runtimeCompatibility": {
    "catalogVersion": 2,
    "catalogRevision": "<40-lowercase-hex>",
    "catalogSha256": "<64-lowercase-hex>",
    "skillsRevision": "<40-lowercase-hex>",
    "skillsManifestSha256": "<64-lowercase-hex>",
    "capabilityRevision": "hermes-sdlc-runtime/v2",
    "capabilitySha256": "<64-lowercase-hex>"
  },
  "source_provenance": {
    "schema_version": 1,
    "source_revision": "<40-or-64-lowercase-hex>",
    "source_archive_sha256": "<64-lowercase-hex>",
    "runtime_bundle_sha256": "<64-lowercase-hex>"
  }
}
```

Runtime role token возвращает `credential_kind=runtime` и capabilities
`["step", "history"]`. Missing/unknown credential даёт `401`, catalog
credential — `403`, collision/config error, неготовая schema либо отсутствующий
или некорректный immutable manifest/release compatibility descriptor — `503`. Ответ не содержит token,
namespace/task identifiers, counts, titles или внутреннюю конфигурацию.
`/health` остаётся DB/schema probe и не заменяет этот authenticated preflight.
Capability определяется сохранённым типом credential. Совпадение role key с
зарезервированным именем `fleet-control` не превращает runtime token в catalog
token; `/internal/runtime/catalog` принимает только точный catalog credential,
а catalog credential не принимается `step`, `history` и `capabilities`.

## Backend-owned mode policy

Канонический managed registry:

| Role key | Workflow | Modes | Scope |
| --- | --- | --- | --- |
| `project_manager` | `hermes-sdlc:project_manager` | `draft` | `business` |
| `analyst` | `hermes-sdlc:analyst` | `analysis` | `business` |
| `architect` | `hermes-sdlc:architect` | `decomposition` | `business` |
| `developer` | `hermes-sdlc:developer` | `initial`, `rework` | Каждый mode: `delivery` / `aggregate` |
| `reviewer` | `hermes-sdlc:reviewer` | `delivery`, `integration` | `delivery` / `aggregate` |
| `tester` | `hermes-sdlc:tester` | `delivery`, `integration` | `delivery` / `aggregate` |
| `devops` | `hermes-sdlc:devops` | `delivery`, `integration` | `delivery` / `aggregate` |

`project_manager` — единственный допустимый underscore role key; произвольные
aliases не транслируются. Повторная доработка получает новый backend-owned
cycle/assignment, а не `repeatable` flag. Managed workflow без explicit
`mode_key` не использует legacy `default` fallback.

Dispatch разрешён только в mode с полным policy:

- `role_key`;
- `execution_scopes`: допустимый набор `business`, `delivery` или `aggregate`; assignment закрепляет один выбранный Business `execution_scope`;
- `tech_workspace_policy`: `forbidden` для business mode, `required` для
  delivery/aggregate mode.

Legacy `default` modes после миграции не получают выдуманный policy. Попытка
нового assignment в такой mode завершается fail-closed.

`role_key` имеет один общий runtime-safe формат для каталога, assignment API и
token configuration: lowercase `[a-z][a-z0-9-]{1,31}` плюс единственный
канонический underscore key `project_manager`.

## Immutable binding

Каждая новая assignment revision хранит переданную Business execution identity:

- routing identity: `workflow_key`, `mode_key`, `stage_key`, `role_key`,
  `execution_scope`, `cycle_number`, `attempt_number`;
- Business refs: `business_task_ref`, `root_task_ref`, `work_item_ref`,
  `work_item_revision`, `queue_item_ref`, `decomposition_revision_ref`,
  `stage_revision`;
- execution refs: `task_workspace_ref`, `workspace_revision`, применимые
  `tech_execution_workspace_ref`/`tech_execution_attempt_ref`,
  `workspace_generation`, `lease_generation`;
- provenance до запуска: `assignment_ref` и bounded `exact_input_refs`;
- provenance после запуска: реальные `binding_ref`, `hermes_run_ref`,
  `bind_operation_key` и digest bind-запроса; отдельный immutable
  `concrete_agent_ref` (canonical non-nil lowercase Fleet UUID), обязательный для PM;
- technical cursor: project/workflow/mode/cycle/assignment revision и
  idempotent `operation_key`.

Business mode обязан явно не иметь Tech workspace refs. Delivery и aggregate
mode требуют оба Tech refs. Активную assignment нельзя заменить; повтор того же
`operation_key` принимается только при полном совпадении canonical payload.
`exact_input_refs` может быть пустым, содержит не более 128 Business-owned
snapshot-объектов и не маршрутизируется по `kind`. `kind` и `ref` обязательны;
`revision` и непустое поле `hash` длиной до 256 символов
опциональны. Список канонически
сортируется по tuple `(kind, ref, revision-or-empty, hash-or-empty)`, при этом
отсутствующее optional-поле не превращается в синтетическое значение.
Canonical JSON всего replay payload хранится вместе с его SHA-256 digest;
перестановка refs и JSON keys сохраняет replay, изменение или добавление любого
значимого значения даёт conflict.

Первое принятое назначение может иметь любой положительный `attempt_number`,
выданный Business: предыдущие попытки доставки могли завершиться до обращения
к project-workflow. Локальная `assignment_revision` при этом начинается с 1.
Номер попытки не сбрасывается и входит в неизменяемый payload и bind/step fences.
Transport route `project-manager` не заменяет канонический `role_key=project_manager`:
credential map, capabilities и assignment используют имя роли из managed registry.

Записи из опубликованной migration `0002`, у которых уже есть реальные
`binding_ref`/`hermes_run_ref`, но ещё нет bind metadata, читаются как
`legacy_bound`. Точный bind с `expected_binding_state=legacy_bound` и теми же refs
однократно дописывает `bind_operation_key` и digest; другие refs
отклоняются. Миграция не изобретает для старых записей operation key или
digest.

`/internal/runtime/bind` принимает точный task, assignment
operation/ref/revision, mode/cycle/attempt, ожидаемое `unbound` или
`legacy_bound` состояние,
реальные refs и отдельный `bind_operation_key`. Одна DB CAS-операция переводит
assignment в `bound`. Точный retry того же ключа возвращает сохранённый cursor;
изменённый payload, второй ключ, другая роль/задача либо stale revision дают
детерминированный conflict. Этот endpoint не переписывает refs существующего
assignment. Continuation создаёт отдельный assignment по контракту ниже.

## Question continuation

После durable owner checkpoint и terminal acknowledgement старого run Business
подготавливает новый assignment через `/internal/runtime/rebind`. Request
закрепляет old/new assignment и binding identity, checkpoint owner/run/ref/revision,
workspace/stage/decomposition revisions, operation key и новый `run_sequence`.
Checkpoint input должен совпадать с frozen provenance; изменённые входные refs,
повторное использование immutable IDs или stale cursor отклоняются без записи.

Новая запись начинается `unbound`, сохраняет текущую незавершённую фазу,
Task/Thread/cycle и Business attempt. Новые binding/run refs закрепляются
owner-confirmed `bind`; до него effects запрещены. Same-key retry возвращает
сохранённую подготовку, collision и старый run не продвигают новый cursor.
Ранний/повторный ответ на question сохраняется Business по актуальному reference
и сам по себе не запускает второй run. Git checkpoint не означает PASS,
candidate или закрытие стадии; business-only checkpoint не требует Tech workspace.

Catalog v2, skills и capabilities закреплены в immutable assignment. Runtime
повторно проверяет packaged descriptor; drift между prepare и bind блокирует
исполнение. V1 catalog/history сохраняются без переименования mode/phase refs;
legacy Developer `integration|integration_rework` не выдаются новым dispatch.
Owner cleanup v1 ограничен GET/ACK `RECONCILE_ONLY`.

`concrete_agent_ref` записывается только этим защищённым bind, вместе с refs и
digest. Он не заменяет каталожное имя агента или `role_key=project_manager`.
PM identity/callback используют тот же UUID в `agent_ref` и сверяются с
сохранённым mapping и bind provenance. PM без mapping закрывается fail-closed.
Для non-PM поле optional/nullable; отсутствие или null сохраняет прежний
canonical bind digest. Finalized bind нельзя дополнить UUID задним числом.

New PM enrollment requires an explicitly provisioned namespace/Tracker project
mapping; see [PM Namespace Ownership](pm-namespace-ownership.md). This separate
authority table does not weaken generic binding completeness or fabricate any
Business workspace/queue/decomposition provenance. Ordinary non-PM runs retain
their existing contract; ownership alone never grants PMDraft dispatch.
Pending migration `0007_pm_execution` после accepted `0006` оставляет mapping
старых строк null, не меняя опубликованные `0001`–`0006` и не выдумывая Fleet identity.

Assignment, enrolled в PMExecution, не может создать generic continuation через
`/internal/runtime/rebind`, независимо от статуса. Проверка enrollment выполняется
под тем же owner task lock, что и PM bind, до изменения cursor/ledger/history.
Exact historical replay без новых effects допустим. PM использует только свой
resume/rebind; accepted generic flow для non-enrolled assignments сохраняется.

Новая generic `/internal/runtime/assign` revision также запрещена для задачи
с любым immutable PM enrollment, включая `done` и enrollment старой assignment.
Task-wide indexed EXISTS выполняется под owner task lock после exact historical
same-key replay и до мутаций. Service возвращает `ConflictError`, HTTP — прежний
generic envelope `ok=false,error` со статусом 409. Workflow PASS и terminal
readback не заменяют отсутствующий owner replacement/history CAS. Non-enrolled
generic assignment/retry/cycle и PM-specific resume/rebind не изменены.

`/internal/runtime/step` доступен только для `bound` assignment и сохраняет
прежний полный fence. History может читаться в `unbound` состоянии, но не
создаёт binding и не подставляет отсутствующие refs.
Успешный report-step и его exact replay возвращают один сохранённый result,
дополненный прочитанным после transition cursor:
`assignment_operation_key`, `assignment_revision`, `assignment_ref`, `binding_ref`,
`hermes_run_ref`, `binding_state`, `mode_key`, `cycle_number`, `attempt_number`,
`status`, `current_phase_code`, `current_phase_name`. Cursor записывается в
одной transaction с phase transition, а ответ перечитывается из fresh UoW.
Следующая фаза и terminal/blocked status не выводятся из verdict.

После terminal `done` Business может выдать новый `operation_key` в том же
mode/cycle только как retry: `attempt_number` обязан быть ровно на единицу
больше предыдущего, а workflow/role/stage/scope, Business refs, их revisions и
exact inputs остаются неизменными. Attempt-specific run/binding/Tech refs и
lease generations могут измениться. Новый rework entry обязан иметь следующий
`cycle_number` и снова начинается с `attempt_number=1`. Активный attempt,
пропуск/регресс attempt, изменение frozen tuple и пропуск cycle отклоняются.

Опубликованная migration `0002_workflow_modes` не изменяется. Forward migration
`0003_runtime_assignment_bind` добавляет nullable bind metadata, сохраняет
исторические ledger rows и не создаёт вымышленные внешние refs,
operation keys или digests.

Business `work_item_revision` может быть 41-битной временной отметкой изменения
задачи. Поле хранится как `BIGINT` и принимает целые значения от 0 до
`2^63−1`; API и application service отклоняют значения вне этого диапазона.
Forward migration `0004_wide_work_item_revision` расширяет существующее поле
без изменения ledger rows, binding refs, hashes и pinned history. Lossy
downgrade на 32-битное поле запрещён.

## Terminal owner boundary

Project-workflow `step` с внутренним verdict `PASS` закрывает только текущую
техническую phase. Business lifecycle меняется отдельной server-owned операцией
`completeAssignedStage(outcome=passed|needs_rework)` после принятия evidence.

`needs_rework` никогда не кодируется как project-workflow verdict. Внутренние
`BLOCKED`, `PARTIAL`, `ROLLBACK` и `DELEGATE` не вызывают Business transition.
Agent-facing CLI по-прежнему содержит только `step` и `history`.
