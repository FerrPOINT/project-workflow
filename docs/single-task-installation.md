# Single-Task Workflow Installation

Workflow поддерживает opt-in установку собственного семейства `single-task-v1`,
catalog version 1: семь namespaces, семь workflows, восемь modes и 24 phases.
Default остаётся `legacy`. **Установка не активирует live исполнение**:
Tracker/Fleet source integration уже реализована; source qualification не является
разрешением установки/активации на стенде. Exact source и оставшаяся live-граница:
[Single-Task Instruction Audit](single-task-instruction-audit.md).

Bounded profile-aware execution и typed PM packet реализованы отдельно:
[Single-Task Runtime Packet](single-task-runtime.md). Ниже ограничения прежнего
source-installer пакета отмечены как исторические; live activation по-прежнему запрещена.

## Bootstrap И Readback

Existing selector `PROJECT_WORKFLOW_CATALOG_VARIANT=single-task-v1` выбирает новый
профиль в `python -m scripts.init_db`. Это реальная установка через existing
initialization transaction, catalog lock, repositories и profession membership.
Команда читает явный `DATABASE_URL`. Текущая семья проверена на настоящем
временном PostgreSQL с сохранением legacy rows/history и persisted readback:
[PG1 evidence](current-family-postgres-20261016.md). Live runtime не менялся;
не направлять этот запуск на live до согласованной установки.

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
catalog:  86e6c983b7aa6a2c99da11d1d4b1f1b4563ff913262236903a19bc86bdec2d67
manifest: 652a38c0f7bdb48a569aa3fcd5c2e81e153db6e22b5201cfb6ce15c988dd57f3
```

16October typed backend image-build instructions change sealed content/hashes, not role IDs or
profile/protocol versions. Existing installation with an older manifest is drift:
observation/init must not repair it silently. Coordinate reviewed installation
adoption and Fleet effective configuration revisions before activation; never
relabel old assignments, terminal receipts or history with the new hash.

`python -m scripts.build_single_task_profile --check` проверяет воспроизводимость.
Это отдельная редакция от `docs/proposals`: их hashes и исходный module `fb9dd53`
сохранены. Новый instruction overlay имеет собственный source path/hash.
Base `PACKAGE_COMMIT`, catalog pins/source и legacy history не переписываются.

Предыдущая редакция 14 октября добавляла разрешённые sealed role artifacts через существующий
Tracker CLI; соответствующие artifacts и pins опубликованы в Workflow source
`d0ea6b181f7b6beb292297404df0fa0dc8743a9c` и проверены отдельно от live rollout.
Текущий source-кандидат добавляет critical-business ветку техническим ролям и
отдельную инструкцию PM review для доверенно выданного нового assignment той же
задачи. Обычный PM brainstorming/confirmation текст сохранён. Требуются новый
Tracker CLI с `critical-blocker submit/read/operation`, существующий `jq`,
согласованный non-secret export `FLEET_CRITICAL_BLOCKER_KEY` в приватном `env.sh`
и доверенный PM review input;
старый CLI2aa и исходный Draft snapshot этого не обеспечивают. Подробные границы
даны в [аудите инструкций](single-task-instruction-audit.md).
Общий manifest hash относится ко всем профессиям.
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
Parent владеет Tracker/Fleet policy и её развёртыванием; source registration уже
есть в согласованном Tracker817, а не остаётся текущим installer blocker.

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
- Current lifecycle: `task-tracker sdlc lifecycle --task <UUID>`.
- Accepted result: `task-tracker sdlc result read --task <UUID> --result <RESULT_UUID>`.

Последние две команды реализованы в Tracker CLI
`2aa87cbc9061f60b626f11f26de2281693f8b05f`; server
`81759bbb8a07c1076b9c3c4f97c7af058b626dd2` регистрирует соответствующие GET routes.
Own-task delivery reader требует `task-tracker:read`, exact current assignment,
bound machine subject, актуальную requirements revision и project authorization.
Это не PM grant, scheduler authority или доступ ко всему проекту.

Proposal содержит ровно `fence`, `workflow_receipt`, `result`, `idempotency_key`.
ArtifactReceipt содержит `reference`, `sha256`. Fence/receipt выдаёт владелец.
Reviewer verdict — `approved|rework`, Tester — `passed|rework`, DevOps —
`deployment` и `verification`; verification покрывает exact artifact/health/acceptance.

Non-PM: после accepted Workflow complete=true агент публикует proposal **пока run жив**,
сверяет actual `proposal_id/output_sha256` через operation, возвращает их с original
key в отчёте и завершает run. Proposal сам не меняет stage. После actual terminal
Fleet проверяет proposal и делает schedulerComplete; Fleet/operator читает итоговые
stage/status через registered lifecycle readback. Агент не удерживает run polling-ом.
В Fleet `d5d6643e288dbdf858f060538dca34295ac62bd3` consumer уже сверяет actual
Workflow terminal receipt, proposal и raw role artifacts под delegated child PAT,
затем заново читает current authority/fence перед существующим Complete.
API/grant/consumer source реализован, но требуется совместимый actual deployment;
missing/403/404/unknown acceptance — blocker,
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
ссылается на существующий real confirmation receipt. До реализации typed contract
фаза оставалась unfinished с явной зависимостью. В installer-only пакете shared wire,
checkpoint/resume implementation и migrations не менялись. Проверки фазы требуют
actual receipt и разрешённых зависимостей до final report; тот пакет задавал
instruction gate, а текущий implemented runtime guard описан в runtime packet.

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

Source integration включает additive assignment constraint, typed PM packet,
terminal/lifecycle/result readback и consumer artifact hook. Уже полученное parent
source QA описано в instruction audit; этот docs-only пакет его не повторяет.
Remaining acceptance: actual installed deployment manifest/credentials/policy,
native completion witness, полный single-task flow, оба Rework возврата,
replay/stale fences и deployment artifact/health/acceptance. Source/PG qualification
не подменяет эти live receipts. Docker/PG/build/live activation этим пакетом не выполнялись.
