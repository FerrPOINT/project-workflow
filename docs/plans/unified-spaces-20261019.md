# Единое пространство PDLC: project-workflow

Статус: **согласованная цель**, реализация в работе, runtime не активирован.
Решение владельца 2026-10-19; общий договор — services-base ADR 0010 и
`docs/contracts/UNIFIED_SPACES_V1.md` в зависимой feature-ветке.

## Ответственность

ProjectRef/ExecutionContextV3 для project execution/results/logs/callbacks. Wiki context требует SpaceRef. Профессия и integer namespace самостоятельны. V1/V2 неизменны, ambiguous legacy input отклонять.

## Инварианты и зависимость

Admin владеет Space и policy, Tracker M:N, Auth identity/sessions/global roles.
Space 0..N Projects; Project 1..N Spaces, без основного Space. ANY allowed Space
открывает Project; A не открывает Wiki B. Read не даёт write/admin роль.
selected empty/missing policy deny; all включает будущие Space и выдаётся явно.
Archive last Space сохраняет Project readonly и links. Active B помогает только
субъекту с B и прежней write ролью; restore не снимает Project archive.
Last unlink запрещён даже конкурентно и direct DML. Данные не удаляются.

Admission сохраняет исходный deadline <=60s/token/upstream; downstream TTL не
обновляется. Expired/unavailable fail-closed, readiness отражает зависимость.
PAT/delegation/machine scopes дополнительно. Public/legacy URL не обходят правило.

## Последовательность и gates

1. Обновить owner API/data-model/architecture и версии контрактов перед кодом.
   Applied migrations/checksums и строгие V1/V2/receipts не переписывать.
2. Реализовать свою boundary и causal tests с отрицательными соседними случаями.
   Полная route/resource матрица включает raw download/Git/PAT/jobs.
3. На заполненных isolated копиях проверить additive migration/retry/rollback,
   сохранность документов/ролей/history и union подтверждённого прежнего чтения.
   Ordinary selected snapshot; all только verified platform admins. Неизвестные
   Wiki auto-admin привилегии разобрать до activation; расширение чтения показать.
4. Проверить гонки archive/create/link/start, lost ACK/reconcile/restart и
   подтверждённый drain без таймера/force stop. Wiki projection только от Tracker.
5. Scoped checks в ходе работы, один integrated gate полного compatible serving
   cohort. Backend/SDK сначала, activation/UI затем; incompatible route блокирует.
6. Dev Firebat2 installation через PDLC4 после backup/rehearsal. Rollback только
   compatible guarded cohort с новой policy/links. Served provenance и свежая IAB
   обычным/admin со screenshots после последнего изменения.

Source/tests/publication/images/migration/live — отдельные gates. Прежние 1:1
планы исторические; новая модель не меняет смысл технических receipts.
Production входит в явно порученный выпуск 2026-10-21 после rehearsal, dev и backup. PDLC1/2/3, Hermes и соседи исключены. Не смешивать с прежними Workflow
исправлениями профессий. Зависимые PR без автоматического merge.

### Human resource authorization (2026-10-21)

Tracker ProjectAccessV2 is the authority for human project visibility, source
identity and the original deadline. Workflow professions remain shared execution
configuration. PMExecution supplies an exact per-task immutable Tracker owner;
ambiguous legacy tasks without such a binding are hidden, never guessed from
profession membership. ResourceExecutionContext uses its verified project and
task instance. SQLAlchemy applies owner filters before query counts, pages and
history. Central members do not acquire Workflow mutation/operator rights.
Native runtime routes retain their separately authenticated exact protocols.

### PostgreSQL and retained SSR data

Migration0016 adds row and deferred commit checks to the actual owner tables,
using a transaction-local snapshot of the original human proof. Task ownership
comes from the exact PMExecution binding; context ownership includes its real
SpaceRef. Confirmed native protocols have no human GUC and retain their existing
checks. Shared profession/workflow definitions still require the operator role.
The proof is never renewed by a connection, SQL wait or commit. No legacy rows
or roles are rewritten. Rollback requires a compatible guarded cohort.

SSR refreshes display metadata from the authorized owner endpoint. Unchanged
rights keep drafts; changed rights or original expiry discard private DOM and
owner autosave before reloading. This forced retirement bypasses draft leave
confirmation. BFCache snapshots stay hidden until fresh server rendering.
This source change is not evidence of dev or production activation.
