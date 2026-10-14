# Single-Task Workflow Installation

Workflow поддерживает opt-in установку собственного семейства `single-task-v1`,
catalog version 1: семь namespaces, семь workflows, восемь modes и 24 phases.
Default остаётся `legacy`. **Установка не активирует live исполнение**:
Tracker/Fleet policy и API integration остаются pending parent.

Bounded profile-aware execution и typed PM packet реализованы отдельно:
[Single-Task Runtime Packet](single-task-runtime.md). Ниже ограничения прежнего
source-installer пакета отмечены как исторические; live activation по-прежнему запрещена.

## Bootstrap И Readback

Existing selector `PROJECT_WORKFLOW_CATALOG_VARIANT=single-task-v1` выбирает новый
профиль в `python -m scripts.init_db`. Это реальная установка через existing
initialization transaction, catalog lock, repositories и profession membership.
Команда читает явный `DATABASE_URL`; здесь она проверена только на временной SQLite.
Live runtime не менялся. Не направлять этот запуск на live до parent acceptance.

Bootstrap печатает typed installation readback после успешного commit. Повторный
запуск полностью сверяет content/relations и сохраняет реальные IDs/counts.
Drift, partial install и foreign collisions отклоняются без repair. Ошибка первого
создания откатывает transaction. Legacy metadata/defaults/task/history не меняются.

Новые GET зарегистрированы в существующем runtime router:

- `/internal/runtime/profiles/single-task-v1/installation` → `SingleTaskInstallationResponse`.
- `/internal/runtime/profiles/single-task-v1/namespace-bindings/{namespace_id}` → `SingleTaskBindingResponse`.

Используется existing catalog credential `PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN`;
это прежнее имя настройки, не новый owner и не требование запускать Fleet.
Нет нового controller, installer HTTP endpoint или runtime proof surface.
Unknown credential → 401, role runtime/assignment credential → 403,
missing/divergent installation → 409, dependency unavailable → 503.
Namespace ID — canonical positive decimal string; unknown ID → 404.
Даже один binding возвращается только после persisted проверки всех 7/7/8/24.
Успешный ответ имеет `Cache-Control: no-store`.

DTO содержит instruction profile/manifest hash, catalog version/hash, actual
namespace/workflow IDs, role/launch profile, role instruction hash, mode IDs/scopes
и phase IDs. `runtime_ready=false`, `live_activation_allowed=false`.
Installed binding не является runtime admission или Tracker transition receipt.

## Source И Pins

Устанавливаются отдельные `project_workflow/references/single_task_catalog_v1.json`
и `single_task_manifest_v1.json`, проверяемые по фактическим UTF-8/LF bytes:

```text
catalog:  b7b8bed470dc8a8730c8c1b1af8db0d556afec652394c569a9b0e97a64b6dcfd
manifest: e5e67111d89a0eeae89b6f78da6c887281cca187d7ea7792822d76ce2c4cc7a8
```

`python -m scripts.build_single_task_profile --check` проверяет воспроизводимость.
Это отдельная редакция от `docs/proposals`: их hashes и исходный module `fb9dd53`
сохранены. Новый instruction overlay имеет собственный source path/hash.
Base `PACKAGE_COMMIT`, catalog pins/source и legacy history не переписываются.

Редакция 14 октября добавляет разрешённые sealed role artifacts через существующий
Tracker CLI; hash нового ещё не выпущенного profile family изменён вместе с pins.
PM-инструкции сохранены, но общий manifest hash относится ко всем профессиям.
Не заменять его в старых заданиях, истории или установленном каталоге вручную:
свежий профиль проверяется в disposable QA, установка совместимого набора сервисов
и назначений выполняется отдельно. Эти source-изменения не включают поток на стенде.

Новые identities: namespace `single-task-<role-with-hyphens>`, workflow
`single-task-v1:<canonical-role>`, launch profile `single-task-v1-<role-with-hyphens>`.
Wire role — `devops`; только Fleet boundary явно отображает его в `dev_ops`.

## Assignment И Guard (Installer Baseline)

До bounded execution пакета existing assign endpoint принимал `SingleTaskAssignmentRequest`:
`instruction_profile=single-task-v1`, exact manifest hash и canonical Tracker UUID
с `business_task_ref == root_task_ref`. Decomposition revision может отсутствовать/null
и не может быть фиктивной строкой. Legacy request сохраняет обязательность поля.
Profile branch отвергает legacy workflow key, aggregate scope и Base admission.
Общие workspace/queue/work-item inputs пока сохраняются; их producer mapping не выдуман.

**Историческая граница installer-only пакета.** Тогда DB constraint
`ck_task_runtime_assignments_binding_complete` требует decomposition revision для
ordinary assignment. Нужна отдельно согласованная DB-адаптация; migrations здесь
не добавлялись. Теперь additive `0015` и standalone profile DTO описаны в runtime packet.
Parent по-прежнему владеет Tracker/Fleet policy и registration.

Existing assign/bind/rebind/step сохраняли раздельные credentials и assignment/run
fence проверки. Новый family key явно блокируется до parent integration независимо
от version 1 в installer-only пакете. В bounded execution этот blocker заменён
installed profile + authenticated binding guard. Human/local-DB Supervisor step не создаёт задачу и не исполняет
существующий unbound cursor этого семейства. Нового terminal owner нет.

## Tracker Instructions

Read-only сверены текущие parser/dispatch и `SubmitDeliveryProposal`:

- PM: `task-tracker sdlc confirmation read --task <UUID> --revision <REVISION>`;
  `--revision` обязателен в фактическом parser. Текущий dispatch использует direct
  `GET requirements/{revision}/confirmation` под own-task PM grant. Receipt
  проверяется по task/revision/hash/owner; исторический stage=Backlog не заменяет
  текущий lifecycle. Missing/denied/stale readback оставляет phase 3 незавершённой.
  PM не читает intent и не заимствует scheduler/owner credentials ради обхода.
- Non-PM: `task-tracker sdlc result propose --task <UUID> --from-file <proposal.json>`.
- Readback: `task-tracker sdlc result operation --task <UUID> --key <KEY>`.

Proposal содержит ровно `fence`, `workflow_receipt`, `result`, `idempotency_key`.
ArtifactReceipt содержит `reference`, `sha256`. Fence/receipt выдаёт владелец.
Reviewer verdict — `approved|rework`, Tester — `passed|rework`, DevOps —
`deployment` и `verification`; verification покрывает exact artifact/health/acceptance.

Non-PM: после accepted Workflow complete=true агент публикует proposal **пока run жив**,
сверяет actual `proposal_id/output_sha256` через operation, возвращает их с original
key в отчёте и завершает run. Proposal сам не меняет stage. После actual terminal
Fleet проверяет proposal и делает schedulerComplete; Fleet/operator читает итоговые
stage/status через registered lifecycle readback. Агент не удерживает run polling-ом.
Lifecycle CLI команды в inspected parser нет: инструкции её не придумывают.
Tracker API registration pending parent; missing/403/404/unknown acceptance — blocker,
не permission для generic patch, scheduler credential или фиктивного receipt.

Current instruction audit, grant restrictions and exact consumer prerequisites:
[Single-Task Instruction Audit](single-task-instruction-audit.md). Content/hash
updates are source-only; existing installed content must not be silently repaired.

### PM Phase Ordering

Фазы 1/2 отчитываются только о подготовке и останавливаются на следующей фазе,
не пытаясь довести весь Workflow до complete. Phase 3 строго упорядочена:

1. Показать полный сохранённый документ с exact revision/content_hash.
2. Ждать actual owner confirmation в checkpoint при незавершённой phase 3.
3. Feedback перерабатывает документ в том же execution/assignment/cycle;
   новая revision/hash отменяет старое consent и показывается целиком заново.
4. Прочитать реальный confirmation receipt и сверить task/revision/hash/owner.
5. Только теперь отправить final Workflow report, проверить complete=true
   и завершить PM run. PM не dispatch-ит Analyst.

Consent может создать Analysis / Ready intent в Tracker, но Analyst reserve
заблокирован до PM actual completion. Дополнительные PM assignment cycles
или resume completed execution не являются способом реализовать ожидание.

Legacy PM checkpoint/resume DTO остаётся answer-only. Opt-in typed contract реализован
в runtime packet на существующих endpoints. Исходная dependency формулировалась как
typed `input_kind=answer|feedback|confirmation`: только answer ссылается на реальный
question/answer event, feedback не получает фиктивный answer ID, confirmation
ссылается на существующий real confirmation receipt. До интеграции typed contract
фаза остаётся unfinished с явной зависимостью. В installer-only пакете shared wire,
checkpoint/resume implementation и migrations не менялись. Проверки фазы требуют
actual receipt и разрешённых зависимостей до final report; это instruction gate,
не заявление о готовом runtime enforcement.

Installed artifact hashes обновлены только для source-only opt-in семейства.
Установка предыдущего content отклоняется как drift, автоматически не ремонтируется;
live catalog не активировался и legacy/proposal pins не изменены.

## Validation И Parent QA

Focused tests: настоящий `init_db` дважды, persisted router readback, coexistence
с авторскими legacy edits/task/history, rollback, drift, task=root DTO,
auth/version-1 bypass rejection, source hashes и producer/terminal последовательность.
Отдельно persisted PM phase 3 проверяется на presentation/checkpoint/feedback/readback
до единственного final report, наличие receipt checks/evidence и отсутствие
premature complete в preparation reports.

Parent QA: согласовать exact Tracker/Fleet DTO до использования, адаптировать
assignment constraint, подключить actual terminal/lifecycle readback; проверить
полный single-task flow, оба Rework возврата, replay/stale fences, PG persistence
и deployment artifact/health/acceptance. Docker/PG/build/live activation здесь не выполнялись.
