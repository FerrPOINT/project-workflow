# Single-Task Profile: Activation Proposal

Исторический review proposal `a51f576`. Workflow-owned bootstrap/readback теперь
согласованы и реализованы в [installation package](single-task-installation.md).
Routing v2 ниже остаётся историческим предложением: его exact DTO и Tracker/Fleet реализация
не согласованы как готовый контракт и не используются. Прежние review artifacts
и hashes сохранены отдельно от устанавливаемой редакции инструкций.

Статус: **предложение для согласования, не реализованная активация**.
Исходные инструкции: Workflow `fb9dd53c90cb4c421ffa12c0c766ca54961f2003`.
Ни bootstrap, ни текущие Tracker/Fleet owner contracts этот профиль не принимают.
Standalone loader остаётся source-only и не должен рекламироваться как активируемый.

## Проверенная Несовместимость

Tracker проверен read-only: HEAD `9eac790a332d9501511d8cac2a3ef0f3ac7ddc23`
и текущие рабочие файлы соседнего worker. Его незакоммиченные lifecycle/CLI правки
не изменялись и не считаются опубликованным контрактом producer.

| Граница | Текущая проверка | Почему нельзя подставить новый hash |
| --- | --- | --- |
| Tracker `domain/src/sdlc_routing.rs` | `RoleRoute`, `PACKAGE_COMMIT=4b9b4c9297a13fb28a6ba2039af2f7cb719f2f58` | `package_commit` означает services-base package, не Workflow commit |
| Tracker `app/src/sdlc_routing.rs::validate_routes` | catalog 3, `hermes-*` namespace, `hermes-sdlc:*` workflow, фиксированный role profile | Новые identities и версия отвергаются ещё до owner readback |
| Tracker migration `m20261001_0000034_sdlc_clarification.rs` | SQL `sdlc_valid_role_routes`, тот же commit/profile/version и точный набор полей | Даже ослабление Rust validator не позволяет записать новый routing |
| Tracker routing revisions/snapshots | CHECK `contract_version=1`; snapshot `task_id=root_task_id` | Новая routing ветка требует согласованной новой migration; task=root уже поддерживается |
| Tracker `app/src/sdlc_configuration.rs::compare` | Base package proof repository/schema, package commit/hash/profile, Workflow binding skills revision | Workflow-owned manifest нельзя выдать за proof старого Base package |
| Workflow `ManagedWorkflow/ManagedCatalog` | Только legacy keys, 11 modes, 33 phases, закреплённые terminal markers | Новый каталог 7/8/24 не проходит загрузку |
| Workflow `config.py`, `scripts/init_db.py` | Только variants legacy/base; повторный bootstrap пропускает ensure по сравнению номера версии | Нет ни установки нового семейства, ни гарантированного readback при повторе |
| Workflow `BaseNamespaceBinding`, `BaseAdmission` | Base versions 3/4, фиксированные skills revisions | Нельзя включать Workflow-owned профиль в эти DTO под видом Base |
| Workflow `RuntimeAssignmentRequest` | Обязательный `decomposition_revision_ref`, work-item/queue/workspace refs | Нельзя генерировать фиктивную decomposition revision для одной задачи |
| Workflow `assert_base_step/supervisor` | Все mode versions ≥3 требуют Base admission | Глобальный version 5 сам по себе не создаёт новый execution contract |
| Workflow build compatibility | `scripts/build_runtime_image.py` принимает только legacy/base | Новая config enum сама по себе не квалифицирует собранный image |

`RoleRoute` сам не перечисляет 11 modes: это ограничение пакета/Workflow catalog.
Tracker preflight сейчас проверяет наличие запрошенного mode в package, а не весь
точный single-task inventory. Для нового профиля нужна сверка полного 7/8/24 manifest.

## Настоящие Review Artifacts

- [Draft catalog](proposals/single-task-v1.catalog.json): все 24 фазы, инструкции,
  checks/evidence и отдельные новые identities.
- [Draft profile manifest](proposals/single-task-v1.manifest.json): exact catalog hash,
  семь role instruction hashes, source commit/hash и полный разрешённый inventory.
- `python -m scripts.prepare_single_task_profile_proposal --check`: воспроизводимость
  committed artifacts, без установки, DB или API calls.

Schema names этих двух файлов являются **предложенными форматами review artifacts**,
а не зарегистрированными публичными API schemas. Manifest содержит `proposal=true`.
Ни один hash не является installed receipt, package proof или runtime admission.

Source commit относится только к существующему модулю инструкций и его identity
donor: оба Git blob проверены и закреплены SHA-256. Снимок нового каталога является
отдельным локальным derivative, он не приписывается содержимому того commit.
Этот commit доступен в локальном Workflow Git; публикация в remote этим пакетом
не заявляется. Фактические hashes текущих review artifacts:

```text
catalog:  1b04602d82967d0f873af762c983547f6fbd78a2c490e7cb1660d335896fa321
manifest: 76c721172e0d22a47f014e9374c63c6fc16c3fec844f385eda26637ee7580413
```

Генератор отказывается при изменении любого входа, а не выдаёт moving working tree
за прежний source commit. Изменения инструкций после Tracker producer report потребуют
новых artifact hashes и новой согласованной редакции, без изменения прежних receipts.

Catalog hash = SHA-256 фактических UTF-8/LF bytes файла без BOM, с конечным LF.
Manifest hash вычисляется над его bytes тем же способом и не включается в себя.
Точечные `.gitattributes` закрепляют LF только для этих двух файлов; `--check`
сравнивает их реальные bytes без нормализации, включая проверку на Windows.
Role instruction hash = SHA-256 canonical JSON полного массива modes соответствующей
роли: UTF-8, sort_keys, compact separators, без конечного LF. Catalog не содержит
manifest hash, поэтому циклической зависимости hashes нет.

## Отдельные Identities

Предлагается `instruction_profile=single-task-v1`, profile version 1 и
`workflow_catalog_version=1` внутри нового семейства workflow keys. Это не Base v1/v5
и не замена старой global metadata. Номер версии сравнивается только вместе с
instruction_profile/workflow family и exact hash.

| Wire role | Namespace | Workflow key | `RoleRoute.profile` / launch profile | Modes / scopes |
| --- | --- | --- | --- | --- |
| project_manager | single-task-project-manager | single-task-v1:project_manager | single-task-v1-project-manager | draft / business |
| analyst | single-task-analyst | single-task-v1:analyst | single-task-v1-analyst | analysis / business |
| architect | single-task-architect | single-task-v1:architect | single-task-v1-architect | decomposition / business |
| developer | single-task-developer | single-task-v1:developer | single-task-v1-developer | initial, rework / delivery |
| reviewer | single-task-reviewer | single-task-v1:reviewer | single-task-v1-reviewer | delivery / delivery |
| tester | single-task-tester | single-task-v1:tester | single-task-v1-tester | delivery / delivery |
| devops | single-task-devops | single-task-v1:devops | single-task-v1-devops | delivery / delivery |

Здесь `RoleRoute.profile` обозначает смысл будущего role launch profile;
существующий legacy DTO пока отвергает эти значения. Parent должен согласовать
конкретное новое profile-aware DTO, прежде чем его producer начнёт их отправлять.

Новые CLI wrapper names: `workflow-single-task-<role-with-hyphens>`.
При legacy installation рядом остаются прежние семь namespaces/workflows: профиль
добавляет собственные семь, не переписывает `launch_profile`, defaults, old mode IDs,
bindings или task/history. На чистой БД профиль устанавливает ровно семь своих.
IDs извлекаются только из фактической установки, не включены в source manifest.
Agent IDs и effective Fleet revisions также выдаёт владелец, а не этот proposal.

Инвариант назначения: canonical Tracker task UUID равен root UUID во всех stage,
assignments, reports, receipts и Rework cycles. Workflow session key остаётся локальным
ключом, но его external task/root refs указывают на один UUID. Ни children, ни aggregate
scope, ни decomposition revision/barrier не служат условием назначения этого профиля.

Canonical wire role в Tracker/Workflow/manifest/report/receipt — `devops`.
Единственная явная адаптация на Fleet boundary: `devops` ↔ `dev_ops`.
Остальные роли передаются без изменений. Эта карта не применяется к profile names,
workflow keys или историческому Fleet enum и не допускает общий heuristic rename.

## Публичные Изменения Для Согласования

Рекомендуется явная profile-aware ветка routing contract, сохраняя legacy v1 payload
и validator неизменными. Не делать optional arbitrary package_commit/hash и не
расширять allowlist просто на любой 40/64-символьный hex.

1. **Tracker routing DTO/SQL.** Предлагаемые SetRoutingPolicy/Policy/Snapshot v2
   используют `contract_version=2`, `instruction_profile=single-task-v1` и
   `instruction_manifest_sha256` из согласованного manifest. Новый route сохраняет
   реальную executor identity/effective revision и namespace/workflow/profile/catalog version/hash поля,
   но не требует и не подделывает legacy `package_commit/package_manifest_sha256`.
   Seven-role map, CAS/idempotency, immutable policy/snapshot hashes и task=root
   остаются обязательными. Нужны новая Tracker migration для отдельной v2 validation
   ветки CHECK/SQL и обновление OpenAPI/codegen владельцем. Старую migration не править.
2. **Workflow installed readback.** Предлагаемый отдельный
   `single-task-sdlc/workflow-binding/v1` возвращает фактические namespace/workflow IDs,
   role, launch profile, instruction_profile, manifest hash, catalog version/hash,
   точные modes/scopes и role instruction hash. Сохранить decimal-string IDs.
   Возвращать результат только после полной сверки persisted 7/7/8/24 под catalog lock;
   `runtime_ready=false` не выдаёт execution proof. Endpoint/path и его auth owner
   согласуются отдельно; действующий `/base/namespace-bindings` и его DTO не менять.
3. **Configuration observation.** Новая профильная ветка сравнивает свежие
   installed Workflow binding и effective executor configuration с одним согласованным
   manifest, включая полный mode inventory и exact instruction hashes. Она не требует
   ложный `base-sdlc/package-proof/v1` для Workflow-owned инструкций. При использовании
   Fleet его producer/consumer DTO и managed-file hashing меняет владелец Fleet;
   terminal-only исполнитель должен дать эквивалентное authenticated observation,
   не фиктивный Fleet agent/config/package. Owner и способ readback требуют решения parent.
   Для terminal ветки `agent_id/fleet_config_revision` не становятся обязательными
   legacy Fleet полями: предлагается явный discriminator исполнителя, конкретный
   terminal-owner identity/config reference и его readback. Точную форму этой ветки
   согласует parent; manifest инструкций от выбора исполнителя не зависит.
4. **Workflow assignment/admission.** Предлагается отдельная profile-aware ветка
   existing assignment/bind/step контракта с instruction profile/manifest hash,
   canonical task/root refs и реальными workspace/lease/fence только там, где они
   нужны роли. Для single-task `decomposition_revision_ref` отсутствует, а не является
   выдуманной строкой; legacy DTO сохраняет прежнее обязательное поле. Проверки
   authorisation/owner binding/CAS/replay остаются обязательными. Не использовать
   catalog version 1 как обход Base guard: новое workflow family требует своего
   verified admission и fail-closed до его реализации. Public DTO/registration
   и возможные DB constraints согласует интегратор, ничего из этого здесь не изменено.

Минимальные owner решения: принять/изменить identities и version 1; выбрать владельца
публикации manifest и допустимый exact manifest hash; согласовать routing v2 и SQL
ветку; выбрать authenticated configuration observation и binding/admission DTO.
Формат producer result, command names и outcome vocabulary добавляются только после
реального Tracker producer report; нынешние missing-capability инструкции сохраняются.

## Bootstrap После Согласования

Предлагаемый opt-in selector: `PROJECT_WORKFLOW_CATALOG_VARIANT=single-task-v1`.
**Сейчас это значение не поддерживается, его нельзя использовать как команду активации.**

После согласования реализация использует existing initialization transaction,
catalog lock, workflow/mode/phase repositories и profession membership. Требуется
profile-aware catalog loader/validator и namespace identity policy; публичный Base
catalog/source pins не расширяются до нового профиля. Workflow DB migration для
самого каталога по текущей схеме не требуется. Assignment/admission constraints
проверяются отдельно после согласования их DTO, заранее отсутствие migration
для execution contract не обещается.

Установка атомарно создаёт семь новых namespaces/workflows, восемь modes, 24 phases,
instructions/checks/evidence. Не переназначает legacy namespace/workflow defaults.
Повторный `init_db` обязательно вызывает полную проверку нового профиля, а не
условие `installed_version >= requested_version`; сравнивает IDs/relations/content
и exact manifest/catalog hashes. Drift, частичная установка и foreign collision
дают ошибку без перезаписи чужого содержимого. Persisted readback не выдаётся из
source loader. Fresh source artifact не означает совместимость build/runtime.

## Проверки Parent QA

- Fresh SQLite и legacy+single-task coexistence: настоящий bootstrap, 7/7/8/24
  profile inventory, повторный запуск без изменения IDs/counts, возврат persisted binding.
- Legacy source pins, raw phase/instruction rows, namespaces/launch profiles,
  active/completed tasks и history побайтно/по значениям прежние после установки.
- Corrupt/missing rows, wrong family/version/hash, mixed-profile routes и
  unsupported selector дают fail-closed; никакого silent downgrade/Base impersonation.
- SQL и Rust routing v2 validators принимают тот же approved manifest и отвергают
  legacy `PACKAGE_COMMIT` в качестве provenance нового профиля; v1 regression проходит.
- `task==root` сохраняется до Deployment/Completed и через оба Rework возврата;
  единственная Fleet role adapter — explicit `devops` ↔ `dev_ops`.
- Первое действие каждой профессии — admitted Workflow step; report/receipt/replay
  проверяются после согласованного Tracker producer contract. Schema/API tests и
  единый PG QA принадлежат интегратору. В этом proposal нет Docker или runtime writes.
