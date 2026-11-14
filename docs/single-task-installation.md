# Single-Task Workflow Installation

Workflow поддерживает opt-in установку собственного семейства `single-task-v1`,
catalog version 1: семь namespaces, семь workflows, восемь modes и 33 phases.
Дефолт source-конфигурации — `single-task-v1`. **Установка не активирует live исполнение**:
Tracker/Fleet source integration уже реализована; source qualification не является
разрешением установки/активации на стенде. Exact source и оставшаяся live-граница:
[Single-Task Instruction Audit](single-task-instruction-audit.md).

Каталог определяет `role_key`, точные идентификаторы профессии и Workflow и
профиль запуска для [комплекта агента Fleet](https://github.com/FerrPOINT/fleet-control/blob/main/docs/AGENT_DEFAULTS.md#комплект-агента).
В ответе установки `required_tools` сопоставляет `role_key` и обязательные
инструменты. Tracker и Workflow добавляются для каждой профессии.
Дополнительные инструменты для новых и существующих профессий задаёт
`PROFESSION_TOOL_REQUIREMENTS` в `project_workflow/domain/single_task_profile.py`.
Base готовит зависимости по ответу установки.
Список дефолтных агентов берётся из установленного каталога; семь профессий —
состав версии 1. Учётку, секреты, ключ AI Hub и экземпляр подготавливает шаг
установки платформы. Workflow публикует и подтверждает привязку.

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
создания откатывает transaction. Существующая current-установка и её история
не переназначаются; переход прежних профессий описан ниже.

Чтобы явно выбрать каталог из установленного образа, оператор указывает SHA-256
манифеста из текущего installation readback.

```sh
python -m scripts.init_db --publish-packaged-catalog-from "$INSTALLED_MANIFEST_SHA256"
```

Команда под блокировкой валидирует установленное baseline family. Если его manifest
уже совпадает с packaged manifest, возвращается installation readback без записи:
операторские черновики и выбранные публикации сохраняются и не блокируют этот no-op.
В этой ветке допустим и прежний SHA-256 из поддерживаемых манифестов в аргументе команды.

Только при фактической замене baseline family команда требует точного совпадения
исходного manifest с аргументом, отклоняет операторскую публикацию или черновик
и добавляет базовую публикацию для всех ролей в одной транзакции. Для такой замены
операторские изменения требуют отдельного решения. Начатые задачи продолжают
использовать прежние mode ID и фазы. После публикации прочитайте новые привязки
и подготовьте конфигурации Fleet для новых назначений.

Installation manifest и bindings описывают sealed baseline provenance, а не
обещают, что выбранная операторская редакция совпадает с packaged content.
Фактические active `catalog_version`, `content_sha256` и `modes` читайте через
`GET /api/workflows/{workflow_id}/catalog` с существующими правами администратора;
контракт описан в [Catalog Publication API](managed-catalog-publication.md#json-api).

Новые GET зарегистрированы в существующем runtime router:

- `/internal/runtime/profiles/single-task-v1/installation` → `SingleTaskInstallationResponse`.
- `/internal/runtime/profiles/single-task-v1/namespace-bindings/{namespace_id}` → `SingleTaskBindingResponse`.

Используется existing catalog credential `PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN`;
это прежнее имя настройки, не новый owner и не требование запускать Fleet.
Нет нового controller, installer HTTP endpoint или runtime proof surface.
Unknown credential → 401, role runtime/assignment credential → 403,
missing/divergent installation → 409, dependency unavailable → 503.
Namespace ID — canonical positive decimal string; unknown ID → 404.
Даже один binding возвращается только после persisted проверки всех 7/7/8/33.
Успешный ответ имеет `Cache-Control: no-store`.

DTO содержит instruction profile/manifest hash, catalog version/hash, actual
namespace/workflow IDs, role/launch profile, role instruction hash, mode IDs/scopes
и phase IDs. `runtime_ready=false`, `live_activation_allowed=false`.
Installed binding не является runtime admission или Tracker transition receipt.

## Переход С Прежнего Base-Каталога

Миграция `0033_profession_transition` выполняется штатным `scripts.init_db`
в общей транзакции миграции и bootstrap. Для точного опубликованного Base-v4
(`hermes-sdlc:*`, active catalog4) она сохраняет IDs существующих профессий,
добавляет current workflows с sealed baseline и переключает на них default
workflow каждой профессии. CLI/code/profile и стандартные названия этой же
профессии принимают значения current `single-task-v1`; theme сохраняется.
Новых параллельных профессий не создаётся. Это явный forward transition,
а не переключатель env или возможность исполнять прежний протокол после отказа.

Старые workflow/mode/phase IDs, membership, задачи и отчёты сохраняются для
исторического чтения. Сохранённые FK указывают на исходный workflow, независимо
от нового default профессии. Повтор не добавляет workflow или publication.
Если global default выбирал legacy workflow, его флаг выбора переходит к
соответствующему current workflow той же роли. Внешний custom default не меняется;
это изменение текущего выбора, а не исторического содержимого.
Raw editor API отвергает запись в retired `hermes-sdlc:` workflow и его фазы;
чтение истории сохраняется. Авторские workflows остаются редактируемыми,
включая standalone: этот режим не исполняет платформенный `hermes-sdlc`.
Установка, уже содержащая валидный `single-task-v1`, не переназначается,
включая её текущие исполнения и принятые публикации.

До первой записи переход проверяет опубликованный Git blob Base-v4, полный
каталог и его содержимое, однозначную profession membership, незанятые current
идентичности и отсутствие незавершённых legacy задач/bindings. Изменённый каталог,
операторский профиль, конфликт владельца или неподтверждённый PM terminal
отклоняются с откатом всей initialization transaction. Неподдерживаемые старые
семьи не подменяются defaults.

SQLite regression проходит через фактический predecessor `0015`, v3/v4 modes и
normal init; PostgreSQL node —
`tests/test_legacy_profession_transition_postgres.py::test_0015_base_v4_adopts_current_professions_and_preserves_history_postgres`.
Он использует существующий owner fixture `pg_url` и marker `integration`;
отсутствие его PG prerequisites/skip не считается приёмкой. Смена исходников
не доказывает миграцию или установку на Relevanter/PDLC.

## Source И Pins

Устанавливаются отдельные `project_workflow/references/single_task_catalog_v1.json`
и `single_task_manifest_v1.json`, проверяемые по фактическим UTF-8/LF bytes:

```text
catalog:  9db2e982d93ead86a16c0b88785cbb9a5e1306e74cd56dc929ab7f7d1342f605
manifest: 2f16635c0f588d1f285393b4ad8c163119b4dba4b9918335c821f295e88a4f64
```

Миграции0029/0030 публикуют дефолт Analyst с 12 фазами через существующий
журнал версий. Занятые пользовательские номера не переиспользуются; исходные
mode/phase IDs, черновики, публикации и история задач сохраняются.
0030 также обрабатывает уже применённый исходный0029 без перезаписи его строк.
[Полный процесс и граница приёмки](analyst-workflow.md). Старые catalog/manifest
сохранены как исторические данные; новые назначения используют текущую семью.
Task/step history и исходные hashes прежних receipts не переписываются.

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

DevOps выбирает контракт по опубликованному owner target рецепта Forge.
Для `base_resource_rollout` исходная операция Check получает
`result.baseOperationObservation` с `forge/base-operation-observation/v1`
и запечатанной квитанцией `pdlc/resource-rollout-delivery/v1` в фазе `complete`.
Для pipeline deployment сохраняется `result.deploymentObservation` в фазе
`deployed`. Физическое применение Base выполняет владелец установки.
После публикации его квитанции DevOps сверяет ту же операцию Check командой
`cicd-cli dev-workspace reconcile`, затем читает исходный UUID операции.
Кандидат, исходная публикация, назначение и сессия сохраняются.

Обновление инструкций собирается `python scripts/build_single_task_profile.py`,
а `--check` проверяет артефакты и runtime pins выбранного checkout.
После поставки нового пакета владелец установки публикует каталог штатной командой
`python scripts/init_db.py --publish-packaged-catalog-from <installed-manifest-sha256>`.
Обычная повторная инициализация сохраняет установленный каталог. Явная публикация
сверяет прежний manifest и добавляет новые редакции, сохраняя существующие
исполнения и их snapshots. Неизвестная редакция либо пользовательский черновик
требует сверки до публикации. Предыдущий sealed manifest остаётся доступен для чтения.

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
