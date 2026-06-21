# План доработки project-workflow v2

> Автоматические миграции. Postgres. React + TypeScript frontend. Docker Compose — единственный способ запуска dev/prod-like.

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
  DATABASE_URL: PostgresDns
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

## 2. UI: отдельный React + TypeScript frontend

### 2.1. Почему React, а не Jinja2/HTMX
- Текущий SSR-Jinja2 превращается в лапшу из inline-стилей и шаблонов.
- GitHub отображает репо как "HTML" — выглядит неадекватно.
- React + TypeScript — стандарт production UI. GitHub покажет TypeScript/React в статистике.
- API backend уже есть. Frontend ходит в `/api/*`.

### 2.2. Структура frontend

```
frontend/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api/
│   │   └── client.ts          # axios/fetch wrapper
│   ├── components/
│   │   ├── Layout.tsx
│   │   ├── Sidebar.tsx
│   │   ├── Dashboard.tsx
│   │   ├── WorkflowList.tsx
│   │   ├── WorkflowForm.tsx
│   │   ├── PhaseList.tsx
│   │   ├── PhaseForm.tsx
│   │   ├── ProjectList.tsx
│   │   ├── ProjectForm.tsx
│   │   ├── TaskList.tsx
│   │   ├── TaskDetail.tsx
│   │   ├── AgentList.tsx
│   │   ├── SkillsCatalog.tsx
│   │   └── Settings.tsx
│   ├── hooks/
│   │   ├── useApi.ts
│   │   ├── useDashboard.ts
│   │   └── useMutation.ts
│   ├── types/
│   │   └── index.ts
│   └── styles/
│       └── index.css
```

### 2.3. Техстек frontend
- React 18
- TypeScript
- Vite (сборка + dev server + proxy к backend)
- Tailwind CSS или Mantine UI
- React Query / TanStack Query для кеширования API
- React Router для навигации
- Axios для HTTP

### 2.4. Интеграция с backend
- Backend отдаёт API на `localhost:8811/api/*`.
- Vite dev server проксирует `/api` → `http://localhost:8811`.
- Production: frontend билдится в `frontend/dist/` и отдаётся через FastAPI `StaticFiles` + `index.html` для всех не-API путей.

### 2.5. Backend API — доработки
- Все HTML-роуты из `project_workflow/ui/routes/pages.py` удаляются.
- Остаются только JSON API в `project_workflow/ui/routes/api.py`.
- Добавить CORS для dev-режима.
- Добавить `StaticFiles(directory="frontend/dist", html=True)` для production.
- Все API-ответы — строго типизированные Pydantic-модели.

### 2.6. Задачи

#### P0. Frontend scaffold
- `frontend/` с Vite + React + TS.
- Tailwind CSS подключён.
- Базовый `Layout` + `Sidebar`.
- API client.

#### P0. Страницы CRUD
- Dashboard
- Workflows (list, create, edit, delete)
- Phases (list per workflow, create, edit, delete, reorder)
- Projects (list, create, edit, delete)
- Tasks (list, detail, phase transition via `project-workflow step` integration)
- Agents
- Skills catalog
- Settings (key patterns, skills mapping)

#### P1. UX
- Toast-уведомления.
- Формы с валидацией.
- Drag-and-drop для reorder фаз.
- Фильтры и поиск.
- Loading / error states.

#### P2. Production build
- `frontend/Dockerfile` для сборки.
- Backend раздаёт статику.
- `docker-compose.yml` включает `frontend` сервис (опционально для dev).

### 2.7. Чек-лист
- [ ] `frontend/` scaffold с Vite + React + TS.
- [ ] Backend отдаёт только JSON API.
- [ ] Все страницы из текущего UI перенесены в React.
- [ ] `docker compose up` поднимает backend + Postgres + frontend.
- [ ] GitHub статистика показывает TypeScript/React вместо HTML.

---

## 3. Docker Compose: единый источник правды

### 3.1. Dev-режим
```bash
docker compose up --build
```
Backend на `localhost:8811`, frontend dev server на `localhost:5173`, Postgres на `localhost:5432`.

### 3.2. Production-like
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build
```
- Frontend билдится в `frontend/dist/`.
- Backend раздаёт статику.
- Postgres с volume.
- Без dev server.

### 3.3. env-файлы
- `.env.example` — для dev.
- `.env.prod.example` — для production-like.

### 3.4. Чек-лист
- [ ] `docker compose up` работает из коробки.
- [ ] Миграции применяются автоматически.
- [ ] Frontend и backend видят друг друга.

---

## 4. Тестирование

### 4.1. Backend tests
- SQLite-режим остаётся для unit-тестов.
- Добавить `tests/integration/test_postgres.py`.

### 4.2. Frontend tests
- Vitest для unit.
- Playwright для E2E (хотя бы smoke: login/dashboard/CRUD workflow).

### 4.3. Integration tests
- `docker compose -f docker-compose.test.yml up --abort-on-container-exit`.

---

## 5. Порядок выполнения

1. **P0. Postgres + session.py + Pydantic Settings.**
2. **P0. Docker Compose + Dockerfile + автоматические Alembic-миграции.**
3. **P0. Перевод UI/API на SQLAlchemy-сервисы, удаление legacy WorkflowDB.**
4. **P0. React + Vite + TS scaffold, Tailwind, API client.**
5. **P0. Backend: убрать HTML-роуты, оставить JSON API, добавить CORS и StaticFiles для dist.**
6. **P0. React страницы Dashboard/Workflows/Phases/Projects/Tasks.**
7. **P1. React страницы Agents/Skills/Settings, drag-and-drop, toasts, фильтры.**
8. **P1. Postgres-интеграционные тесты + frontend unit-тесты.**
9. **P2. Production docker-compose, README-скриншоты, CI-заготовка.**

---

## 6. Что не делаем

- Не добавляем CLI-команды (freeze: только `step` и `history`).
- Не разбиваем базу на несколько схем.
- Не остаёмся на Jinja2/HTMX для сложного UI.
- Не добавляем Kubernetes / метрики / CI/CD в этот план.

---

## 7. Итоговая архитектура

```
┌─────────────────┐
│  React + Vite   │
│   frontend/     │
└────────┬────────┘
         │ /api/*
         ▼
┌─────────────────┐
│   FastAPI app   │
│ project_workflow│
│   .ui/routes    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ SQLAlchemy +    │
│ Alembic         │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    Postgres     │
│  project_workflow
│   schema: pw    │
└─────────────────┘
```

Единственная ручная команда разработчика: `docker compose up --build`.
