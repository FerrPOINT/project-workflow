<p align="center">
  <h1 align="center">project-workflow</h1>
</p>

<p align="center">
  Пофазовый движок управления задачами с CLI supervisor-вердиктами и Web UI.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Postgres-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="Postgres" />
  <img src="https://img.shields.io/badge/SQLAlchemy-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white" alt="SQLAlchemy" />
  <img src="https://img.shields.io/badge/pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white" alt="pytest" />
  <img src="https://img.shields.io/badge/ruff-261230?style=flat-square&logo=ruff&logoColor=white" alt="ruff" />
  <img src="https://img.shields.io/badge/mypy-2E6AFF?style=flat-square&logo=mypy&logoColor=white" alt="mypy" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License MIT" />
</p>

---

## Позиционирование

**project-workflow** — пофазовый движок управления задачами.
Агент отчитывается через CLI, встроенный supervisor оценивает отчёт и выдаёт вердикт: **PASS**, **ROLLBACK** или **BLOCK**.
Всё управление шаблонами workflow, фазами, проектами, агентами и задачами ведётся через Web UI.

CLI остаётся минимальным: ровно две команды — `step` и `history`.

В production используется **PostgreSQL**.

SQLite остаётся только для тестов (временные файлы, monkeypatch `DATABASE_URL`).

## Features

| Feature | Описание |
|---------|----------|
| Пофазовый workflow | Каждая задача строго следует шаблону фаз с инструкциями, чек-листами и артефактами. |
| Встроенный supervisor | Автоматическая оценка отчётов и решение о переходе на следующую фазу. |
| Web UI | Управление шаблонами, фазами, проектами, задачами и агентами через браузер. |
| CLI freeze | Только `step` и `history`; весь CRUD — через UI. |
| PostgreSQL | Единый production-стек: systemd UI и CLI используют тот же Postgres через `DATABASE_URL`. |
| Автоматические миграции | `docker compose up` сам создаёт схему, таблицы и baseline. |

## Core Stack

| Zone | Tech | Роль |
|------|------|------|
| Runtime | Python 3.11 | основной язык |
| Data | PostgreSQL | production БД |
| ORM & migrations | SQLAlchemy 2 + Alembic | модели, репозитории, UoW, миграции |
| API | FastAPI + Pydantic | UI и JSON API |
| UI | Jinja2 + minimal JS | server-side HTML, без frontend-фреймворков |
| CLI | Click + Rich | `step` / `history` |
| Config | Pydantic Settings | `.env`, переменные окружения |

## CLI

```bash
# Выполнить текущую фазу задачи и получить вердикт supervisor
project-workflow step --task TASK-123 --report "Сделал X, проверил Y"

# История фаз и supervisor-решений
project-workflow history --task TASK-123 --n 10
```

CLI ожидает переменную окружения `DATABASE_URL`:

```bash
export DATABASE_URL=postgresql+psycopg://project_workflow:project_workflow@localhost/project_workflow
```

## Web UI

Web UI работает в двух режимах:

- **systemd-сервис** `project-workflow-ui.service` — production UI на `http://localhost:8811` (Postgres Docker).
- **Docker Compose** — UI на `http://localhost:8812` (тот же Postgres).

Запуск через Docker Compose:

```bash
cp .env.example .env
docker compose up --build -d
# UI доступен на http://localhost:8812
```

Переключение systemd UI на Postgres:

```bash
sudo systemctl daemon-reload
sudo systemctl restart project-workflow-ui.service
```

При старте автоматически создаётся схема `project_workflow`, таблицы и baseline-версия Alembic.

Перенос данных SQLite → Postgres:

```bash
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db \
  python scripts/migrate_sqlite_to_postgres.py /path/to/workflow.db
```

## Architecture

```mermaid
flowchart TD
    CLI[CLI project-workflow] -->|step / history| WE[WizardEngine]
    UI[Web UI FastAPI+Jinja2] -->|CRUD / HTML| API[API routes]
    API -->|UoW| Repo[SQLAlchemy Repositories]
    WE --> Repo
    Repo --> DB[(PostgreSQL)]
    WE --> SV[Supervisor / LLM checks]
    SV -->|verdict| WE
    Seed[schema.py seed loader] --> DB
```

### Принципы

- Единый data layer: все операции через SQLAlchemy-модели и репозитории.
- UI-пакет (`project_workflow/ui/`) — чистое FastAPI-приложение с отдельными routes, services, dependencies.
- `project_workflow/db/compat.py` — SQLAlchemy-реализация `WorkflowDB`, сохраняющая публичный API для CLI/wizard/tests.
- Конфигурация централизована в `project_workflow.config` на Pydantic Settings; `DATABASE_URL` обязателен.

## 🛡️ Quality Bar

| Проверка | Команда | Статус |
|---|---|---|
| Lint | `ruff check .` | **green** |
| Type check | `mypy project_workflow` | **green** |
| Tests | `pytest -q --tb=short` | **643 passed** |
| Docker UI health | `curl http://localhost:8812/` | **200** |
| Systemd UI health | `curl http://localhost:8811/` | **200** |

## Roadmap

- [x] Конфигурация на Pydantic Settings (`DATABASE_URL` required)
- [x] SQLAlchemy-модели, репозитории и unit-of-work
- [x] Alembic-миграции + `scripts/init_db.py` для автоматического baseline
- [x] Docker Compose: Postgres + migrate + UI
- [x] UI/API переведены на SQLAlchemy-сервисы
- [x] `WorkflowDB` переписан на SQLAlchemy, `db/base.py` и `db_schema.sql` удалены
- [x] mypy green, ruff green, 643 теста green
- [ ] Postgres-интеграционные тесты
- [ ] Разделение `wizard.py` на доменные application-сервисы
- [ ] API-тесты на все UI routes

Подробный план: [`docs/plans/2026-06-21-detailed-roadmap.md`](docs/plans/2026-06-21-detailed-roadmap.md).

## Установка

```bash
git clone https://github.com/FerrPOINT/project-workflow.git
cd project-workflow
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ui]"
```

## License

MIT

