# project-workflow — текущее состояние (2026-06-26)

## Стек

- Python 3.11, FastAPI, Jinja2, SQLAlchemy 2.0 ORM, PostgreSQL 15 (localhost).
- Тесты: pytest 8.x, SQLite fallback only в тестовых фикстурах, runtime SQLite удалён.
- Ruff (lint), mypy (type check), pytest --forked (из-за FD exhaustion под xdist).

## Архитектура

```
project_workflow/
├── config.py               # Pydantic Settings, DATABASE_URL
├── domain/                 # entities, fsm, validation, repositories (abstract)
├── application/            # сервисы: project, task, phase, agent, workflow
├── infrastructure/db/      # SQLAlchemy models, repositories, UoW, session
├── interfaces/
│   ├── cli/                # click CLI
│   └── ui/                 # FastAPI + Jinja2 UI
└── wizard/                 # LLM/rule-based supervisor
```

## Что сделано (2026-06-26)

- [x] Legacy `WorkflowDB`/`db/base.py` удалены; runtime только PostgreSQL.
- [x] Delete API: `DELETE /api/tasks/{task_key}`, `DELETE /api/projects/{project_id}` с каскадом.
- [x] Broad `except Exception` сужены до ожидаемых исключений + логирование.
- [x] `wizard/core.py` без side-effect печати; CLI `ui.py` единый формат + `--json`.
- [x] `scripts/migrate_sqlite_to_postgres.py` заархивирован.
- [x] UI polish: execution_type на отдельной строке, склонение счётчиков, `/instructions` роут.
- [x] Request logging middleware, `/health` с db_latency_ms.
- [x] README/AGENTS.md синхронизированы с реальными цифрами.

## Метрики

- Тесты: `869 passed, 6 deselected` (`pytest --forked`).
- Ruff: All checks passed!
- mypy: Success: no issues found in 57 source files.
- UI health: `http://localhost:8811/health` → 200.

## Ближайшие направления (не приоритет)

- Docker Compose/бойлерплейт для новых разработчиков.
- Структурный логгер в формате JSON для прод-сборки.
- Маркеры pytest для быстрого запуска (unit/ui/wizard).
