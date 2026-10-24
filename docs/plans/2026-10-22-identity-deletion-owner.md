# Workflow: владелец жизненного цикла identity

Кандидат интегрирован с `origin/master`:
`51664f37bf455bbebd016cf4470f8614dc94dfa9`.
SDK закреплён на опубликованном кандидате
`2bb386503eeb009e2238160e88970eae0fab2824`; независимый UI pin сохранён.
Исходники не означают установку runtime или завершённую квалификацию.

## Inventory и владение

Сохраняются два источника ссылок на identity Auth:

| Источник | Ссылка | Запись |
|---|---|---|
| `resource_execution_contexts` | `created_by_subject` и явно привязанный issuer установки | аутентифицированная команда execution context, repository и SQL ports |
| `pm_namespace_ownership` | `authority_issuer` и `provisioner_subject` | зарегистрированный provisioner namespace, replay и история |

Context сохраняет автора после завершения исполнения. Provisioning namespace
сохраняет инициатора независимо от того, человек это или служебная учётная запись.
Проверка только активных объектов или текущей директории Auth не заменяет историю.

Context `request` и `verified_projection` содержат resource IDs и workflow catalog
IDs. `PMExecution.identity_json` и снимки run/operation/checkpoint содержат task,
project, Fleet agent/run/binding IDs и role keys. Эти поля не являются identity
человека. История задач и фаз сохраняет результаты исполнения, назначения и роли
профессий без отдельного человеческого actor. Legacy названия профессий и агентов,
описания CLI actor, Git author, произвольные отчёты и инструкции не преобразуются
в UUID пользователя по внешнему виду. Локальных таблиц users/memberships/sessions
нет; browser SSO cookie не является durable ссылкой продукта. Историческое
авторство не выдумывается и директория пользователей не создаётся.

## Аддитивная миграция и общий guard

Выпущенная `0017_human_application_clock` остаётся неизменной. Новая миграция
`0018_identity_deletion_owner` следует за ней; второй Alembic head не создаётся.
Upgrade admission сохраняет все прежние ограничения и допускает оба выпущенных
предшественника: `0016_human_project_commit_guard` и `0017_human_application_clock`.

PostgreSQL triggers покрывают все прямые INSERT/UPDATE/DELETE обоих источников
перед изменением бизнес-строк. Writers удерживают общий транзакционный advisory
lock `714402216003` в shared-режиме и epoch `FOR SHARE`. Эффекты owner берут
exclusive lock и обновляют обязательный singleton epoch. Предыдущие writers
завершаются перед freeze; старый repeatable-read snapshot получает `40001`.
Отсутствующий epoch закрывает запись. Inventory читает MVCC без бизнес-строк
`FOR UPDATE`; общий порядок блокировок не меняется. Обычные API, CLI и repository
writers проходят те же DB guards. SQLite используется только для schema/unit:
эффекты жизненного цикла на нём возвращают `503`.

Каждая команда, включая `check`, replay и `release` без существующего freeze,
передаёт исходный типизированный `Authority` до Core-транзакции. До блокировок
считывается DB clock anchor; только после ответа вычисляется остаток исходных
wall/monotonic часов. Конечный SQL deadline ограничен также исходным абсолютным
expiry. Нового TTL после ожидания не появляется.

`identity_owner_command_authorizations` содержит только UUID и expiry. Core
вставляет и удаляет свежую строку в той же транзакции: PostgreSQL сохраняет
отложенное AFTER INSERT событие с NEW до COMMIT. Immediate и deferred guards
возвращают `42501` при истечении. Строки не накапливаются и не содержат PII.
SQL guard откатывает всю команду, если разрешение истекло внутри COMMIT, после
последней проверки Python. На долговечном fence deadline не сохраняется;
последующая команда с новым разрешением может обновить его.

`PROJECT_WORKFLOW_IDENTITY_LEGACY_ISSUER` — явное утверждение оператора об issuer
старых context subjects. Значение должно точно совпадать с `AUTH_ISSUER`.
Первая подтверждённая транзакция сохраняет неизменяемую привязку. Отсутствующая,
изменённая или чужая привязка означает unknown/conflict; email lookup и форма UUID
не подставляют issuer. Бизнес-данные и история сохраняются.

`check` предварителен. `freeze` атомарно сохраняет полный запрос и неизменяемую
квитанцию, включая ненулевое число ссылок. Replay возвращает сохранённый результат.
`release` сохраняет отмену даже до freeze; запоздалый freeze конфликтует. Чужая
операция не снимает fence. TTL нет. Auth — доверенный координатор, который запрещает
release завершённого удаления; owner не заявляет независимую проверку tombstone Auth.

## Закрытый транспорт и человеческое администрирование

`POST /api/internal/v1/user-deletions/{operation_id}/{check|freeze|release}`
проверяет строгий JSON Base v1, совпадение path/body и тело не более 16 KiB.
Все ответы имеют `no-store`, включая ошибки body и неподдерживаемые методы.
Обходится только человеческий SSO: обязательны свежий introspection PAT,
`subject_role=service_account`, регистрация в
`PROJECT_WORKFLOW_IDENTITY_DELETION_COORDINATOR_SUBJECTS`, точный scope
`project-workflow:identity-lifecycle` и точный issuer. Пустая регистрация запрещает
доступ. Human admin/PAT, общий write scope и service-account JWT не заменяют
полномочия координатора. Namespace-auth контракт сохранён.

Оба канонических поля introspection, `role` и `subject_role`, обязательны и должны
совпадать. Отсутствующие, некорректные или противоречивые поля дают `503`.
Допустимый human PAT получает `403`, включая настоящий ответ с метаданными
application access. Проверка этих метаданных использует существующий чистый
валидатор, без дополнительного Auth I/O или создания прав координатора.
Неизвестные поля по-прежнему запрещены.

Регистрация owner route не убирает `require_administrator` у страниц и команд
конфигурации. Канонические человеческие роли, доступ к приложениям и исходные
часы допуска из актуального master остаются действующими.

Auth HTTP не использует redirects/proxies/compression: тело ограничено 16 KiB,
бюджет — 5 секунд. Исходные observed/expires сохраняются с monotonic deadline
не более 60 секунд; весь owner I/O ограничен 9 секундами. Транзакционные
`lock_timeout` и `statement_timeout` — 8 секунд. Proof и общий deadline
перепроверяются перед commit и ответом. Timeout/unknown возвращают статический
`503`, а не ноль. Thread после timeout обязан повторно проверить исходный deadline.

Обязательный legacy subject с пустым или пробельным значением — unknown:
`check`/`freeze` возвращают `503`, новые неразрешённые записи после fence запрещены.
Исторический provenance разрешается оператором явно. Issuer сохраняет точное
написание, включая завершающий slash и path. Допустим HTTP(S) без userinfo,
query, fragment или управляющих символов. Нормализуется только транспортный origin.

## Проверки и открытые gates

Scoped unit проверяют DTO, управляемый Auth wire role/scope/PAT/expiry/redirect,
исходный lifetime, настоящий FastAPI route/no-store/body и отказ SQLite.
Отдельный тест регистрации сохраняет административные dependencies конфигурации.
Эти fixtures не заменяют настоящий Auth.

Настоящие PostgreSQL тесты проверяют заполненный upgrade, два источника, replay,
отмену до freeze, чужой запрос, неизменяемый issuer, обычные записи после fence,
drain writers, RR `40001`, отсутствующий epoch и настоящий lock timeout.
Заполненный upgrade параметризован по версиям 0016 и 0017: после 0018 остаются
5000 context rows и все 34 released application-clock triggers; для 0017 также
сравниваются точные определения trigger/function до и после owner migration.
SQLite regression сохраняет те же исторические строки для обоих предшественников.

Исторический PG snapshot `5dd` прошёл 5 случаев и выявил 3 ошибки: отсутствующий
0016 в upgrade allowlist и попытку теста удалить immutable namespace history.
Исправления сохраняют ограничения unversioned/foreign schema; неизвестная история
и запрет новой записи проверяются раздельно на свежих базах. Исторические результаты
не выдаются за проверку текущей интеграции. Исторический расширенный owner PG
набор содержал 16 случаев; текущий отдельный owner PG набор содержит 19 случаев.
Он не заменяет полный repository PostgreSQL gate
`tests/test_postgres_integration.py`: его 115 случаев имеют отдельное evidence.
Три COMMIT barrier проверки для
`check`/`freeze`/`release` сначала подтверждают вход в настоящий deferred trigger,
удерживают транзакцию до истечения исходного proof, затем проверяют `42501`,
полный rollback journal/binding/epoch и успешную свежую команду. Пороговые таймауты
приложения и ранее выпущенные часы доступа не расширяются.

### Gates исходников и активации

До merge исходников обязательны pinned Python/constraints lint/mypy, полный pytest
с coverage не ниже 94%, строгий ResourceWarning gate и реальные PostgreSQL/EXPLAIN.
Отдельно обязательны запуск настоящего сервера и HTTP readiness в собственном
Compose-проекте, проверка private check/freeze/release с настоящим Auth coordinator,
потерянного ACK, restart и гонок отмены/завершения. Статус на 2026-10-24: приняты изолированные source-компоненты и составное
доказательство этих gates. Исходники готовы к слиянию; активация не разрешена:

- Строгий native-компонент: 3446 PASS, 5 optional private-Base SKIP,
  coverage 94,07262905162065%, Ruff/mypy и оба warning-as-error фильтра PASS.
  Whole/outer receipts `bfcaba01…`/`0560da8d…` остаются `complete=false` из-за
  concurrent/unknown изменения permanent-state guard. Успешный изолированный
  source-компонент принят на неизменных inputs отдельно; эти результаты сохранены.
- Настоящие PostgreSQL owner19 и repository115 — разные прогоны, не общий count.
  Owner receipt `20ee7c40…` включает durable replay/release, cancel-before-freeze,
  writer/freeze wait, RR40001, COMMIT rollback и populated upgrade/EXPLAIN;
  repository receipt `3a8f9e76…` сохраняет полный обязательный repository gate.
- Genuine Auth PAT и настоящий Workflow HTTP: receipt `0a526283…` прошёл 9 checks,
  включая полную перехваченную freeze ACK, фактическую потерю ответа клиенту
  (curl52), точный replay до/после restart, release200 и late-freeze409.
  Cleanup/source/process/inputs и outer four-project guard PASS.
- Auth actual PG20 в принятом scoped invocation `a72c21e6…`/gate `54859bfe…`
  проверяет final-ACK/cancel с настоящим DB lock waiter, противоположный порядок
  cancel-before-last-freeze, восстановление только после всех release ACKs,
  worker crash/ACK recovery и один final effect. Это реальные Auth транзакции
  с controlled TCP peers восьми owners, а не приёмка восьми продуктов.
  Deletion/command code и SQL Auth C9 совпадают с этими проверенными inputs.

Отдельного одновременного Workflow freeze/release на двух DB connections
не запускали: owner19 проверяет общий exclusive transaction lock и оба durable
порядка; concurrent cancel/complete проверен на стороне Auth. Это принятое
составное source-доказательство, не новый full-cohort прогон. В Workflow HTTP
fixture Auth inventory отсутствует и `global_cancel_finish_qualified=false`;
это ограничение fixture не отменяет отдельные actual Auth race results.

Полная совместная приёмка восьми owners, deployment qualification Docker/Compose
и Kubernetes, включение функции и rollout относятся к отдельному этапу активации.
Эти gates остаются **OPEN**; их отделение от merge исходников не означает PASS
или завершение общей цели. Слияние кода с выключенной по умолчанию функцией
не разрешает её включение или установку в действующий runtime.

Все контейнерные проверки используют только собственный временный
ComposeHelper v2 проект с сохранением evidence и удалением собственных ресурсов.
Этот PR не устанавливает runtime.
