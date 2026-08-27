# Quality Gate

Этот файл фиксирует локальный quality gate для `project-workflow`. Hosted CI в
текущем scope не используется; перед commit разработчик запускает релевантные
локальные проверки.

## Базовый gate

```bash
uv run --isolated --with-requirements constraints.txt --all-extras pytest -q --timeout=60
uv run --isolated --with-requirements constraints.txt --all-extras pytest -q -m integration tests/test_postgres_integration.py --timeout=120
uv run --isolated --with-requirements constraints.txt --all-extras pytest --cov=project_workflow --cov-report=term --timeout=60
uv run --isolated --with-requirements constraints.txt --all-extras ruff check .
uv run --isolated --with-requirements constraints.txt --all-extras mypy project_workflow scripts
git diff --check
```

Ожидаемый результат:

- обычный pytest проходит без падений; PostgreSQL integration tests в нём
  показываются как deselected;
- отдельный PostgreSQL integration gate проходит на реальном PostgreSQL;
- coverage остаётся не ниже текущего локального baseline `94%`
  (`pyproject.toml` оставляет аварийный нижний порог `90%`);
- `ruff`, `mypy` и `git diff --check` не находят ошибок.

## ResourceWarning Gate

После изменений в тестовой инфраструктуре, SQLAlchemy layer, UI request
lifecycle или CLI session lifecycle дополнительно запускать:

```bash
uv run --isolated --with-requirements constraints.txt --all-extras pytest -q --timeout=60 -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
```

Этот прогон должен проходить без SQLite connection warnings, включая
`PytestUnraisableExceptionWarning`, и без зависаний на повторных миграционных
кейсах. Если тест создаёт `SAUnitOfWork` вручную, он должен использовать context
manager или закрываться через общий pytest lifecycle в `tests/conftest.py`. Если
тест создаёт SQLite engine напрямую, engine должен быть disposed в teardown.

## PostgreSQL Integration

Integration tests требуют локальный PostgreSQL с правом создавать и удалять
временные базы:

```bash
PGHOST=127.0.0.1
PGPORT=5432
PGUSER=project_workflow
PGPASSWORD=project_workflow
PGDATABASE=project_workflow
```

Набор `tests/test_postgres_integration.py` проверяет реальный путь CLI
subprocess -> PostgreSQL -> тестовый OpenAI-compatible HTTP endpoint ->
Supervisor -> PostgreSQL. Это deterministic runtime integration, а не полный
business E2E с настоящим исполнителем.

Полный executor-driven acceptance описан отдельно в
[`LIVE_TEST_PLAN.md`](../LIVE_TEST_PLAN.md).

## Compose Readiness

Для проверки локального runtime:

```bash
docker compose up --build -d --wait
curl --fail http://127.0.0.1:8812/health
```

Ожидается HTTP `200`, `database=ok`, `schema=ok`. Стандартный Compose публикует
PostgreSQL и API только на loopback.

## UI Smoke

После любых изменений UI/templates/static JS:

- открыть `http://127.0.0.1:8812/`;
- открыть `http://127.0.0.1:8812/phases`;
- проверить, что страницы загрузились без console/network ошибок;
- сохранить screenshot evidence для изменённых экранов.

Для backend-only тестовых или документационных изменений browser smoke не
обязателен.
