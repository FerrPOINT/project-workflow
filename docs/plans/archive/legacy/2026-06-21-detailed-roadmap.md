# План доработки project-workflow v6

> Только стабилизация и Postgres. UI не переписываем — только подгоняем под SQLAlchemy-сервисы. Никакого нового функционала.

---

## 0. Принципы

- **Никакого нового функционала.** Только сохранение существующего поведения.
- **Postgres — основная база.** SQLite остаётся fallback для unit-тестов.
- **Docker Compose — единственный способ запуска dev/prod-like.**
- **Миграции автоматические.** `docker compose up` сам делает `alembic upgrade head`.
- **UI не переписываем.** Только меняем источник данных: `WorkflowDB` → SQLAlchemy-сервисы.
- **Никакого React/HTMX/нового frontend-стека.**

---

## 1. Конфигурация (done)

- [x] Pydantic Settings: `DATABASE_URL`, `DB_SCHEMA`, `UI_HOST`, `UI_PORT`, `LOG_LEVEL`.
- [x] SQLite fallback и нормализация URL.
- [x] Совместимость со старыми env-переменными.

## 2. SQLAlchemy session + Alembic (done)

- [x] `session.py` поддерживает Postgres и SQLite.
- [x] `env.py` создаёт схему `project_workflow` перед миграциями.
- [x] `ensure_migrated()` для автозапуска миграций.

## 3. Docker Compose + Dockerfile + автомиграции (done)

- [x] `Dockerfile` multi-stage для Python app.
- [x] `docker-compose.yml`: `db` (Postgres), `migrate` (Alembic), `api` (FastAPI UI).
- [x] `scripts/init_db.py` создаёт схему и таблицы, затем `alembic stamp head`.
- [x] `.env.example`.
- [x] Проверка: `docker compose up --build` → UI доступен на http://localhost:8812, миграции применены.

## 4. Миграция SQLite → Postgres (done)

- [x] Скрипт `scripts/migrate_sqlite_to_postgres.py`.
- [x] Копирует workflows, phases, projects, tasks, agents, history, supervisor_runs.
- [x] Сбрасывает Postgres sequences после копирования.

## 5. Перевод UI на SQLAlchemy-сервисы (done)

- [x] `WorkflowDBCompat` адаптер покрывает все нужные методы UI/API.
- [x] `sync_phase_catalog` реализован через SQLAlchemy.
- [x] UI на Postgres и SQLite отвечает 200; шаблоны не переписывались.

## 6. Application services + чистка (done)

- [x] WorkflowDB переписан на SQLAlchemy (`project_workflow/db/base.py`).
- [x] Удалены sqlite3-импорты из runtime.
- [x] `mypy` green (с overrides для legacy wizard/CLI).

## 7. Тесты (done)

- [x] 727 unit-тестов по-прежнему проходят на SQLite.
- [x] UI smoke test после запуска в Docker (http://localhost:8812 — 200).

## 8. Документация (done)

- [x] README: Docker Compose quickstart, Postgres schema, `DATABASE_URL`.
- [x] Убраны упоминания SQLite как основной базы.

---

## Порядок работы

1. Docker Compose + Dockerfile.
2. Миграция SQLite → Postgres.
3. UI на SQLAlchemy-сервисы.
4. Удаление WorkflowDB.
5. Чистка + mypy.
6. Тесты + документация.


## 9. Перевод CLI/wizard на SQLAlchemy (done)

- [x] `project_workflow/db/base.py` переписан на SQLAlchemy: сохранён публичный API `WorkflowDB`, sqlite3 удалён.
- [x] `project_workflow/schema.py`, `wizard.py`, `wizard_context.py`, `wizard_store.py`, `cli/core.py`, `cli/ui.py` продолжают работать без изменений благодаря duck-typed адаптеру.
- [x] `tests/conftest.py` адаптирован под SQLAlchemy-backed `_conn`.
- [x] `mypy` green.
