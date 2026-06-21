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

**Оставшееся:** удаление legacy `WorkflowDB` потребует перевода CLI/wizard (`project_workflow/wizard.py`, `cli/core.py`, `cli/ui.py`) на SQLAlchemy. Это вынесено в отдельный этап.

## 6. Application services + чистка

- [ ] Глобальные exception handlers в `app.py`.
- [ ] Удалить дублирующие уровни абстракции.
- [ ] Привести wizard под отдельный пакет (только перенос файлов, без новой логики).
- [ ] `mypy --strict` зелёный.

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


## 9. Перевод CLI/wizard на SQLAlchemy (pending)

- [ ] Перевести `project_workflow/schema.py` `load_phases()` на SQLAlchemy.
- [ ] Перевести `project_workflow/wizard.py`, `wizard_context.py`, `wizard_store.py` на SQLAlchemy-сервисы.
- [ ] Перевести `project_workflow/cli/core.py`, `cli/ui.py` на SQLAlchemy-сервисы.
- [ ] Удалить `project_workflow/db/base.py`.
- [ ] Обновить `tests/conftest.py` fixtures.
- [ ] `mypy --strict` зелёный по всему проекту.
