# Человеческая Identity И Права Workflow

Текущий source-контракт описан ниже; установленный образ и приёмка учитываются
отдельно в [диагнозе](ADVISOR_DIAGNOSIS_20261101.md).
Профессии и роли исполнителей не являются человеческими ролями.

## Вход И Административные Операции

В platform SSO middleware проверяет credential через настроенный Auth и получает
его текущую identity. Нужны активная учётная запись, canonical role user/admin и
действительный срок credential. Для JWT issuer/subject/expiry связываются с
проверенной identity; PAT дополнительно требует точный scope
`project-workflow:read` или `project-workflow:write` по операции.
Service-account credentials не становятся людьми и не получают административные
permissions.

Отдельный `application_access` grant или список приложений для human admission
Workflow не требуется: отсутствие/пустота этого списка не является отказом.
`HumanAccess` содержит identity, роль и исходный срок, не полномочия других
продуктов. Недоступный Auth или просроченный credential закрывают platform-вход,
а не переключают его в standalone. Standalone — отдельный явно выбранный
loopback-only режим; см. [архитектуру](architecture.md#поддерживаемые-режимы).

Обычный пользователь читает процессы и выполняет разрешённые задания.
Изменения профессий, workflow, фаз и инструкций требуют серверной admin dependency;
страницы и scripts редакторов используют ту же текущую authority через
`can_administer`. CLI history/step и личная CLI-справка не становятся
административными операциями. Скрытые UI-кнопки не заменяют серверную проверку.

## Проектный Scope И Исходный Срок

Identity/role не отменяют project ownership и resource permissions. При включённой
политике пространств требуется отдельный подтверждённый project scope, включая
writable admission для записи. Архив, чужой проект и запрет пространства не
обходятся глобальной ролью или отсутствием app grants. Конфигурация по-прежнему
требует admin; техническое назначение не превращается в human authority.

Неизменяемый project scope ограничен исходным human deadline, сроком credential
и project proof. Display window действует и без space policy по исходному
identity clock. При совместном применении берётся меньший срок; кеш и повторная
проверка в том же запросе его не продлевают. Display revision учитывает
issuer/subject/role и действующий project scope, не список приложений.
Изменение только срока не уничтожает неизменённый черновик.

Отдельный request clock ограничивает ORM-чтение, flush и commit независимо от
space policy. Он содержит только исходный срок и не выдаёт полномочий.
Миграция0017 устанавливает row/deferred COMMIT guards на защищённых таблицах.
Настройка принадлежит транзакции; следующий native запрос очищает её и применяет
свои проверки. SQLite используется только в изолированных тестах.

## Машинные Контракты И Границы Проверки

Namespace/Base reader сохраняет exact registered subject, scopes и запрет
human role на machine paths. Отдельные proofs других операций, включая удаление
identity, не являются human app-grant admission и не удаляются этим контрактом.

SSO, role/admin, PAT scopes, credential expiry, project admission и PostgreSQL
COMMIT guards проверяются соответствующими регрессиями. Native PostgreSQL fixture
доказывает откат истёкшей записи и отдельно разрешённую native запись, не внешние
эффекты или весь runtime. Source/unit/PG checks не доказывают установленный cohort,
живое задание или Docker/Kubernetes-приёмку; их результаты фиксируются отдельно.
