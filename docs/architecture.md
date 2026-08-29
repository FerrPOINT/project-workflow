# Архитектура project-workflow

`project-workflow` - внутренняя loopback/private утилита для пофазного ведения
задач. Она не является внешним production-сервисом и не владеет
аутентификацией, CI/CD, метриками или публичной публикацией портов.

## Границы компонентов

- **CLI** предоставляет только `step` и `history`. `step` получает текущий
  контракт фазы или отправляет отчёт исполнителя в Supervisor. `history`
  читает сохранённые записи `task_step_history`.
- **Web UI** владеет CRUD для workflow, фаз, контуров, агентов и задач через
  FastAPI/Jinja. Workflow хранит reusable флоу фаз, а workflow context хранит
  операторское название, простую иконку и HEX-цвет темы; UI использует те же
  application services и UoW, что и CLI.
- **SupervisorEngine** маршрутизирует задачу, строит phase contract, вызывает
  обязательный OpenAI-compatible evaluator и сохраняет результат атомарно.
- **PostgreSQL** - единственный runtime data store. SQLite допустим только в
  изолированных тестах с явным test DSN.
- **Executor/Hermes** находится за границей приложения. Здесь хранится только
  уникальное имя агента, nullable имя Hermes-профиля и список рекомендованных
  skills; секреты и конфигурация профиля остаются во внешнем исполнителе.

## State And Audit

`tasks` хранит текущий snapshot задачи: статус, workflow context, workflow и
текущую фазу. `task_key` уникален внутри одного workflow context, а не глобально
по базе. Это позволяет вести одну внешнюю задачу, например `RUN-42`, в
нескольких контурах: development, testing, release и т.п. Если ключ
встречается в нескольких контурах, CLI/UI должны получать явный selector
context.

Контурные `key_prefixes` также проверяются внутри workflow. Один и тот же
префикс можно использовать в разных workflow, но внутри одного workflow
пересечение префиксов остаётся конфликтом.

`task_phase_events` является append-only журналом переходов фаз.
`task_step_history` хранит каждую пару "отчёт исполнителя - verdict
Supervisor" вместе со снимком контракта и evaluator response.

Удаление задач намеренно не поддерживается публичным UI/API/repository flow:
история должна оставаться проверяемой. Связи context/task/phase/history
закреплены составными FK, чтобы записи audit не могли относиться к чужому
workflow или задаче.

## Supervisor Contract

Supervisor никогда не полагается на локальный fallback evaluator. Если provider
недоступен, ответ некорректен или контракт изменился во время оценки, задача
остаётся на текущей фазе и получает retryable `BLOCKED`.

Replay допускается только для той же задачи, фазы, нормализованного отчёта и
того же contract fingerprint. Fingerprint включает prompt version, phase graph,
evaluation items, transition routes и накопленное покрытие. DB lock не
удерживается во время provider call; перед commit состояние задачи и каталог
перечитываются.

Когда `task_key` не уникален между workflow contexts, `step/history` запускаются
с `--context <id-code-or-name>`. Supervisor добавляет этот selector в
`cli_actor`, чтобы исполнитель отправлял отчёт в тот же контур, по
которому получил контракт.

## Runtime Scope

Текущий scope зафиксирован как внутренняя утилита:

- стандартный Compose публикует PostgreSQL и API только на `127.0.0.1`;
- `/health` проверяет DB connectivity, schema readiness и migration head;
- request logging и readiness считаются достаточными для локальной эксплуатации;
- security middleware, rate limits, CSP, hosted CI и metrics не добавляются,
  пока приложение не становится внешним многопользовательским сервисом.
