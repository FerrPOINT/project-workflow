# AGENTS.md

## Правила репозитория

1. После завершения задачи нельзя оставлять готовую работу в незакоммиченном состоянии.
   - Сначала прогнать релевантные проверки.
   - Для UI-изменений обязательно сделать браузерную проверку и скриншот.
   - Затем сразу сделать git commit по выполненной задаче.

2. Не считать задачу завершённой, если рабочее дерево осталось dirty по её изменениям.

3. Merge и deploy запрещены без явной команды пользователя.

## Обязательные проверки

После любого изменения SQLAlchemy-слоя, application services, состояния UI или
Supervisor Engine перед commit выполнить следующие проверки:

1. **Tests**
   ```bash
   pytest -q --timeout=60
   ```
   Ожидается 0 падений и 0 ошибок. PostgreSQL integration tests здесь намеренно
   исключены и запускаются отдельно.

2. **PostgreSQL integration**
   ```bash
   pytest -q -m integration tests/test_postgres_integration.py --timeout=60
   ```
   Ожидается 0 падений и 0 ошибок. Набор включает реальный путь CLI subprocess →
   PostgreSQL → тестовый OpenAI-compatible HTTP endpoint. Два multi-process E2E
   теста имеют собственный timeout 240 секунд.

3. **Coverage**
   ```bash
   pytest --cov=project_workflow --cov-report=term --timeout=60
   ```
   Ожидается общее покрытие не ниже 90%.

4. **Lint**
   ```bash
   ruff check .
   ```
   Ожидается `All checks passed!`.

5. **Type check**
   ```bash
   mypy project_workflow scripts
   ```
   Ожидается `Success: no issues found`.

6. **Readiness локального Compose**
   ```bash
   docker compose up --build -d
   curl --fail http://127.0.0.1:8812/health
   ```
   Ожидается HTTP `200` и `database=ok`, `schema=ok`.

7. **Браузерная проверка** для изменений UI
   - Открыть `http://127.0.0.1:8812/` и `http://127.0.0.1:8812/phases`.
   - Сохранить скриншот.

## Примечания

- Для стандартного полного набора использовать `pytest -q --timeout=60`.
  `--forked` не требуется; при нём отчёт coverage некорректен.
- `DATABASE_URL` обязателен в runtime. SQLite используется только в изолированных тестах.
- `project-workflow` хранит только имена skills. Канонические файлы находятся в
  `https://gt.wmtgroup.ru/relevanter/agent-skills` и загружаются исполнителем.
- `project-workflow` хранит только уникальное имя Hermes-профиля, назначенного
  агенту. Профилем владеет Hermes; исполнитель выбирает его командой
  `hermes --profile <profile> --oneshot <prompt>`.
- Воспроизводимый CLI acceptance описан в `LIVE_TEST_PLAN.md`.

## Осознанно исключённые возможности

Это внутренняя лёгкая агентская утилита, а не клиентский production-сервис.
Следующие возможности оценены и исключены из текущего scope:

| Возможность | Решение | Причина |
|---|---|---|
| CI/CD pipeline (GitLab/GitHub) | **Не добавлять** | Репозиторий обслуживается вручную; обязательных локальных проверок достаточно. |
| Security middleware (CORS, CSP, HTTPS redirect, rate limits) | **Не добавлять** | UI доступен только на loopback либо в защищённом private/VPN-контуре. |
| Локальные credentials в `docker-compose.yml` | **Допустимо только локально** | Compose публикуется только на loopback; внешний runtime обязан передавать собственный `DATABASE_URL`. |
| Observability / metrics / structured JSON logs | **Не добавлять** | Request logging и `/health` достаточны для внутренней утилиты. |
| Дополнительный слой sanitization | **Не добавлять** | API использует строгие Pydantic-схемы, SQLAlchemy ORM и параметризованный SQL. |
| Connection draining сверх lifespan dispose | **Не добавлять** | Для внутренней утилиты допустим краткий разрыв соединения при перезапуске. |
| Bandit/safety/pre-commit hooks | **Не добавлять** | Принятый quality bar: `ruff`, `mypy`, `pytest` и coverage. |

Если изменятся исходные условия, например появятся внешний доступ,
многопользовательский режим или клиентские данные, этот раздел нужно пересмотреть
до расширения scope.
