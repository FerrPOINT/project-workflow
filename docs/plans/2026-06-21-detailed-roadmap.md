# План доработки project-workflow v5

> Минимальный план: никакого нового функционала, только стабилизация, Postgres, Docker Compose и приведение UI в порядок.

---

## 0. Принципы

- **Никакого нового функционала.** Только рефакторинг и стабилизация существующего.
- CLI: только `step` и `history`.
- Стек: Python + FastAPI + Jinja2 + CSS. Никакого HTMX/JS-фреймворков.
- Одна база Postgres, одна схема `project_workflow`.
- Миграции автоматические через Docker Compose.
- Docker Compose — единственный способ запуска dev/prod-like.
- Не добавляем Kubernetes / CI/CD / метрики / health-check / rate limiter / API versioning / HTMX / drag-and-drop / inline-edit / toast / modal / фильтры AJAX.

---

## 1. Инфраструктура и данные

### 1.1. Postgres

#### Задачи
1. Добавить `psycopg[binary]` в `pyproject.toml`.
2. Переписать `project_workflow/infrastructure/db/session.py`:
   - `DATABASE_URL` из env.
   - Postgres: `create_engine(url, pool_pre_ping=True)`.
   - SQLite fallback только для тестов.
   - Убрать `PRAGMA` listener из runtime.
3. Обновить `project_workflow/infrastructure/db/models.py`:
   - Явные `ForeignKey(..., ondelete=...)`.
   - `DateTime(timezone=True)` вместо строковых timestamps.
   - Разумные длины `String`.
4. Alembic:
   - `version_table_schema = "project_workflow"`.
   - `CREATE SCHEMA IF NOT EXISTS project_workflow` перед `upgrade`.
5. Сгенерировать свежую миграцию.

#### Артефакты
- `pyproject.toml`
- `project_workflow/infrastructure/db/session.py`
- `project_workflow/infrastructure/db/migrations/versions/xxxx_postgres_schema.py`

#### Чек-лист
- [ ] `pytest` green на SQLite.
- [ ] `alembic upgrade head` и `downgrade base` работают на Postgres.

---

### 1.2. Docker Compose

#### Задачи
1. `Dockerfile`: `python:3.11-slim`, `libpq-dev`, `pip install -e ".[ui,db]"`.
2. `docker-compose.yml`:
   - `postgres` с healthcheck.
   - `migrate` — `alembic upgrade head`, зависит от `postgres` healthy.
   - `api` — `python -m project_workflow.ui`, зависит от `migrate` completed.
   - volume для Postgres.
3. `.env.example` с `DATABASE_URL`, `UI_HOST`, `UI_PORT`, `LOG_LEVEL`.
4. `docker-compose.prod.yml` — без dev-only вещей.

#### Артефакты
- `Dockerfile`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `.env.example`
- `.env.prod.example`

#### Чек-лист
- [ ] `docker compose up --build` поднимает всё.
- [ ] `curl http://localhost:8811/` → 200.

---

### 1.3. Конфиг

#### Задачи
1. Переписать `project_workflow/config.py` на Pydantic Settings:
   ```python
   DATABASE_URL: PostgresDsn
   DB_SCHEMA: str = "project_workflow"
   UI_HOST: str = "0.0.0.0"
   UI_PORT: int = 8811
   LOG_LEVEL: str = "INFO"
   ```
2. Убрать `WORKFLOW_DB_PATH`, `WORKFLOW_DIR`, `WORKFLOW_UI_PORT`, `WORKFLOW_UI_HOST`.
3. Обновить systemd-сервис на `DATABASE_URL`.

#### Артефакты
- `project_workflow/config.py`
- `/etc/systemd/system/project-workflow-ui.service`

---

### 1.4. Миграция данных SQLite → Postgres

#### Задачи
1. Скрипт `scripts/migrate_sqlite_to_postgres.py`.
2. Читает SQLite, пишет в Postgres через SQLAlchemy.
3. Сверка count по таблицам.

#### Артефакты
- `scripts/migrate_sqlite_to_postgres.py`

---

### 1.5. Удаление legacy WorkflowDB

#### Задачи
1. Перевести UI routes на SQLAlchemy-сервисы.
2. Перевести wizard на application services.
3. Перевести CLI на SQLAlchemy-сервисы.
4. Удалить `project_workflow/db/base.py` и модуль `project_workflow/db/`.
5. Переписать/удалить legacy DB тесты.

#### Артефакты
- `project_workflow/application/services.py`
- Расширенный `project_workflow/infrastructure/db/repositories.py`

#### Чек-лист
- [ ] `grep -R "WorkflowDB\|from project_workflow.db" project_workflow/` — пусто.
- [ ] `pytest` green.

---

## 2. Backend

### 2.1. UI routes

#### Задачи
1. Оставить существующую структуру:
   - `pages.py` — HTML-страницы.
   - `api.py` — JSON endpoints.
2. Не добавлять `/api/v1/`, не добавлять HTMX partials.
3. Все POST/PUT/DELETE — обычные формы с redirect после успеха.
4. Pydantic-схемы для валидации входов.
5. Глобальный exception handler: 422 с понятной ошибкой, 500 с логом.

#### Артефакты
- `project_workflow/ui/routes/pages.py`
- `project_workflow/ui/routes/api.py`
- `project_workflow/ui/exceptions.py`

---

### 2.2. Application services

#### Задачи
1. Создать сервисы:
   - `WorkflowService`
   - `PhaseService`
   - `ProjectService`
   - `TaskService`
   - `AgentService`
2. Каждый сервис принимает `uow`.
3. Бизнес-логика в сервисах, роуты только валидируют и форматируют ответ.

#### Артефакты
- `project_workflow/application/services.py`

---

### 2.3. Wizard refactoring

#### Задачи
1. Разбить `wizard.py`:
   - `wizard/engine.py`
   - `wizard/checks.py`
   - `wizard/evaluate.py`
   - `wizard/format.py`
2. Убрать глобальное состояние.
3. Перевести на application services.
4. Добавить mypy-типизацию.

#### Артефакты
- `project_workflow/wizard/` package.

---

## 3. UI: нормальный SSR без нового функционала

### 3.1. Структура шаблонов

```
project_workflow/templates/
├── base.html
├── components/
│   ├── sidebar.html
│   ├── header.html
│   ├── card.html
│   ├── form_field.html
│   └── empty_state.html
├── macros/
│   ├── forms.j2
│   ├── tables.j2
│   ├── badges.j2
│   └── icons.j2
├── pages/
│   ├── dashboard.html
│   ├── workflows.html
│   ├── workflow_detail.html
│   ├── phases.html
│   ├── phase_detail.html
│   ├── projects.html
│   ├── project_detail.html
│   ├── tasks.html
│   ├── task_detail.html
│   ├── agents.html
│   ├── skills.html
│   └── settings.html
```

#### Задачи
1. Переместить шаблоны в эту структуру.
2. Все страницы наследуют `base.html`.
3. Вынести повторяющиеся блоки в components/macros.

---

### 3.2. CSS

#### Задачи
1. `project_workflow/static/css/project-workflow.css`.
2. Design tokens:
   ```css
   :root {
     --pw-primary: #8B3A3A;
     --pw-bg: #0B1220;
     --pw-surface: #111827;
     --pw-text: #F9FAFB;
     --pw-border: #374151;
     --pw-radius: 8px;
     --pw-space-md: 16px;
   }
   ```
3. Компоненты: `.btn`, `.btn-primary`, `.card`, `.table`, `.form-input`, `.badge`.
4. Подключить `StaticFiles`.
5. Удалить все inline-стили.

#### Артефакты
- `project_workflow/static/css/project-workflow.css`

---

### 3.3. Страницы

#### Задачи
1. Dashboard — real данные, без synthetic KPI.
2. Workflows — CRUD (как сейчас, но с нормальной вёрсткой).
3. Phases — CRUD, без drag-and-drop.
4. Projects — CRUD.
5. Tasks — list + detail.
6. Agents — CRUD.
7. Skills catalog.
8. Settings — key patterns, skills mapping.

#### Чек-лист
- [ ] Все страницы работают через обычные POST/redirect.
- [ ] Нет inline-стилей.
- [ ] Нет новых JS-фреймворков.

---

## 4. Безопасность

### 4.1. Валидация
1. Pydantic-модели для всех входов.
2. Только SQLAlchemy ORM — никакого raw SQL.
3. Jinja2 autoescape включён.

### 4.2. Логирование
1. Настроить стандартный logging.
2. JSON-формат в production, readable в dev.
3. Логировать HTTP-запросы и supervisor runs.

#### Артефакты
- `project_workflow/logging_config.py`

---

## 5. Тестирование

### 5.1. Backend
1. Сохранить 727 unit-тестов на SQLite.
2. `tests/integration/test_postgres.py`.
3. API tests для `/api/*` endpoints.

### 5.2. UI
1. Integration tests через `httpx` + TestClient для HTML-роутов.

### 5.3. Docker
1. Проверить `docker compose up --build` вручную.

---

## 6. Документация

### 6.1. README
1. Quickstart: `docker compose up --build`.
2. CLI examples.
3. API overview.
4. Скриншоты UI.

### 6.2. Документация для разработчиков
1. `docs/architecture.md`
2. `docs/ui/components.md`
3. `docs/ui/css-tokens.md`
4. `docs/api.md`
5. `docs/deployment.md`

---

## 7. Порядок выполнения

### Этап 1: Фундамент
1. Pydantic Settings config.
2. Postgres session + Alembic schema.
3. Docker Compose + Dockerfile + автомиграции.
4. Миграция SQLite → Postgres.
5. Перевод UI/API на SQLAlchemy-сервисы.
6. Удаление legacy `WorkflowDB`.

### Этап 2: Backend
7. Application services.
8. Exception handlers.
9. Wizard refactoring.
10. mypy green по `project_workflow/`.

### Этап 3: UI
11. Рефактор шаблонов: base, components, macros, pages.
12. CSS-система + StaticFiles.
13. Production-ready страницы (без HTMX, drag-and-drop, inline-edit).

### Этап 4: Тесты и документация
14. Postgres integration tests.
15. API + HTML route tests.
16. README + screenshots + docs.

---

## 8. Что не делаем

- Не добавляем CLI-команды.
- Не переходим на React/Vue/Svelte/HTMX.
- Не разбиваем Postgres на схемы.
- Не версионируем API.
- Не добавляем rate limiter.
- Не добавляем drag-and-drop / inline-edit / toast / modal / AJAX-фильтры.
- Не добавляем Kubernetes / CI/CD / метрики / health-check.

---

## 9. Итоговая архитектура

```
Browser
  HTML + CSS
    │
    ▼
FastAPI
  ├── HTML pages (/workflows, /tasks, ...)
  └── JSON API (/api/*) — существующее
    │
    ▼
Application services
Wizard engine
    │
    ▼
SQLAlchemy + Alembic
    │
    ▼
Postgres
  DB: project_workflow
  Schema: project_workflow
```
