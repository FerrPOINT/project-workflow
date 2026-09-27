# Runtime assignment binding contract

Project-workflow — технический sink и cursor. Он не определяет роль, workflow
mode, execution scope, порядок очереди или следующий stage. Эти значения
вычисляет Relevanter Business из persisted Task/stage/decomposition state и
передаёт через защищённый `/internal/runtime/assign`.

Endpoint принимает только server-owned role credential из
`PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON`. Assignment credentials должны быть
уникальны и не могут совпадать с Hermes runtime или fleet catalog tokens; они
не передаются в agent shell.

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
- provenance: `assignment_ref`, `binding_ref`, `hermes_run_ref`, bounded typed
  `exact_input_refs`;
- technical cursor: project/workflow/mode/cycle/assignment revision и
  idempotent `operation_key`.

Business mode обязан явно не иметь Tech workspace refs. Delivery и aggregate
mode требуют оба Tech refs. Активную assignment нельзя заменить; повтор того же
`operation_key` принимается только при полном совпадении canonical payload.
`exact_input_refs` канонически сортируются по tuple
`(kind, ref, revision, sha256)`. Canonical JSON всего replay payload хранится
вместе с его SHA-256 digest; перестановка refs и JSON keys сохраняет replay,
изменение любого значимого значения даёт conflict.

После terminal `done` Business может выдать новый `operation_key` в том же
mode/cycle только как retry: `attempt_number` обязан быть ровно на единицу
больше предыдущего, а workflow/role/stage/scope, Business refs, их revisions и
exact inputs остаются неизменными. Attempt-specific run/binding/Tech refs и
lease generations могут измениться. Новый rework entry обязан иметь следующий
`cycle_number` и снова начинается с `attempt_number=1`. Активный attempt,
пропуск/регресс attempt, изменение frozen tuple и пропуск cycle отклоняются.

Миграция `0003_runtime_assignment_bindings` оставляет эти поля nullable только
для исторических строк и не создаёт вымышленные внешние refs.

## Terminal owner boundary

Project-workflow `step` с внутренним verdict `PASS` закрывает только текущую
техническую phase. Business lifecycle меняется отдельной server-owned операцией
`completeAssignedStage(outcome=passed|needs_rework)` после принятия evidence.

`needs_rework` никогда не кодируется как project-workflow verdict. Внутренние
`BLOCKED`, `PARTIAL`, `ROLLBACK` и `DELEGATE` не вызывают Business transition.
Agent-facing CLI по-прежнему содержит только `step` и `history`.
