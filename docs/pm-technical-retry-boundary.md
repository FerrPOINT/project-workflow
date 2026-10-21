# PM: технический retry до принятого отчёта

Source review: `e2abddf4d1833a6758032621110d978a955b1e51`. Это предложение
для согласования C/Main, не реализованный retry API и не installed/live proof.
Workflow production, DTO, схема и generated catalog этим пакетом не изменяются.

Уточнение Main после исходного review: canonical Tracker assignment/execution и
owner_version сохраняются; создаётся linked Fleet bootstrap attempt. Реализация
зарегистрированного reader/internal метода описана в [pm-bootstrap-recovery.md](pm-bootstrap-recovery.md).

## Конкретный пробел

- `application/task.py:454` запрещает replacement enrolled PM даже при новом
  attempt. Generic `rebind_runtime_assignment` запрещает single-task execution.
- `application/pm_execution.py:262` допускает следующий local cursor только после
  `task.status=done`, проверенного Workflow terminal receipt и trusted native
  terminal. Native terminal до завершения Workflow этому не соответствует.
- `resume` требует `waiting`, сохранённый checkpoint и действительный typed input;
  `rebind` требует `resume_pending` и тот же reserved checkpoint. Технический сбой
  не является feedback/answer/confirmation. Фиктивный checkpoint недопустим.
- `infrastructure/db/models.py:55` сохраняет один PMExecution на local Workflow
  task. Перепривязка нового execution к прежней строке нарушает существующую модель.

## Минимальная граница для C/Main

Уточнённый scope Main: **PMExecution ещё отсутствует**, а не технический retry уже
enrolled PM. Для этого достаточно следующего immutable assignment на ТОМ ЖЕ local
Workflow task; уникальность `PMExecution.task_id` не требует нового cursor, пока
enrollment не состоялся. Canonical Tracker task=root, namespace owner/project,
профессия, mode Draft и business cycle остаются теми же. Новый attempt/execution и
assignment выдаёт доверенный coordinator, не агент.

Узкая ветка в existing `assign_runtime_task` перед отказом active-assignment должна
под existing namespace/task lock:

1. Сверить exact predecessor assignment/revision/agent, finalized bind key/hash,
   original native run/session/binding, initial phase/status и frozen input refs.
   Сверить authoritative Tracker/Fleet predecessor fence и coordinator successor.
   Original key/body replay возвращает прежний результат; иной concurrent successor
   или устаревший predecessor отклоняются CAS.
2. Потребовать **отсутствие PMExecution** и любых принятых step/report/progress
   записей. Не принимать caller-controlled `no_step`. Попытка PM step до enrollment
   уже запрещена `supervisor_binding`; после enrollment эта ветка всегда закрыта.
   Нет PMExecution — нет PMRun/checkpoint/resume; не создавать их искусственно.
3. Если исходный bind/step/enrollment имел unknown ACK, сначала выполнить existing
   authorized original-key readback/reconciliation. Пустой список, caller boolean
   или timeout не являются доказательством отрицательного эффекта. Native terminal
   `completed|failed|cancelled|stopped` должен прийти из проверяемого owner readback
   с exact original identity/fence; unknown/running/foreign proof запрещены.
4. Создать новый assignment с next attempt и next local revision, новым coordinator
   execution context, сохранив старую assignment/binding/payload/key/hash/history
   байт-в-байт. Не маркировать прежний task `done`, не синтезировать Workflow
   terminal receipt/checkpoint и не повышать business cycle. Initial phase не меняется.
5. Выполнить обычный `bind_runtime_assignment` для нового unbound assignment, затем
   PM bind. Fresh trusted proof нового native run обязан быть **running**. Не
   сбрасывать прежние bind-поля в NULL и не добавлять skip-running/fallback.

У already-enrolled PM `runtime_api.py:575–604` возвращает `report=null` инструкции
без durable step-history. Поэтому пустой history у enrolled PM НЕ доказывает
before-first-read. В новом guard обязательное отсутствие enrollment устраняет эту
неоднозначность; ветку нельзя расширять до merely zero reports.

Shared predecessor wire fields и источник их readback согласовать с C/Main до
реализации. Если Tracker assignment revision и Workflow sink revision расходятся,
их нужно связать явно, не подставлять другую revision. Нельзя использовать
`PMReviewAdmissionContext` с выдуманным critical-review blocker для technical retry.

## Семь профессий: installable source

Проверяется generated `references/single_task_catalog_v1.json`, загружаемый
`infrastructure/db/single_task_catalog.py`, а не legacy CLI catalog и не старый
proposal из `infrastructure/single_task_catalog.py` без delivery overlay.

| Профессия / mode | Нормальный business результат |
|---|---|
| PM / draft | Exact owner confirmation readback → final Workflow report → native terminal; Backlog/Ready, затем Analysis/Ready через Tracker/Fleet |
| Analyst / analysis | Architecture / Ready |
| Architect / decomposition | Development / Ready, без children |
| Developer / initial и rework | Review / Ready, затем свежие Review и Testing |
| Reviewer / delivery | Testing / Ready при approved, иначе Rework / Ready до лимита |
| Tester / delivery | Deployment / Ready при passed, иначе Rework / Ready до лимита |
| DevOps / delivery | Deployment / Completed |

Для всех modes первое рабочее действие — существующий scoped `project-workflow
--json step` без report, с exact key/request/token. Для шести technical roles:
sealed artifacts → accepted Workflow receipt → `task-tracker sdlc result propose`
→ original-key operation readback → завершение native run → Fleet CompleteCAS.
Нельзя ждать собственной будущей transition, удерживая run alive. На третьем
rework-limit Reviewer/Tester сохраняют фактические Review/Testing + Ready + Terminal,
а не создают четвёртый cycle. PM не использует technical result proposal и не
подменяет человеческое подтверждение. Эти first/final инструкции дефекта,
требующего переписывания каталога, не показали; installed CLI/runtime здесь не
опрашивались.

## Regression scope

В существующем `tests/test_pm_critical_review.py` добавлен параметризованный test
для четырёх native terminal statuses с/без first read. Проверяет real isolated
SQLite/TestClient: повторное enrollment отклонено, terminal receipt отсутствует,
все task/assignment/step/event/PM execution/run/operation строки сохранены.
Это доказательство существующей fail-closed границы, НЕ positive retry acceptance.

Отдельный test проверяет текущий no-enrollment случай: exact original runtime-bind
replay разрешён, замена finalized run запрещена, caller `no_step` отклонён схемой,
PM first-step до enrollment запрещён, старые assignment bytes и initial cursor
сохранены. Этот пакет не ослабляет guard и не реализует coordinator retry.

## Выполненные host checks

- Новые boundary regressions: 8 parameterized cases PASS (39.78s), no-enrollment
  case PASS (4.16s). SQLite/TestClient, synthetic native observations; не live proof.
- Existing `test_single_task_instructions`, `test_single_task_source_context_instructions`,
  `test_single_task_artifact_instructions`, `test_cli_platform`: 155 PASS (49.55s).
- `python -m scripts.build_single_task_profile --check`: PASS. Catalog SHA256
  `86e6c983b7aa6a2c99da11d1d4b1f1b4563ff913262236903a19bc86bdec2d67`,
  manifest `652a38c0f7bdb48a569aa3fcd5c2e81e153db6e22b5201cfb6ce15c988dd57f3`.
- Scope: source/test-only, без Hermes/live API/PG/Docker/build/install. Полный
  repository quality gate и positive technical-retry acceptance не выполнялись.

## Повторный profession audit 2026-10-21

Read-only audit исходников на docs-only HEAD `57785668ba3aab93eee5db073c531beabb699a9a`;
production/tests/scripts/catalog byte-identical к `a7b805d4`. Это отдельный source
scope, не installed/live qualification. Проверяется существующий generated
installable catalog: **7 namespaces, 7 workflows, 8 modes, 24 phases**.

- Все восемь modes начинают с реального scoped CLI `project-workflow --json step`
  без report, с supplied original key/request/token; не narrative ACK и не local DB.
- PM draft сохраняет brainstorming малыми итерациями, pre-document feedback
  null/null, затем full saved requirements и exact owner confirmation перед final
  report. Нет fake revision/checkpoint, self-confirmation или лишнего PM cycle.
- Analyst/Architect сохраняют task=root и не создают children, decomposition
  barriers или integration/integration_rework modes.
- Developer initial/rework, Reviewer, Tester и DevOps сохраняют конкретные role
  artifacts, provenance и собственные verdicts. Rework повторяет Review и Testing;
  третье отклонение сохраняет реальный stage/Ready/Terminal без четвёртого cycle.
- Все шесть technical roles сначала получают usable Workflow complete receipt,
  затем публикуют Tracker result proposal и делают original-key operation readback,
  после чего завершают native run. Собственный CompleteCAS/stage transition внутри
  live agent не ожидается; это последующий Fleet/operator readback.
- Critical business hold остаётся отдельной unfinished веткой: не normal result,
  не fake completion и не автоматическое PM/scheduler действие агента.

Новых доказанных instruction defects в этом bounded scope не обнаружено;
production/instruction/catalog bytes не изменялись и новые modes не добавлялись.

Actual host regressions на этом неизменном source:

- `test_single_task_instructions.py`, `test_single_task_catalog.py`,
  `test_single_task_source_context_instructions.py`,
  `test_single_task_artifact_instructions.py`: **133 PASS / 49.00s**.
- Existing `test_cli_platform.py`: original snapshot/key/scoped credential
  forwarding (2), incomplete/mismatched flags reject before HTTP/DB (6), timeout
  unknown without retry/DB fallback (1): **9 PASS / 8.44s**, mocked HTTP transport.
- `python -m scripts.build_single_task_profile --check`: PASS; catalog
  `86e6c983b7aa6a2c99da11d1d4b1f1b4563ff913262236903a19bc86bdec2d67`, manifest
  `652a38c0f7bdb48a569aa3fcd5c2e81e153db6e22b5201cfb6ce15c988dd57f3`.

Эти scopes не суммируются с overlapping прежними 66/155 host cases или с actual
PG6. Установленные CLI/профессии и реальные модели здесь не вызывались. Отдельный
actual bootstrap PG6/API61 receipt на a7 находится в
[pm-bootstrap-recovery.md](pm-bootstrap-recovery.md); production release/install
или seven-role business acceptance этим audit не заявлены.
