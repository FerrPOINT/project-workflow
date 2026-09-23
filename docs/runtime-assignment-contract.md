# Runtime assignment binding contract

Project-workflow — технический sink и cursor. Он не определяет роль, workflow
mode, execution scope, порядок очереди или следующий stage. Эти значения
вычисляет Relevanter Business из persisted Task/stage/decomposition state и
передаёт через защищённый `/internal/runtime/assign`.

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

Каждая новая assignment revision хранит:

- Business refs: `business_task_ref`, `root_task_ref`, `work_item_ref`,
  `decomposition_revision_ref`, `stage_revision`;
- execution refs: `task_workspace_ref`, применимые
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

Миграция `0003_runtime_assignment_bindings` оставляет эти поля nullable только
для исторических строк и не создаёт вымышленные внешние refs.

## Terminal owner boundary

Project-workflow `step` с внутренним verdict `PASS` закрывает только текущую
техническую phase. Business lifecycle меняется отдельной server-owned операцией
`completeAssignedStage(outcome=passed|needs_rework)` после принятия evidence.

`needs_rework` никогда не кодируется как project-workflow verdict. Внутренние
`BLOCKED`, `PARTIAL`, `ROLLBACK` и `DELEGATE` не вызывают Business transition.
Agent-facing CLI по-прежнему содержит только `step` и `history`.
