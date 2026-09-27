# Runtime assignment binding contract

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

Оба endpoint используют один role-scoped assignment token. Runtime token
агента не может создавать или связывать assignment. Синтетические binding/run
refs запрещены.

## Backend-owned mode policy

Dispatch разрешён только в mode с полным policy:

- `role_key`;
- `execution_scope`: `business`, `delivery` или `aggregate`;
- `tech_workspace_policy`: `forbidden` для business mode, `required` для
  delivery/aggregate mode.

Legacy `default` modes после миграции не получают выдуманный policy. Попытка
нового assignment в такой mode завершается fail-closed.

`role_key` имеет один общий runtime-safe формат для каталога, assignment API и
token configuration: lowercase `[a-z][a-z0-9-]{1,31}`.

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
  `bind_operation_key` и digest bind-запроса;
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
детерминированный conflict. Rebind к другим refs запрещён.

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

## Terminal owner boundary

Project-workflow `step` с внутренним verdict `PASS` закрывает только текущую
техническую phase. Business lifecycle меняется отдельной server-owned операцией
`completeAssignedStage(outcome=passed|needs_rework)` после принятия evidence.

`needs_rework` никогда не кодируется как project-workflow verdict. Внутренние
`BLOCKED`, `PARTIAL`, `ROLLBACK` и `DELEGATE` не вызывают Business transition.
Agent-facing CLI по-прежнему содержит только `step` и `history`.
