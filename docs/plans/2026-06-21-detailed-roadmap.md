# Детальный план развития project-workflow

> Полный план: Postgres, Docker Compose, production-ready UI на HTMX, удаление технического долга, безопасность, тестирование, документация.

---

## 0. Принципы (не обсуждаются)

- CLI остаётся ровно с двумя командами: `step` и `history`.
- Язык разработки: Python. Frontend: Jinja2 + HTMX + CSS.
- Одна база Postgres, одна схема `project_workflow`.
- Миграции автоматические через Docker Compose.
- Docker Compose — единственный способ запуска dev/prod-like.
- Не добавляем Kubernetes / CI/CD / метрики / health-check endpoints в этом плане.

---

## 1. Инфраструктура и данные

### 1.1. Postgres: миграция с SQLite

#### Задачи

1. **Добавить `psycopg[binary]`** в `pyproject.toml`.
2. **Переписать `project_workflow/infrastructure/db/session.py`**:
   - `DATABASE_URL` из env.
   - `create_engine(url, pool_pre_ping=True)`.
   - SQLite fallback только для тестов (через отдельную фабрику).
   - Убрать `PRAGMA` listener из runtime.
3. **Обновить `project_workflow/infrastructure/db/models.py`**:
   - Явные `ForeignKey(..., ondelete=...)`.
   - `DateTime(timezone=True)` вместо строковых timestamp-ов.
   - `String` с разумными длинами.
   - Убедиться, что все primary keys — `Integer, primary_key=True`.
4. **Alembic**:
   - `version_table_schema = "project_workflow"`.
   - `target_metadata = Base.metadata`.
   - В `env.py` гарантировать `CREATE SCHEMA IF NOT EXISTS project_workflow` перед `command.upgrade()`.
5. **Сгенерировать свежую миграцию** на основе актуальных моделей.

#### Артефакты
- `pyproject.toml` с `psycopg[binary]`.
- `project_workflow/infrastructure/db/session.py`.
- `project_workflow/infrastructure/db/migrations/versions/xxxx_postgres_schema.py`.

#### Чек-лист
- [ ] `pytest` проходит на SQLite.
- [ ] `alembic upgrade head` работает на чистой Postgres.
- [ ] `alembic downgrade base` работает.

---

### 1.2. Docker Compose

#### Задачи

1. **Создать `Dockerfile`**:
   - `python:3.11-slim`.
   - `apt-get install libpq-dev gcc`.
   - `pip install -e ".[ui,db]"`.
   - Не копировать `tests/`, `.git/`, `.venv/`.
2. **Создать `docker-compose.yml`**:
   - `postgres` с healthcheck.
   - `migrate` — `alembic upgrade head`, зависит от `postgres` healthy.
   - `api` — `python -m project_workflow.ui`, зависит от `migrate` completed.
   - volume `project_workflow_postgres_data`.
3. **Создать `.env.example`**:
   ```
   DATABASE_URL=postgresql+psycopg://project_workflow:project_workflow@postgres:5432/project_workflow?options=-csearch_path=project_workflow
   UI_HOST=0.0.0.0
   UI_PORT=8811
   LOG_LEVEL=INFO
   ```
4. **Создать `docker-compose.prod.yml`**:
   - Без dev-only переменных.
   - Postgres с volume на хосте.
5. **Создать `docker-compose.test.yml`**:
   - Postgres + migrate + test runner.

#### Артефакты
- `Dockerfile`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `docker-compose.test.yml`
- `.env.example`
- `.env.prod.example`

#### Чек-лист
- [ ] `docker compose up --build` поднимает Postgres, миграции, API.
- [ ] `curl http://localhost:8811/` возвращает 200.
- [ ] `docker compose -f docker-compose.test.yml up --abort-on-container-exit` проходит.

---

### 1.3. Конфигурация через Pydantic Settings

#### Задачи

1. **Переписать `project_workflow/config.py`** на Pydantic `BaseSettings`:
   ```python
   class Settings(BaseSettings):
       DATABASE_URL: PostgresDsn
       DB_SCHEMA: str = "project_workflow"
       UI_HOST: str = "0.0.0.0"
       UI_PORT: int = 8811
       LOG_LEVEL: str = "INFO"
   ```
2. **Убрать `WORKFLOW_DB_PATH`, `WORKFLOW_DIR`, `WORKFLOW_UI_PORT`, `WORKFLOW_UI_HOST`**.
3. **Обновить systemd-сервис** (`/etc/systemd/system/project-workflow-ui.service`) на `Environment="DATABASE_URL=..."`.
4. **Обновить `project_workflow/ui/main.py`** и CLI на использование `Settings`.

#### Артефакты
- `project_workflow/config.py`
- Обновлённый `/etc/systemd/system/project-workflow-ui.service`

#### Чек-лист
- [ ] Приложение падает с понятной ошибкой, если `DATABASE_URL` невалидный.
- [ ] `docker compose` и systemd используют одинаковые переменные.

---

### 1.4. Удаление legacy `WorkflowDB`

#### Задачи

1. **Переписать UI routes (`project_workflow/ui/routes/api.py` и `pages.py`)** на SQLAlchemy-сервисы.
2. **Переписать wizard** (`project_workflow/wizard.py`) с `WorkflowDB` на `UnitOfWork` / repositories.
3. **Переписать CLI** (`project_workflow/cli/ui.py`) на SQLAlchemy-сервисы.
4. **Удалить `project_workflow/db/base.py`**.
5. **Удалить `project_workflow/db/`**.
6. **Удалить или переписать тесты legacy DB**.

#### Артефакты
- `project_workflow/application/services.py` (полноценный application layer).
- `project_workflow/infrastructure/db/repositories.py` (дополненный).

#### Чек-лист
- [ ] `grep -R "WorkflowDB\|from project_workflow.db" project_workflow/` — пусто.
- [ ] `pytest` проходит.
- [ ] `ruff check` green.

---

## 2. Backend: API и application layer

### 2.1. Единый API

#### Задачи

1. **Отделить HTML-роуты от JSON API**:
   - `project_workflow/ui/routes/pages.py` — только GET страницы.
   - `project_workflow/ui/routes/api.py` — только JSON REST API.
   - `project_workflow/ui/routes/partials.py` — HTMX partials.
2. **Все API-ответы через Pydantic-модели**.
3. **Добавить CORS** для dev-режима (origins из env).
4. **Добавить глобальный exception handler**:
   - 422 → понятная JSON-ошибка.
   - 500 → лог + generic message в production.
5. **Версионирование API**:
   - Все JSON endpoints под `/api/v1/...`.
   - HTMX partials под `/partials/...`.
   - HTML pages под `/...`.

#### Артефакты
- `project_workflow/ui/routes/pages.py`
- `project_workflow/ui/routes/api.py`
- `project_workflow/ui/routes/partials.py`
- `project_workflow/ui/exceptions.py`

#### Чек-лист
- [ ] `/api/v1/workflows` возвращает JSON.
- [ ] `/workflows` возвращает HTML.
- [ ] `/partials/workflow/1` возвращает HTMX partial.

---

### 2.2. Application services

#### Задачи

1. **Создать полноценный application layer**:
   - `WorkflowService`
   - `PhaseService`
   - `ProjectService`
   - `TaskService`
   - `AgentService`
   - `SupervisorService`
2. **Каждый сервис** принимает `uow: IUnitOfWork`.
3. **Все бизнес-правила** (constraint checks, переходы фаз) — в сервисах, не в роутах.
4. **DTO через Pydantic**.

#### Артефакты
- `project_workflow/application/services.py` (разбить на `services/workflow.py`, `services/phase.py` и т.д. если разрастётся).

#### Чек-лист
- [ ] Роуты не содержат бизнес-логики, только валидацию входа и форматирование ответа.
- [ ] Сервисы покрыты unit-тестами.

---

### 2.3. Wizard refactoring

#### Задачи

1. **Разбить `project_workflow/wizard.py`**:
   - `wizard/engine.py` — основной цикл.
   - `wizard/checks.py` — проверки.
   - `wizard/evaluate.py` — supervisor evaluation.
   - `wizard/format.py` — format_result.
2. **Убрать глобальное состояние**.
3. **Перевести wizard на application services**.
4. **Добавить mypy-типизацию**.

#### Артефакты
- `project_workflow/wizard/` package.

#### Чек-лист
- [ ] `mypy project_workflow/wizard/` green.
- [ ] Все wizard-тесты проходят.

---

## 3. UI: production-ready HTMX + Jinja2

### 3.1. Структура шаблонов

#### Задачи

1. **Переместить шаблоны**:
   ```
   project_workflow/templates/
   ├── base.html
   ├── components/
   │   ├── sidebar.html
   │   ├── header.html
   │   ├── card.html
   │   ├── toast.html
   │   ├── modal.html
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
   └── partials/
       ├── workflow_row.html
       ├── phase_row.html
       ├── project_row.html
       ├── task_row.html
       └── toast.html
   ```
2. **Все страницы наследуют `base.html`**.
3. **Все повторяющиеся блоки вынесены в components/macros**.

#### Артефакты
- Перестроенная директория `project_workflow/templates/`.

#### Чек-лист
- [ ] Нет дублирования вёрстки.
- [ ] Все inline-стили удалены.

---

### 3.2. CSS-система

#### Задачи

1. **Создать `project_workflow/static/css/project-workflow.css`**.
2. **Design tokens**:
   ```css
   :root {
     --pw-primary: #8B3A3A;
     --pw-primary-hover: #A04040;
     --pw-bg: #0B1220;
     --pw-surface: #111827;
     --pw-surface-elevated: #1F2937;
     --pw-text: #F9FAFB;
     --pw-text-muted: #9CA3AF;
     --pw-border: #374151;
     --pw-success: #10B981;
     --pw-warning: #F59E0B;
     --pw-danger: #EF4444;
     --pw-radius-sm: 4px;
     --pw-radius: 8px;
     --pw-radius-lg: 12px;
     --pw-space-xs: 4px;
     --pw-space-sm: 8px;
     --pw-space-md: 16px;
     --pw-space-lg: 24px;
     --pw-space-xl: 32px;
   }
   ```
3. **Utility classes**: layout, flex, grid, spacing, typography, colors.
4. **Component classes**: `.btn`, `.btn-primary`, `.card`, `.table`, `.form-input`, `.badge`, `.toast`.
5. **Подключить `StaticFiles` в FastAPI**.

#### Артефакты
- `project_workflow/static/css/project-workflow.css`
- `project_workflow/static/js/htmx.min.js`
- `project_workflow/static/js/project-workflow.js`

#### Чек-лист
- [ ] UI выглядит единообразно.
- [ ] Нет inline-стилей в шаблонах.

---

### 3.3. HTMX-интерактивность

#### Задачи

1. **Vendored HTMX** в `static/js/htmx.min.js`.
2. **Формы**:
   - `hx-post`, `hx-put`, `hx-delete`.
   - `hx-target="#list"`.
   - `hx-swap="outerHTML"`.
3. **Inline-edit** для фаз и workflow name/description.
4. **Reorder фаз**:
   - HTML5 drag-and-drop или SortableJS.
   - POST `/partials/phases/reorder`.
5. **Toast-уведомления** после успешных операций.
6. **Подтверждение удаления** через modal.
7. **Фильтры и поиск** по tasks/projects без перезагрузки.

#### Артефакты
- `project_workflow/ui/routes/partials.py`
- `project_workflow/static/js/project-workflow.js`

#### Чек-лист
- [ ] Создание workflow без перезагрузки страницы.
- [ ] Удаление phase с подтверждением.
- [ ] Reorder фаз drag-and-drop.
- [ ] Фильтр tasks по статусу.

---

### 3.4. Страницы

#### Задачи

1. **Dashboard**:
   - Реальные данные.
   - Карточки: Projects, Tasks, Active, Done.
   - Последние задачи.
2. **Workflows**:
   - Список + create/edit/delete.
   - Переход к phases.
3. **Phases**:
   - Список фаз workflow.
   - Create/edit/delete.
   - Reorder.
   - Назначение skills.
4. **Projects**:
   - Список + create/edit/delete.
   - Связь с workflow.
5. **Tasks**:
   - Список с фильтрами.
   - Task detail с историей supervisor runs.
6. **Agents**:
   - CRUD.
7. **Skills catalog**:
   - Сканирование Hermes skills.
   - Mapping к фазам.
8. **Settings**:
   - Key patterns.
   - Skills mapping.
   - DB connection (read-only для production).

#### Чек-лист
- [ ] Все страницы существуют и работают.
- [ ] Нет placeholder/synthetic данных.

---

## 4. Безопасность и надёжность

### 4.1. Валидация и безопасность

#### Задачи

1. **Pydantic-модели для всех входов**:
   - Query params, form data, JSON body.
2. **Защита от SQL-инъекций**:
   - Только SQLAlchemy ORM / parameterized queries.
   - Удалить оставшийся raw SQL.
3. **XSS-защита**:
   - Jinja2 autoescape включён.
   - Никакого `| safe` без валидации.
4. **CSRF**:
   - Для HTMX-форм добавить CSRF-токен.
   - `htmx.config.includeIndicatorStyles = false`.
5. **Rate limiting**:
   - `slowapi` или middleware на `/api/*`.
   - Особенно на endpoint supervisor evaluation.

#### Артефакты
- `project_workflow/ui/schemas.py` (расширенный).
- `project_workflow/ui/middleware.py`.

#### Чек-лист
- [ ] `grep -R "execute\(" project_workflow/infrastructure project_workflow/ui project_workflow/application` — только SQLAlchemy.
- [ ] Все формы с CSRF-токеном.

---

### 4.2. Логирование и observability

#### Задачи

1. **Настроить `structlog`** или стандартный logging.
2. **Единый формат логов** JSON в production, readable в dev.
3. **Логировать**:
   - Все HTTP-запросы (method, path, status, duration).
   - Supervisor runs (task, phase, verdict).
   - Ошибки с traceback.
4. **Log level из env**.

#### Артефакты
- `project_workflow/logging_config.py`

#### Чек-лист
- [ ] `docker compose logs api` показывает запросы.
- [ ] Ошибки содержат correlation id.

---

## 5. Тестирование

### 5.1. Backend tests

#### Задачи

1. **Сохранить 727 unit-тестов** на SQLite.
2. **Добавить Postgres-интеграционные тесты**:
   - `tests/integration/test_postgres.py`.
   - Использовать `pytest-postgresql` или testcontainers.
3. **API-тесты** для всех `/api/v1/*` endpoints.
4. **HTMX partial tests** для `/partials/*`.
5. **Application service tests**.

### 5.2. Frontend/UI tests

#### Задачи

1. **Integration tests** через `httpx` + TestClient.
2. **Playwright E2E smoke tests**:
   - Dashboard загружается.
   - CRUD workflow.
   - CRUD phase.
3. **Скриншотные тесты** (опционально).

### 5.3. Docker tests

#### Задачи

1. **`docker-compose.test.yml`**.
2. **Запуск**: `docker compose -f docker-compose.test.yml up --build --abort-on-container-exit`.

---

## 6. Документация

### 6.1. README

#### Задачи

1. **Актуальная архитектура**.
2. **Quickstart**: `docker compose up --build`.
3. **CLI examples** с `project-workflow`.
4. **API overview**.
5. **Скриншоты UI**.
6. **Roadmap link**.

### 6.2. Документация для разработчиков

#### Задачи

1. `docs/architecture.md` — слои, data flow.
2. `docs/ui/components.md` — список Jinja2 компонентов.
3. `docs/ui/css-tokens.md` — design tokens.
4. `docs/api.md` — endpoints.
5. `docs/deployment.md` — Docker Compose, systemd.

### 6.3. Комментарии в коде

#### Задачи

1. Docstrings для всех public функций/классов.
2. TODO/FIXME — только с issue reference.

---

## 7. Миграция данных

### 7.1. Из SQLite в Postgres

#### Задачи

1. **Скрипт `scripts/migrate_sqlite_to_postgres.py`**:
   - Читает SQLite из `WORKFLOW_DB_PATH` или аргумента.
   - Пишет в Postgres через SQLAlchemy.
   - Сохраняет ID-шники, constraints, foreign keys.
2. **Проверка**:
   - Сверка количества записей по таблицам.
   - Проверка целостности FK.

#### Артефакты
- `scripts/migrate_sqlite_to_postgres.py`

#### Чек-лист
- [ ] Скрипт успешно переносит текущую SQLite БД в Postgres.
- [ ] UI после миграции показывает те же данные.

---

## 8. Порядок выполнения

### Этап 1: Фундамент (P0)
1. Pydantic Settings config.
2. Postgres session + Alembic schema setup.
3. Docker Compose + Dockerfile + автомиграции.
4. Перевод UI/API на SQLAlchemy-сервисы.
5. Удаление legacy `WorkflowDB`.

### Этап 2: Backend чистота (P0)
6. Application services (Workflow, Phase, Project, Task, Agent).
7. REST API `/api/v1/*` + exception handlers + CORS.
8. Wizard refactoring на application services.
9. mypy зелёный по `project_workflow/` (цель).

### Этап 3: UI редизайн (P0)
10. Рефактор шаблонов: base, components, macros, pages, partials.
11. CSS-система + StaticFiles.
12. HTMX подключение.
13. Production-ready страницы Dashboard/Workflows/Phases/Projects/Tasks.

### Этап 4: UI интерактивность (P1)
14. HTMX формы без перезагрузки.
15. Inline-edit, reorder фаз.
16. Toast, modal, filters, search.
17. Agents, Skills, Settings pages.

### Этап 5: Тесты и безопасность (P1)
18. Postgres integration tests.
19. API tests.
20. HTMX partial tests.
21. CSRF, rate limiting, input validation.

### Этап 6: Документация и деплой (P2)
22. README + screenshots.
23. `docs/architecture.md`, `docs/ui/*`, `docs/api.md`.
24. `docker-compose.prod.yml`.
25. Миграционный скрипт SQLite → Postgres.

---

## 9. Чек-листы завершения этапов

### Этап 1
- [ ] `docker compose up --build` работает.
- [ ] `pytest` green.
- [ ] `WorkflowDB` удалён.

### Этап 2
- [ ] `mypy project_workflow/` green.
- [ ] Все API endpoints под `/api/v1/`.
- [ ] Роуты не содержат бизнес-логики.

### Этап 3
- [ ] Нет inline-стилей.
- [ ] Все страницы работают.
- [ ] UI единообразный.

### Этап 4
- [ ] 5+ HTMX-форм без перезагрузки.
- [ ] Reorder фаз drag-and-drop.
- [ ] Toast-уведомления.

### Этап 5
- [ ] Postgres integration tests green.
- [ ] API tests green.
- [ ] CSRF на формах.

### Этап 6
- [ ] README со скриншотами.
- [ ] Документация завершена.
- [ ] Prod compose проверен.

---

## 10. Что явно НЕ делаем

- Не добавляем новые CLI-команды.
- Не переходим на React/Vue/Svelte.
- Не разбиваем Postgres на несколько схем.
- Не добавляем Kubernetes, CI/CD pipelines, health-check endpoints, Prometheus-метрики в этом плане.
- Не переписываем логику supervisor evaluation на другой язык/фреймворк.

---

## 11. Итоговая архитектура

```
┌─────────────────────────────┐
│ Browser                      │
│ HTMX + minimal JS           │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│ FastAPI                      │
│ ├── HTML routes (pages)      │
│ ├── HTMX partials            │
│ └── REST API (/api/v1/*)     │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│ Application services         │
│ Wizard engine                │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│ SQLAlchemy + Alembic         │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│ Postgres                     │
│ DB: project_workflow         │
│ Schema: project_workflow     │
└─────────────────────────────┘
```
