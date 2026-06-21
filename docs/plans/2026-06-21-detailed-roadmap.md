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

## 3. Docker Compose + Dockerfile + автомиграции

- [ ] `Dockerfile` multi-stage для Python app.
- [ ] `docker-compose.yml`: `db` (Postgres), `migrate` (Alembic), `api` (FastAPI UI).
- [ ] `entrypoint.sh` для migrate-сервиса: `alembic upgrade head`.
- [ ] `.env.example`.
- [ ] Проверка: `docker compose up --build` → UI доступен, миграции применены.

## 4. Миграция SQLite → Postgres

- [ ] Скрипт `scripts/migrate_sqlite_to_postgres.py`.
- [ ] Копирует workflows, phases, projects, tasks, agents, history, supervisor_runs.
- [ ] Пересчитывает sequence/serial id.
- [ ] Проверка: данные из старого SQLite видны в Postgres.

## 5. Перевод UI на SQLAlchemy-сервисы, удаление WorkflowDB

- [ ] Проверить, какие методы `WorkflowDB` используют `ui/services.py`, `ui/routes/*.py`, `ui/state.py`.
- [ ] Добавить недостающие методы в SQLAlchemy-сервисы / repositories.
- [ ] Заменить `_app_state.get_db()` на `_app_state.get_service()` или репозитории.
- [ ] Сохранить формат возвращаемых dict (чтобы шаблоны не ломались).
- [ ] Удалить `project_workflow/db/base.py` и старые SQLite-зависимости.
- [ ] Обновить `conftest.py`.
- [ ] Проверить `pytest` и UI в браузере.

## 6. Application services + чистка

- [ ] Глобальные exception handlers в `app.py`.
- [ ] Удалить дублирующие уровни абстракции.
- [ ] Привести wizard под отдельный пакет (только перенос файлов, без новой логики).
- [ ] `mypy --strict` зелёный.

## 7. Тесты

- [ ] 727 unit-тестов по-прежнему проходят на SQLite.
- [ ] Новые интеграционные тесты для Postgres (опционально, в Docker).
- [ ] UI smoke test после запуска в Docker.

## 8. Документация

- [ ] README: Docker Compose quickstart, Postgres schema, `DATABASE_URL`.
- [ ] `docs/deployment.md`.
- [ ] Удалить упоминания SQLite как основной базы.

---

## Порядок работы

1. Docker Compose + Dockerfile.
2. Миграция SQLite → Postgres.
3. UI на SQLAlchemy-сервисы.
4. Удаление WorkflowDB.
5. Чистка + mypy.
6. Тесты + документация.
