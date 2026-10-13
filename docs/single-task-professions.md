# Single-Task Professions V1

Opt-in preset `single-task-v1` принадлежит Workflow. Он содержит реальные инструкции,
checks и evidence семи профессий для одной Tracker задачи: восемь режимов,
24 последовательные фазы. Исходный baseline Workflow:
`6a50985841daa22aa6513868548a5d0b897fac44`.

Точка подключения для интегратора:

```python
from project_workflow.infrastructure.single_task_catalog import load_single_task_professions

professions = load_single_task_professions()
```

Функция возвращает независимые определения профессий с существующими workflow keys,
mode keys, phase codes, namespace/profile и именами skills. Каждый режим проверяется
существующим `ManagedMode`, фазы совместимы с существующим Supervisor. Это подготовка
default инструкций для выбранного preset, а не установка в runtime. Функция ничего
не пишет в БД, не запускает агентов и не модифицирует Hermes.

## Совместимая Активация

Минимальное предложение интегратору: отдельный явный выбор `single-task-v1` для новых
назначений одной задачи. Не переиспользовать номер pinned Base catalog как номер
этого preset. Текущий `ManagedCatalog` требует 11 режимов и прежнюю terminal policy,
поэтому передавать ему эти восемь режимов как старый catalog запрещено. Общие wire
DTO, schema, API registrations, migrations и bootstrap этим пакетом не меняются.

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

Последняя инструкция каждого режима сначала требует accepted Workflow `complete=true`,
затем называет разрешённые stage/status и требует реальный Tracker receipt/readback.
Будущий receipt не включён в checks/evidence как условие предшествующего report:
это предотвращает цикл «сначала принеси результат ещё не выполненного handoff».
Дефекты Reviewer/Tester возвращают эту же задачу в Rework. Новый candidate снова
проходит Review и Testing. DevOps завершает задачу только с совпадающими доказательствами
artifact/deployment/health/acceptance; успешная сборка сама по себе недостаточна.

## Проверенный Tracker CLI И Пробелы

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
