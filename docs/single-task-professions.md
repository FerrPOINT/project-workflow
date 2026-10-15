# Single-Task Professions V1

Opt-in preset `single-task-v1` принадлежит Workflow. Он содержит реальные инструкции,
checks и evidence семи профессий для одной Tracker задачи: восемь режимов,
24 последовательные фазы. Исходный baseline Workflow:
`6a50985841daa22aa6513868548a5d0b897fac44`.

Source-only чтение подготовленных инструкций (не точка активации):

```python
from project_workflow.infrastructure.single_task_catalog import load_single_task_professions

professions = load_single_task_professions()
```

Исходный loader остаётся source-only. Реальная opt-in установка использует отдельные
profile artifacts, existing bootstrap и persisted readback:
[single-task installation](single-task-installation.md). Установка не разрешает live
исполнение: Tracker registration и assignment DB adaptation остаются pending parent.
Результат этого loader нельзя выдавать за installed binding.

Функция возвращает независимые определения профессий с существующими workflow keys,
mode keys, phase codes, namespace/profile и именами skills. Каждый режим проверяется
существующим `ManagedMode`, фазы совместимы с существующим Supervisor. Это подготовка
default инструкций для выбранного preset, а не установка в runtime. Функция ничего
не пишет в БД, не запускает агентов и не модифицирует Hermes.

## Совместимая Активация

Актуальное предложение интегратору: отдельные namespaces/workflows/launch profiles
семейства `single-task-v1`, catalog version 1 внутри нового семейства, явный opt-in
через реализованные bootstrap и installed readback, без live dispatch. Прежнее предложение переиспользовать
legacy identities отозвано: Tracker связывает их со старым package и metadata.
Не переиспользовать номер pinned Base catalog как номер этого preset.
Текущий `ManagedCatalog` требует 11 режимов и прежнюю terminal policy,
поэтому передавать ему эти восемь режимов как старый catalog запрещено. Workflow-owned
bootstrap/readback и profile assignment DTO реализованы отдельно; Tracker routing DTO,
DB migrations, Base metadata и live runtime не менялись.

`base_sdlc_catalog_cli_v4.json` используется только как donor технических identities
и имён skills; автор новых текстов — Workflow. Исходный `skills_source`, Base SHA,
catalog pins, history, установленный default и legacy integration modes сохранены.
Preset не заявляет, что новые инструкции опубликованы в pinned Base source, и не
устанавливает внешние skills. Совпадение имён profiles не доказывает совместимость
исполнителя. Интегратор должен сохранить старые назначения и receipts и выбирать
новый preset явно, без перепривязки history к новым инструкциям.

Обычный terminal вызывает установленные `project-workflow`, `task-tracker`,
`cicd-cli`. Первое рабочее действие каждого агента — Workflow step без report
в назначенном namespace; только затем читаются Tracker и рабочие входы.
Workflow task key и canonical Tracker task UUID различаются; mapping выдаёт launcher.
Если выдан scoped runtime context, применяются существующие runtime flags без
понижения авторизации. Это не требование использовать Fleet и не добавление нового
протокола admission. Подготовка назначения/namespace и разрешённой identity
остаётся зависимостью интегратора.

## Роли И Передачи

| Профессия | Mode | Работа | Разрешённая следующая stage / status |
| --- | --- | --- | --- |
| PM | draft | Brainstorming, clarification, requirements review внутри Draft | Exact owner confirmation: Backlog / Ready; затем Tracker pickup: Analysis / Ready |
| Analyst | analysis | Анализ и coverage требований одной задачи | Architecture / Ready |
| Architect | decomposition | Только архитектура и текстовый план одной задачи | Development / Ready той же задачи |
| Developer | initial | Реализация и evidence точного candidate | Review / Ready |
| Developer | rework | Исправление frozen findings | Review / Ready, затем Testing заново |
| Reviewer | delivery | Независимое review candidate | passed: Testing / Ready; needs_rework: Rework / Ready |
| Tester | delivery | Проверка acceptance candidate | passed: Deployment / Ready; needs_rework: Rework / Ready |
| DevOps | delivery | Artifact, deployment, health, deployed acceptance | Deployment / Completed |

Stages: Draft, Backlog, Analysis, Architecture, Development, Review, Testing,
Rework, Deployment. Status отдельно: Ready, InProgress, Completed. `waiting_reason`
и runtime state не заменяют status. Агент не выставляет InProgress сам при старте.
Никаких children/decomposition cards, delivery DAG, aggregate scopes или integration
barriers в новом flow. Старые integration modes остаются доступными старому flow.

PM обсуждает идею маленькими итерациями: варианты, компромиссы, противоречия,
свободные ответы и один значимый вопрос за раз. Нет обязательной длинной анкеты,
preselection или подразумеваемого согласия. Owner подтверждает конкретные сохранённые
revision и content_hash. Изменение содержимого требует нового подтверждения.
Workflow complete и ответ на отдельный вопрос не заменяют owner consent.

PM сначала получает exact owner confirmation receipt, затем завершает Workflow.
Технические роли до FINAL Workflow report публикуют и проверяют sealed role artifacts;
после accepted Workflow `complete=true` используют реальный Workflow receipt для typed
Tracker proposal/readback с явно названными разрешёнными stage/status.
Будущий receipt не включён в checks/evidence как условие предшествующего report:
это предотвращает цикл «сначала принеси результат ещё не выполненного handoff».
Дефекты Reviewer/Tester возвращают эту же задачу в Rework. Новый candidate снова
проходит Review и Testing. DevOps завершает задачу только с совпадающими доказательствами
artifact/deployment/health/acceptance; успешная сборка сама по себе недостаточна.

## Sealed Role Artifacts

Актуальный generator для шести технических ролей использует existing Tracker attachment
CLI под текущим delivery grant, без ordinary comments, human token или заимствования
owner/scheduler credentials:

```text
task-tracker attachment upload --issue <task-uuid> --file <role-artifact.json> --content-type application/json
task-tracker attachment list --issue <task-uuid>
task-tracker attachment download <attachment-uuid> --out <private-artifact-path>
```

Structured role evidence публикуется до FINAL Workflow report. В role-typed result
попадает actual server `artifact.receipt {reference,sha256}`, где reference имеет вид
`tracker-attachment:<UUID>`. Metadata `artifact.binding {assignment_id,execution_id,role}`,
task=root, size и SHA256 raw downloaded bytes сверяются с выданным текущим producer
или accepted predecessor context. Workflow terminal receipt/hash не заменяет содержимое
role artifact; локальный файл, comment или выдуманный Forge job/URL не являются receipt.
Upload требует current routing/run/assignment и живую lease; её holder — scheduler,
не агент. Unknown upload сверяется через list/download до exact-file replay, без
перезаписи sealed bytes, смены identity/fence или расширения permissions.

`proposal.idempotency_key` берётся **только** из supplied runtime guidance/template.
Агент не генерирует и не выводит ключ из session/run UUID. Existing
`sdlc result operation --task <task-uuid> --key <original-key>` использует это точное
supplied значение; unknown proposal acceptance сохраняет exact key/body до readback.
Missing key, 404/403, отсутствующая capability, stale binding или mismatch hash/readback
оставляют фазу незавершённой, не дают фиктивного completion. PM attachment capability
не добавлена; brainstorming Draft и exact confirmation-before-complete не меняются.

Исторический attachment packet менял только generator. Текущий source-context packet
регенерирует canonical catalog/manifest командой `python -m scripts.build_single_task_profile`
и проверяет `python -m scripts.build_single_task_profile --check`. Consumer pins/hashes
обновляет main отдельно после review. Legacy source/pins/history не переписываются;
regeneration не устанавливает каталог на стенд и не активирует runtime.

## Approved Source Context И Forge

После первого admitted Workflow step технические роли требуют exact Tracker
instance/project, task=root, approved repository URL/ID, full base SHA, allowed branch,
а при работе с существующим candidate — его exact SHA. Operator Forge `configId`
сопровождается отдельным exact Forge project UUID; это не новый API field или CLI flag.
Контекст вручную задаёт оператор в versioned SOUL/config либо immutable approved
requirements/source snapshot. Автоматического project resolver/supplier нет.
Existing `env_json`/`secret_ref` доставляет разрешённый доступ; отсутствие source mapping,
checkout или permission — operator infrastructure blocker, не business question/consent.
Нельзя угадывать project по имени, принимать default `main` или заимствовать identity.

Для первого требуемого Forge task workspace проверен source candidate
`5ea0ebcd6cdf013ed82079f515edb82b1bbe9812`, не установленный CLI или live runtime:

```text
cicd-cli pipeline run --project <forge-project-uuid> --git-ref <exact-source-sha> --idempotency-key <original-pipeline-key-uuid> --task-intent <task-intent.json>
cicd-cli pipeline task-workspace --project <forge-project-uuid> --id <actual-pipeline-uuid>
```

`project list` и `repository list` существуют; CLI `project get` отсутствует.
Старый packaging pin `4525694` не содержит `--task-intent`/`task-workspace`;
нужны отдельно квалифицированные repin и producer setup. Typed TaskWorkspaceIntent
использует actual Tracker binding/lease и supplied source coordinates, не caller-made
runner lease/attempt/workspace IDs. Forge выдаёт их сам. Preparation read-only в runner,
не writable Hermes checkout. Null readback — pending, blocked receipt — не deployment PASS.
Unknown trigger ACK сохраняет original key/body/args; без actual pipeline ID требуется
authorized reconciliation, а не второй pipeline, guessed ID или слепой retry.

Developer initial/rework sealed changes/checks содержат actual candidate SHA,
build pipeline ID, original operation keys и actual workspace receipt/lookup provenance.
**Собственный acceptedDeveloperResultId туда не входит:** Tracker создаёт его только
после native terminal и Fleet scheduler Complete. Developer не ждёт своего будущего
result/transition внутри active run и не выдумывает UUID. Reviewer после Complete берёт
actual Developer result ID из supplied `previous_result_id`, перечитывает accepted result,
сверяет SHA и sealed evidence, затем включает verified ID/coordinates/build refs в свой
sealed report. Tester передаёт их через accepted Reviewer report с повторной сверкой
Developer result; DevOps читает accepted Tester report и реальный Developer ID/SHA.
Это содержимое existing artifacts, не новые result DTO и не изменение sealed прошлого.

DevOps использует actual original workspace lookup и existing `workspace delivery` /
`workspace delivery-readback`, current DevOps taskFence отдельно от old build binding.
Owner target refs/published policy предоставляются оператором; protected target,
generic deployment create или unbound pipeline не заменяют guarded delivery.
Artifact/deployment/health/acceptance/rollback evidence остаётся обязательным,
как и ordinary tool approval. PM ordering, 7/7/8/24 и final transitions сохранены.
Нет stand adoption, публикации, нового controller/queue/MCP или native acceptance claim.

## Проверенный Tracker CLI И Пробелы

Ниже сохранена историческая проверка исходного loader `fb9dd53`. Для устанавливаемого
профиля она заменена [актуальными producer instructions](single-task-installation.md):
confirmation read требует `--revision`; result propose/operation доступны в parser,
но не означают stage completion. Live API registration остаётся pending parent.

Read-only проверен свежий Tracker checkout на
`9eac790a332d9501511d8cac2a3ef0f3ac7ddc23`: `backend/cli/src/commands.rs`,
`backend/cli/src/main.rs`, `docs/CLI.md`, `docs/SDLC_RESERVATION_V1.md`.
Это проверка исходников поддерживаемого parser/dispatch, не live вызов runtime.

Существуют команды `sdlc context/input/questions/requirements/intent --task <UUID>`,
`sdlc question publish --task <UUID> --from-file <file>`,
`sdlc revision publish --task <UUID> --from-file <file>`, а также
`sdlc analysis result submit --task <UUID> --from-file <file>` и
`sdlc analysis result operation --task <UUID> --key <key>` у `task-tracker`.
Для разрешённого доступа к comments/attachments существуют `comment list <issue-id>`
и `attachment list --issue <issue-id>`. У machine identity может не быть такого grant;
название команды не даёт разрешения. Строгие JSON payloads и authority fields
предоставляются существующим producer contract; этот пакет их не изобретает.

Непосредственные потребности интегратора:

- Owner confirmation exact revision/hash и точный receipt readback отсутствуют
  в CLI. PM не получает owner credentials. Context и Analysis intent помогают
  сверке, но не заменяют confirmation receipt.
- Analysis submit/operation существуют, однако producer принимает scheduler identity.
  Нужен разрешённый caller либо owner-mediated submit/readback подготовленного результата.
  Credentials scheduler нельзя передавать агенту. Нужна сверка реальной status vocabulary
  endpoint с целевыми Ready/InProgress/Completed, без выдуманного преобразования.
- Guarded terminal producer/readback для Architect, Developer, Reviewer, Tester,
  DevOps отсутствуют. Требуются same-task transitions, CAS/revision/fence, operation
  idempotency, frozen findings/Rework cycle и actual receipt. Команды намеренно не названы.
- Нужны mapping одного Tracker UUID на Workflow profession sessions, явный opt-in
  preset и согласованная выдача namespace/identity/input revisions. Без children,
  decomposition revision или barrier как обязательного условия назначения.
- Точные `cicd-cli` release/deployment/health/acceptance операции проверяются через
  установленный CLI help в разрешённой среде; этот пакет не придумывает их синтаксис.

Недостающая команда немедленно сообщается оператору, handoff остаётся незавершённым.
Generic patch, обычный issue transition, board move или status edit не используются.
Неизвестный ACK сверяется по исходному operation key до повторной записи. Сохранённый
старый receipt и уже изменённый context сообщаются отдельно, переход не проигрывается
повторно для возврата к прошлому состоянию.

## Проверки И Запрос Parent QA

Локально: targeted pytest `tests/test_single_task_catalog.py`, существующие CLI/catalog
regressions, ruff и diff check, без установки зависимостей и без Docker/PG.

Source-context packet от `3e0c4d5`: 155 targeted tests PASS, включая 19 новых
`tests/test_single_task_source_context_instructions.py` и actual SQLite/TestClient
PM producer/terminal fixture readbacks с synthetic external authority/runtime inputs.
Canonical generator `--check`, targeted Ruff и diff check PASS. Единственное warning —
existing Starlette/anyio deprecation. PG/native/image/live проверки не выполнялись;
новые catalog/manifest hashes требуют отдельного main integration и квалификации.

В едином parent QA после подключения owner contracts проверить:

- Каждый из восьми режимов получает первый Workflow step до Tracker/CI/CD действий;
  missing/rejected admission не допускает продолжения.
- PM: несколько brainstorming итераций, свободный ответ, конфликт требований,
  изменение revision после consent; handoff только после exact confirmation receipt.
- Полный путь одной задачи Draft → Backlog → Analysis → Architecture → Development
  → Review → Testing → Deployment; UUID сохраняется, children и barriers отсутствуют.
- Defects из Review и Testing: Rework → Review → Testing для нового candidate;
  stale findings/evidence и replay не пропускают стадии.
- Unknown ACK/restart: original operation readback, без второго эффекта, подмены
  identity, generic patch или фиктивного receipt.
- Deployment Completed только при совпадении artifact/deployment/health/acceptance;
  failed/missing/stale evidence оставляет handoff незавершённым.
- PG persistence, coverage ≥94%, mypy, общий quality gate и legacy history/pins
  проверяет parent на одном QA. Этот source-only пакет не объявляет E2E завершённым.
