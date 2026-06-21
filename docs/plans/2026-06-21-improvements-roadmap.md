# План доработки project-workflow v3

> Автоматические миграции. Postgres. FastAPI + Jinja2 + HTMX — весь стек остаётся на Python. Docker Compose — единственный способ запуска dev/prod-like.

---

## 1. База данных: Postgres, одна схема, автомиграции

### 1.1. Цель
- SQLite уходит из runtime.
- Единая база `project_workflow`, единая схема `project_workflow`.
- `docker compose up` поднимает Postgres, прогоняет миграции и стартует приложение. Ручных действий не требуется.

### 1.2. Почему одна схема
- Монолитное приложение. Мульти-схемность — оверинжиниринг.
- `project_workflow` — namespace, который не конфликтует с другими сервисами в shared Postgres.

### 1.3. Задачи

#### P0. Перевод SQLAlchemy на Postgres
- Добавить `psycopg[binary]>=3.1` в `pyproject.toml`.
- Обновить `project_workflow/infrastructure/db/session.py`:
  - DSN из `DATABASE_URL`.
  - Postgres: `create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)`.
  - SQLite fallback только для тестов.
  - Убрать SQLite-specific `PRAGMA` listener из runtime (оставить в тестовом фикстуре).
- Обновить `project_workflow/infrastructure/db/models.py`:
  - Явные `ForeignKey(..., ondelete="CASCADE/SET NULL")`.
  - `DateTime(timezone=True)` вместо строковых timestamps.
  - Разумные длины `String`.
- Alembic:
  - `env.py` уже есть.
  - Добавить `version_table_schema="project_workflow"`.
  - Гарантировать `CREATE SCHEMA IF NOT EXISTS project_workflow` перед миграциями.

#### P0. Удаление legacy WorkflowDB
- Все UI/API/application сервисы должны ходить в SQLAlchemy-сервисы.
- Удалить `project_workflow/db/base.py` и тесты legacy DB API.
- Удалить модуль `project_workflow/db/`.

#### P0. Docker Compose + автоматические миграции

`docker-compose.yml`:
```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: project_workflow
      POSTGRES_USER: project_workflow
      POSTGRES_PASSWORD: ${DB_PASSWORD:-project_workflow}
    volumes:
      - project_workflow_postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U project_workflow -d project_workflow"]
      interval: 5s
      timeout: 5s
      retries: 5

  migrate:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: postgresql+psycopg://project_workflow:${DB_PASSWORD:-project_workflow}@postgres:5432/project_workflow?options=-csearch_path=project_workflow
    command: ["alembic", "upgrade", "head"]
    depends_on:
      postgres:
        condition: service_healthy

  api:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: postgresql+psycopg://project_workflow:${DB_PASSWORD:-project_workflow}@postgres:5432/project_workflow?options=-csearch_path=project_workflow
      UI_HOST: 0.0.0.0
      UI_PORT: 8811
    ports:
      - "8811:8811"
    command: ["python", "-m", "project_workflow.ui"]
    depends_on:
      migrate:
        condition: service_completed_successfully

volumes:
  project_workflow_postgres_data:
```

`Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
COPY project_workflow/ ./project_workflow/
RUN pip install --no-cache-dir -e ".[ui,db]"
EXPOSE 8811
```

`alembic` запускается через сервис `migrate`. `api` стартует только после успешного завершения `migrate`. Никаких ручных `alembic upgrade head`.

#### P0. Конфиг через Pydantic Settings
- `project_workflow/config.py` → Pydantic Settings:
  ```python
  DATABASE_URL: PostgresDsn
  UI_HOST: str = "0.0.0.0"
  UI_PORT: int = 8811
  LOG_LEVEL: str = "INFO"
  ```
- `DATABASE_URL` — единственный источник истины для подключения к базе.

### 1.4. Чек-лист
- [ ] `docker compose up --build` поднимает всё и отдаёт 200.
- [ ] `pytest` проходит в SQLite-режиме.
- [ ] Интеграционные тесты проходят против Postgres (pytest-postgresql / testcontainers).
- [ ] Legacy `WorkflowDB` удалён.

---

## 2. UI: FastAPI + Jinja2 + HTMX, но сделано по-человечески

### 2.1. Почему Python-стек
- Весь проект уже на Python/FastAPI.
- Не тянем JS-билд, Webpack, npm.
- HTMX даёт SPA-подобный UX без написания большого JS.
- Проблема не в Jinja2, а в текущей реализации: inline-стили, отсутствие компонентов, дублирование.

### 2.2. Структура шаблонов

```
project_workflow/templates/
├── base.html
├── components/
│   ├── sidebar.html
│   ├── header.html
│   ├── card.html
│   ├── toast.html
│   └── form_field.html
├── macros/
│   ├── forms.j2
│   ├── tables.j2
│   └── badges.j2
├── pages/
│   ├── dashboard.html
│   ├── workflows.html
│   ├── workflow_form.html
│   ├── phases.html
│   ├── phase_form.html
│   ├── projects.html
│   ├── project_form.html
│   ├── tasks.html
│   ├── task_detail.html
│   ├── agents.html
│   ├── skills.html
│   └── settings.html
└── partials/
    ├── workflow_row.html
    ├── phase_row.html
    ├── task_row.html
    └── toast.html
```

### 2.3. CSS-система
- Удалить все `style="..."` из шаблонов.
- Единый CSS-файл `project_workflow/static/css/project-workflow.css`.
- Design tokens:
  ```css
  :root {
    --pw-primary: #8B3A3A;
    --pw-primary-light: #A04040;
    --pw-bg: #0B1220;
    --pw-surface: #111827;
    --pw-text: #F9FAFB;
    --pw-text-muted: #9CA3AF;
    --pw-border: #374151;
    --pw-radius: 8px;
    --pw-space-xs: 4px;
    --pw-space-sm: 8px;
    --pw-space-md: 16px;
    --pw-space-lg: 24px;
  }
  ```
- Подключить `StaticFiles` в FastAPI.
- Использовать utility-first подход вручную или подключить **Tailwind CSS через CDN** (для SSR-проекта — приемлемо).

### 2.4. HTMX
- Vendored `htmx.min.js` в `project_workflow/static/js/htmx.min.js`.
- Формы отправляются через `hx-post`, `hx-put`, `hx-delete`.
- Обновление списков через `hx-target` + partials.
- Loading states через `hx-indicator`.
- Toast-уведомления через `hx-trigger` + `hx-swap`.

### 2.5. Backend UI-роуты
- Оставляем `project_workflow/ui/routes/pages.py` для страниц.
- Добавляем `project_workflow/ui/routes/partials.py` для HTMX-обновлений.
- Все POST/PUT/DELETE возвращают либо redirect, либо partial HTML для HTMX.
- Строгая валидация форм через Pydantic.

### 2.6. Задачи

#### P0. Рефактор шаблонов
- Вынести `base.html`, `components/`, `macros/`, `pages/`, `partials/`.
- Удалить inline-стили.
- Подключить CSS и HTMX.

#### P0. Production-ready страницы
- Dashboard с real данными, без synthetic KPI.
- Workflows: list + create/edit/delete.
- Phases: list per workflow + create/edit/delete + inline reorder.
- Projects: list + create/edit/delete.
- Tasks: list + detail + phase actions.
- Agents: list + create/edit/delete.
- Skills catalog.
- Settings: key patterns, skills mapping.

#### P1. HTMX-интерактивность
- Inline-edit фаз.
- Drag-and-drop reorder фаз (SortableJS или нативный HTML5 DnD + HTMX).
- Создание/удаление без перезагрузки страницы.
- Toast-уведомления.
- Фильтры и поиск по задачам/проектам.

#### P2. UX-доработки
- Формы с inline-ошибками.
- Loading skeletons.
- Empty states.
- Подтверждение удаления.

### 2.7. Чек-лист
- [ ] Нет inline-стилей.
- [ ] Есть `components/`, `macros/`, `pages/`, `partials/`.
- [ ] HTMX подключён и используется в 5+ формах.
- [ ] UI выглядит как единое приложение, а не набор HTML-страниц.
- [ ] README содержит скриншоты дашборда.

---

## 3. Docker Compose: единый источник правды

### 3.1. Dev
```bash
docker compose up --build
```
Backend на `localhost:8811`, Postgres на `localhost:5432`.

### 3.2. Production-like
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build
```
- Тот же образ.
- Postgres с volume.
- Без dev-only настроек.

### 3.3. env-файлы
- `.env.example` — dev.
- `.env.prod.example` — production-like.

### 3.4. Чек-лист
- [ ] `docker compose up` работает из коробки.
- [ ] Миграции применяются автоматически.
- [ ] `StaticFiles` раздаёт CSS/JS.

---

## 4. Тестирование

### 4.1. Backend tests
- SQLite-режим остаётся для unit-тестов.
- Добавить `tests/integration/test_postgres.py`.

### 4.2. UI tests
- `httpx`-based integration tests для всех UI-роутов.
- Проверка HTMX partials.
- Скриншоты через Playwright (опционально).

### 4.3. Docker integration tests
- `docker compose -f docker-compose.test.yml up --abort-on-container-exit`.

---

## 5. Порядок выполнения

1. **P0. Postgres + session.py + Pydantic Settings.**
2. **P0. Docker Compose + Dockerfile + автоматические Alembic-миграции.**
3. **P0. Перевод UI/API на SQLAlchemy-сервисы, удаление legacy WorkflowDB.**
4. **P0. Рефактор шаблонов: base, components, macros, pages, partials.**
5. **P0. CSS-система + HTMX-подключение.**
6. **P0. Production-ready страницы (Dashboard/Workflows/Phases/Projects/Tasks).**
7. **P1. HTMX-интерактивность: inline-edit, reorder, toasts, фильтры.**
8. **P1. Postgres-интеграционные тесты + UI integration tests.**
9. **P2. Agents/Skills/Settings, empty states, скриншоты для README.**

---

## 6. Что не делаем

- Не добавляем CLI-команды (freeze: только `step` и `history`).
- Не разбиваем базу на несколько схем.
- Не переходим на React/Vue/Svelte.
- Не добавляем Kubernetes / CI/CD / метрики в этот план.

---

## 7. Итоговая архитектура

```
┌─────────────────────────────┐
│   Browser                     │
│   HTMX + minimal JS          │
└─────────────┬─────────────────┘
              │
              ▼
┌─────────────────────────────┐
│   FastAPI                     │
│   - HTML routes (pages)       │
│   - HTMX partials             │
│   - JSON API                  │
└─────────────┬─────────────────┘
              │
              ▼
┌─────────────────────────────┐
│   SQLAlchemy + Alembic        │
└─────────────┬─────────────────┘
              │
              ▼
┌─────────────────────────────┐
│   Postgres                    │
│   DB: project_workflow        │
│   Schema: project_workflow    │
└─────────────────────────────┘
```

Единственная ручная команда разработчика: `docker compose up --build`.
