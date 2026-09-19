# Архитектура project-workflow

`project-workflow` - внутренняя loopback/private утилита для пофазного ведения
задач. Она не владеет human identity, browser sessions или personal tokens:
ими управляет Central Auth. Приложение проверяет их через server-side OIDC и
introspection, а также сохраняет отдельный private runtime bridge для машинных
исполнителей.

## Границы компонентов

- **CLI** предоставляет только `step` и `history`. Пользовательские команды для
  отдельных неймспейсов создаются wrapper-скриптами и внутри вызывают тот же
  `project-workflow step/history`. В token mode команды используют защищённый
  HTTP API через общий `sdlc-cli-core`; direct DB mode остаётся локальным
  legacy/dev вариантом.
- **Browser SSO** использует Authorization Code + PKCE, проверяет signature,
  issuer, audience, expiry, state и nonce, хранит access token только в
  зашифрованной HttpOnly cookie и проверяет активность central session на
  защищённых запросах. Недоступность Central Auth даёт `503` без local login.
- **Web UI** владеет CRUD для workflow, фаз, неймспейсов и агентов через
  FastAPI/Jinja. Задачи в UI доступны только для наблюдения: список, состояние,
  phase/audit history, checks/evidence и verdict. Создание и переходы задач
  выполняются только CLI `step`. Выбор в верхней панели полностью задаёт
  связанный workflow, задачи, название, простую иконку, цвет темы,
  и CLI-команду.
- **Внешний runtime bridge** обслуживает изолированные контейнеры исполнителей
  через `POST /internal/runtime/step` и `GET /internal/runtime/history`. Он
  аутентифицируется role token из `PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON`, не
  доступен как browser UI API и должен публиковаться только во внутреннюю сеть
  или на host loopback.
- **SupervisorEngine** маршрутизирует задачу, строит phase contract, вызывает
  обязательный OpenAI-compatible evaluator и сохраняет результат атомарно.
- **PostgreSQL** - единственный runtime data store. SQLite допустим только в
  изолированных тестах с явным test DSN.
- **Внешний исполнитель** находится за границей приложения. Здесь хранится
  только уникальное имя агента, nullable имя профиля запуска и список
  рекомендованных skills; секреты и конфигурация профиля остаются во внешнем
  исполнителе.

Физическая таблица для неймспейсов пока называется `projects`. Это внутренний
слой хранения, оставленный ради безопасной миграции. Публичный пользовательский
слой работает через `/namespaces` и `/api/namespaces`.

## State And Audit

`tasks` хранит текущий snapshot задачи: статус, выбранный неймспейс, workflow и
текущую фазу. `task_key` уникален внутри одного неймспейса, а не глобально по базе. Это
позволяет вести одну внешнюю задачу, например `RUN-42`, через несколько
неймспейсов: для разработки, проверки, релиза или любого другого сценария.

Ключ задачи валидируется как внешний идентификатор формата `TASK-123`, но не
маршрутизирует неймспейс сам по себе. Когда одна и та же внешняя задача ведётся в
нескольких неймспейсах, нужный workflow выбирается явно: wrapper-командой,
query-параметром или сохранённым UI selector.

`task_phase_events` является append-only журналом переходов фаз.
`task_step_history` хранит каждую пару "отчёт исполнителя - verdict
Supervisor" вместе со снимком контракта и evaluator response.

Удаление задач намеренно не поддерживается публичным UI/API/repository flow:
история должна оставаться проверяемой. Связи task/phase/history закреплены
составными FK, чтобы записи audit не могли относиться к чужому workflow или
задаче.

## Supervisor Contract

Supervisor никогда не полагается на локальный fallback evaluator. Если provider
недоступен, ответ некорректен или контракт изменился во время оценки, задача
остаётся на текущей фазе и получает retryable `BLOCKED`.

Replay допускается только для той же задачи, фазы, нормализованного отчёта и
того же contract fingerprint. Fingerprint включает prompt version, phase graph,
evaluation items, transition routes и накопленное покрытие. DB lock не
удерживается во время provider call; перед commit состояние задачи и каталог
перечитываются.

Когда одна внешняя задача существует через несколько неймспейсов, исполнитель
использует configured CLI-команду нужного неймспейса, например
`workflow-qa step --task RUN-42`. Wrapper выставляет
`PROJECT_WORKFLOW_NAMESPACE_ID=<id>`, поэтому контракт Supervisor показывает
именно configured command без дополнительных selector-флагов.

## Runtime Scope

Текущий scope зафиксирован как внутренняя утилита:

- стандартный Compose публикует PostgreSQL и API только на `127.0.0.1`;
- `/health` проверяет DB connectivity, schema readiness и migration head;
- request logging и readiness считаются достаточными для локальной эксплуатации;
- security middleware, rate limits, CSP, hosted CI и metrics не добавляются,
  пока приложение не становится внешним многопользовательским сервисом.
