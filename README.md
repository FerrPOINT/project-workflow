<p align="center">
  <img src="docs/assets/project-workflow-banner.jpg" alt="project-workflow banner" />
</p>

<p align="center">
  <a href="#features"><img src="https://img.shields.io/badge/%E2%9C%A8%20Features-0B1220?style=for-the-badge" /></a>
  <a href="#stack"><img src="https://img.shields.io/badge/%F0%9F%94%A7%20Stack-111827?style=for-the-badge" /></a>
  <a href="#cli"><img src="https://img.shields.io/badge/%F0%9F%96%A5%EF%B8%8F%20CLI-1F2937?style=for-the-badge" /></a>
  <a href="#ui"><img src="https://img.shields.io/badge/%F0%9F%8C%90%20Web%20UI-374151?style=for-the-badge" /></a>
  <a href="#architecture"><img src="https://img.shields.io/badge/%F0%9F%8F%97%EF%B8%8F%20Architecture-4B5563?style=for-the-badge" /></a>
  <a href="#quality"><img src="https://img.shields.io/badge/%F0%9F%9B%A1%EF%B8%8F%20Quality-6B7280?style=for-the-badge" /></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Postgres-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="Postgres" />
  <img src="https://img.shields.io/badge/SQLAlchemy-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white" alt="SQLAlchemy" />
  <img src="https://img.shields.io/badge/Pydantic-E92063?style=flat-square&logo=pydantic&logoColor=white" alt="Pydantic" />
  <img src="https://img.shields.io/badge/uv-000000?style=flat-square&logo=astral&logoColor=white" alt="uv" />
  <img src="https://img.shields.io/badge/Rich-000000?style=flat-square&logo=rich&logoColor=white" alt="Rich" />
  <img src="https://img.shields.io/badge/Jinja2-B41717?style=flat-square&logo=jinja&logoColor=white" alt="Jinja2" />
  <img src="https://img.shields.io/badge/Alembic-6B8E23?style=flat-square&logo=alembic&logoColor=white" alt="Alembic" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white" alt="pytest" />
  <img src="https://img.shields.io/badge/ruff-261230?style=flat-square&logo=ruff&logoColor=white" alt="ruff" />
  <img src="https://img.shields.io/badge/mypy-2E6AFF?style=flat-square&logo=mypy&logoColor=white" alt="mypy" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License MIT" />
</p>

---

## Позиционирование

Пофазовый движок управления задачами.
Агент отчитывается через CLI, встроенный supervisor оценивает отчёт и выдаёт вердикт: **PASS**, **ROLLBACK** или **BLOCK**.
Всё управление шаблонами workflow, фазами, проектами, агентами и задачами ведётся через Web UI.

CLI остаётся минимальным: ровно две команды — `step` и `history`.

В production используется **PostgreSQL**.

SQLite остаётся только для тестов (временные файлы, monkeypatch `DATABASE_URL`).

<a name="features"></a>
## ✨ Features

| Feature | Описание |
|---------|----------|
| Пофазовый workflow | Каждая задача строго следует шаблону фаз с инструкциями, чек-листами и артефактами. |
| Встроенный supervisor | Автоматическая оценка отчётов и решение о переходе на следующую фазу. |
| Web UI | Управление шаблонами, фазами, проектами, задачами и агентами через браузер. |
| CLI freeze | Только `step` и `history`; весь CRUD — через UI. |
| PostgreSQL | Единый production-стек: systemd UI и CLI используют тот же Postgres через `DATABASE_URL`. |
| Автоматические миграции | `docker compose up` сам создаёт схему, таблицы и baseline. |

<a name="stack"></a>
## 🔧 Core Stack

| Zone | Tech | Роль |
|------|------|------|
| Runtime | Python 3.11 | основной язык |
| Data | PostgreSQL | production БД |
| ORM & migrations | SQLAlchemy 2 + Alembic | модели, репозитории, UoW, миграции |
| API | FastAPI + Pydantic | UI и JSON API |
| UI | Jinja2 + minimal JS | server-side HTML, без frontend-фреймворков |
| CLI | Click + Rich | `step` / `history` |
| Config | Pydantic Settings | `.env`, переменные окружения |

<a name="cli"></a>
## 🖥️ CLI

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

<a name="ui"></a>
## 🌐 Web UI

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

<a name="architecture"></a>
## 🏗️ Architecture

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

<a name="quality"></a>
## 🛡️ Quality Bar

| Проверка | Команда | Статус |
|---|---|---|
| Lint | `ruff check .` | **green** |
| Type check | `mypy project_workflow` | **green** |
| Tests | `pytest -q --tb=short` | **643 passed** |
| Docker UI health | `curl http://localhost:8812/` | **200** |
| Systemd UI health | `curl http://localhost:8811/` | **200** |

<a name="roadmap"></a>
## 🗺️ Roadmap

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


