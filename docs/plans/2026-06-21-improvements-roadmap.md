# План доработки project-workflow

> Статус: план, а не задачи на прямо сейчас. Приоритеты: P0 — обязательно, P1 — сразу после P0, P2 — когда стабилизируется ядро.

---

## 1. Postgres + схема `project_workflow` + Docker Compose

### 1.1. Цель
- Уйти от SQLite в runtime.
- Иметь единую базу `project_workflow` и единственную схему `project_workflow`.
- Локальный запуск и dev-окружение через `docker compose up`.

### 1.2. Почему именно так
- SQLite не масштабируется на concurrent writes и нельзя подключить из нескольких процессов без WAL-ограничений.
- Для одного монолитного приложения мульти-схемность — лишняя сложность. Всё в одной схеме `project_workflow`.
- `docker compose` — единственный источник правды про dev-окружение: Postgres, app, миграции.

### 1.3. Задачи

#### P0. Перевод SQLAlchemy на Postgres
- **Добавить драйвер** в `pyproject.toml`: `psycopg[binary]>=3.1`.
- **Обновить `project_workflow/infrastructure/db/session.py`**:
  - Убрать SQLite-specific `PRAGMA` event listener (либо вынести в отдельный адаптер для SQLite-only тестового режима).
  - Читать DSN из `DATABASE_URL` (или `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`).
  - Для Postgres: `create_engine(url, pool_pre_ping=True)`.
  - Для SQLite: `create_engine("sqlite:///...", connect_args={"check_same_thread": False})` — оставить как fallback для тестов.
- **Обновить все Alembic-модели** (`infrastructure/db/models.py`):
  - Убедиться, что внешние ключи и ON DELETE заданы явно.
  - Перевести `String` колонки с разумными длинами.
  - Добавить `DateTime(timezone=True)` вместо строковых timestamp-ов, если они ещё строковые.
- **Добавить схему**:
  - `search_path` через `connect_args={"options": "-csearch_path=project_workflow"}` или явное `CREATE SCHEMA IF NOT EXISTS project_workflow`.
  - В Alembic `env.py` — `context.configure(..., version_table_schema="project_workflow")`.
- **Удалить legacy `WorkflowDB`** (`project_workflow/db/base.py`) поэтапно:
  1. Переписать все вызовы из UI/API/application сервисов на SQLAlchemy-сервисы.
  2. Удалить файл и тесты, которые тестируют legacy DB API.
  3. Удалить модуль `project_workflow/db/`.

#### P0. Docker Compose
- **Создать `docker-compose.yml`**:
  - `postgres:16-alpine`:
    - база `project_workflow`
    - схема `project_workflow`
    - пользователь `project_workflow`
    - пароль из `.env`
    - volume `project_workflow_postgres_data`
    - healthcheck через `pg_isready`
  - `migration` (init контейнер):
    - build: `Dockerfile`
    - команда: `alembic upgrade head`
    - зависимость от healthcheck Postgres
  - `app`:
    - build: `Dockerfile`
    - команда: `python -m project_workflow.ui ...`
    - порты: `8811:8811`
    - зависимость от `migration`
- **Создать `Dockerfile`**:
  - multistage или single-stage Python 3.11 slim
  - install `psycopg[binary]`
  - не копировать `tests/`, `.venv/`, `__pycache__/`, `.git/`
- **Создать `.env.example`** с переменными:
  ```
  DATABASE_URL=postgresql+psycopg://project_workflow:project_workflow@postgres:5432/project_workflow?options=-csearch_path=project_workflow
  DB_HOST=postgres
  DB_PORT=5432
  DB_NAME=project_workflow
  DB_USER=project_workflow
  DB_PASSWORD=project_workflow
  DB_SCHEMA=project_workflow
  ```
- **Обновить `README.md`**:
  - `docker compose up --build` как основной способ запуска.
  - SQLite — только для тестов и fallback.

#### P1. Миграции
- Сгенерировать новую Alembic-миграцию на базе актуальных `infrastructure/db/models.py`.
- В `docker-compose.yml` сделать `migration` сервис обязательным для запуска `app`.
- Проверить downgrade/upgrade цикл.
- В CI (если появится) — `alembic upgrade head && alembic downgrade base`.

### 1.4. Чек-лист готовности
- [ ] `docker compose up --build` поднимает Postgres, прогоняет миграции и отдаёт `200` на `localhost:8811`.
- [ ] Все существующие 727 тестов проходят (SQLite-режим остаётся для тестов).
- [ ] Нет прямого SQL из `project_workflow/db/base.py`.
- [ ] `DATABASE_URL` — единственный способ указать DB для runtime.

---

## 2. Production-ready UI (server-side, без React/Vue)

### 2.1. Почему не отдельный frontend
- Проект small-to-medium.
- SSR на Jinja2 + HTMX даёт production-ready UI без JS-билда, Webpack и отдельной команды.
- CLI freeze и скорость разработки важнее SPA-перехода.

### 2.2. Проблемы, которые надо закрыть
- GitHub отображает репозиторий как "HTML" — это нормально для SSR, но выглядит неадекватно без структуры и документации.
- Сейчас страницы — монолитные HTML-шаблоны с inline-стилями и повторяющейся вёрсткой.
- Нет компонентной системы, нет минификации, нет кеширования.

### 2.3. Задачи

#### P0. Структура UI
- **Вынести общие компоненты** в `project_workflow/templates/components/`:
  - `sidebar.html`
  - `header.html`
  - `card.html`
  - `toast.html`
  - `form_field.html`
- **Вынести макросы Jinja2** в `project_workflow/templates/macros/`:
  - `forms.j2`, `tables.j2`, `badges.j2`.
- **Переписать все страницы** на `{% extends "base.html" %}` + `{% include "components/..." %}`.

#### P0. CSS-система
- **Заменить inline-стили** на CSS-переменные и классы.
- **Добавить единый CSS-файл** `project_workflow/static/css/project-workflow.css`.
- **Определить design tokens**:
  - цвета (primary `#8B3A3A`, surface, background, text)
  - spacing scale
  - типографика
  - breakpoints
- **Подключить `static/` к FastAPI** через `StaticFiles`.

#### P1. HTMX
- **Добавить HTMX** через CDN или vendored bundle.
- **Перевести формы** на `hx-post`/`hx-put`/`hx-delete` с `hx-target`.
- **Добавить optimistic updates** для создания/удаления фаз, задач, проектов.
- **Добавить `hx-indicator`** для loading-состояний.

#### P1. UI/UX-доработки
- **Страница `/settings`**:
  - форма подключения Postgres (DSN) — только dev/local, не production secrets.
  - каталог key patterns для валидации task keys.
  - skills mapping.
- **Страница `/phases`**:
  - drag-and-drop для reordering фаз.
  - inline-редактирование инструкций.
- **Страница `/tasks`**:
  - фильтры по project/status/current_phase.
  - кнопка "открыть task detail".
- **Глобальный поиск** по task key / project code / workflow name.
- **Toast-уведомления** после операций.

#### P2. Frontend-документация
- `docs/ui/components.md` — список компонентов и примеры использования.
- `docs/ui/css-tokens.md` — дизайн-токены.
- Обновить `README.md`, чтобы раздел "Web UI" выглядел как полноценная часть, а не "просто HTML".

### 2.4. Чек-лист готовности
- [ ] Все inline-стили удалены.
- [ ] Есть `components/` и `macros/`.
- [ ] HTMX подключён и используется хотя бы в 3 формах.
- [ ] Страница настроек позволяет менять key patterns и skills mapping.
- [ ] README явно описывает UI-стек и показывает скриншоты.

---

## 3. Конфигурация и окружение

### 3.1. P0. Единый config
- Перевести `project_workflow/config.py` на Pydantic Settings.
- Поддерживаемые переменные:
  ```python
  DATABASE_URL: PostgresDsn
  DB_SCHEMA: str = "project_workflow"
  UI_HOST: str = "0.0.0.0"
  UI_PORT: int = 8811
  LOG_LEVEL: str = "INFO"
  ```
- Валидация при старте: если `DATABASE_URL` невалидный — падать с понятной ошибкой.

### 3.2. P1. Убрать env-зоопарк
- Заменить `WORKFLOW_DB_PATH`, `WORKFLOW_DIR`, `WORKFLOW_UI_PORT`, `WORKFLOW_UI_HOST` на единые `DATABASE_URL`, `UI_HOST`, `UI_PORT`.
- Обновить systemd-сервис (`/etc/systemd/system/project-workflow-ui.service`) на `Environment="DATABASE_URL=..."`.

---

## 4. Тестирование под Postgres

### 4.1. P1. Integration tests against Postgres
- Добавить `tests/integration/test_postgres.py`.
- Использовать `pytest-postgresql` или testcontainers.
- Проверить миграции up/down, CRUD операции, constraints.

### 4.2. P1. Тесты UI на реальном сервере
- Добавить Playwright-тесты или хотя бы `httpx`-based integration tests для всех UI routes.

### 4.3. P2. Нагрузочные тесты
- Проверить concurrent `project-workflow step` под Postgres.

---

## 5. Порядок выполнения

1. **P0. Postgres + session.py** — база под приложением.
2. **P0. Docker Compose + Dockerfile + .env.example** — единый способ запуска.
3. **P0. Alembic-миграция на Postgres** — схема `project_workflow` создана правильно.
4. **P0. Перевести UI/API на SQLAlchemy-сервисы** — удалить `WorkflowDB`.
5. **P0. Структурировать UI-шаблоны и CSS** — компоненты, макросы, design tokens.
6. **P1. HTMX + UI/UX-доработки**.
7. **P1. Pydantic Settings** — унифицировать конфиг.
8. **P1. Postgres-интеграционные тесты**.
9. **P2. Документация UI + README-скриншоты**.

---

## 6. Что явно НЕ делаем

- Не добавляем новые CLI-команды (freeze: только `step` и `history`).
- Не переходим на React/Vue/отдельный SPA — остаёмся на SSR + HTMX.
- Не разбиваем базу на несколько схем.
- Не добавляем Kubernetes / CI/CD / метрики в этот план.
