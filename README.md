<p align="center">
  <img src="docs/assets/project-workflow-banner.jpg" alt="project-workflow banner" />
</p>

<p align="center">
  <a href="#features"><img src="https://img.shields.io/badge/✨%20Features-0B1220?style=for-the-badge" /></a>
  <a href="#cli"><img src="https://img.shields.io/badge/🖥️%20CLI-111827?style=for-the-badge" /></a>
  <a href="#ui"><img src="https://img.shields.io/badge/🌐%20Web%20UI-1F2937?style=for-the-badge" /></a>
  <a href="#architecture"><img src="https://img.shields.io/badge/🏗️%20Architecture-374151?style=for-the-badge" /></a>
  <a href="#quality"><img src="https://img.shields.io/badge/🛡️%20Quality-4B5563?style=for-the-badge" /></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/SQLAlchemy-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white" alt="SQLAlchemy" />
  <img src="https://img.shields.io/badge/Pydantic-E92063?style=flat-square&logo=pydantic&logoColor=white" alt="Pydantic" />
  <img src="https://img.shields.io/badge/Click-yellow?style=flat-square&logo=clickhouse&logoColor=white" alt="Click" />
  <img src="https://img.shields.io/badge/Rich-000000?style=flat-square&logo=rich&logoColor=white" alt="Rich" />
  <img src="https://img.shields.io/badge/Jinja2-B41717?style=flat-square&logo=jinja&logoColor=white" alt="Jinja2" />
  <img src="https://img.shields.io/badge/Alembic-6B8E23?style=flat-square&logo=alembic&logoColor=white" alt="Alembic" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white" alt="pytest" />
  <img src="https://img.shields.io/badge/ruff-261230?style=flat-square&logo=ruff&logoColor=white" alt="ruff" />
  <img src="https://img.shields.io/badge/mypy-2E6AFF?style=flat-square&logo=mypy&logoColor=white" alt="mypy" />
</p>

---

## Позиционирование

**project-workflow** — это пофазовая платформа управления задачами.
В ядре — жёсткий контроль переходов между фазами: агент отчитывается через CLI, встроенный supervisor оценивает отчёт и решает PASS / ROLLBACK / BLOCK.
Всё управление workflow-шаблонами, фазами, проектами и агентами ведётся через Web UI.

CLI-часть платформы остаётся максимально узкой: ровно две команды — `step` и `history`.

## Features

- **Пофазовый workflow** — каждая задача строго следует шаблону фаз с инструкциями, чек-листами и артефактами.
- **Встроенный supervisor** — автоматическая оценка отчётов и решение о переходе.
- **Web UI** — управление шаблонами, фазами, проектами, задачами и агентами.
- **CLI freeze** — только `step` и `history`; всё остальное через UI.
- **Лёгкий деплой** — SQLite + FastAPI, можно запустить локально или как systemd-сервис.
- **Расширяемые skills** — каталог Hermes-скиллов для фаз.

## CLI

```bash
# Запуск рабочей фазы задачи
project-workflow step --task TASK-123 --report "Сделал X, проверил Y"

# История фаз и supervisor-решений
project-workflow history --task TASK-123 --n 10
```

## Web UI

```bash
python -m project_workflow.ui --host 0.0.0.0 --port 8811
```

Или через systemd:

```bash
systemctl enable project-workflow-ui.service
systemctl start project-workflow-ui.service
```

## Architecture

```mermaid
flowchart LR
    A[CLI project-workflow] -- step / history --> B[WizardEngine]
    B -- read/write --> C[(SQLite)]
    D[Web UI] -- CRUD --> C
    B -- supervisor --> E[LLM / rule checks]
    E -- verdict --> B
```

## Quality

| Проверка | Команда | Статус |
|---|---|---|
| Lint | `python -m ruff check project_workflow/ tests/` | green |
| UI type-check | `python -m mypy project_workflow/ui/ --ignore-missing-imports` | green |
| Tests | `pytest -q --tb=short` | **727 passed** |

## Установка

```bash
git clone https://github.com/FerrPOINT/project-workflow.git
cd project-workflow
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ui]"
```

## Архитектура и ограничения

- CLI заморожен: ровно две команды — `step` и `history`. Весь CRUD workflows/phases/projects/agents и администрирование выполняется через Web UI.
- UI-пакет (`project_workflow/ui/`) — чистый FastAPI-приложение с Pydantic-схемами, отдельными routes/services/dependencies.
- Data layer в стадии рефакторинга: legacy `WorkflowDB` (`project_workflow/db/base.py`) соседствует с SQLAlchemy-сервисами; план миграции — в `docs/plans/2026-06-21-refactor-roadmap.md`.
- CI/CD, Docker, health-checks и метрики вне скоупа.

## Roadmap

Краткая версия:

1. Убрать двойной data layer — весь raw SQLite уйдёт в SQLAlchemy services.
2. Выполнить Pydantic + mypy-чистку вне UI.
3. Разделить `wizard.py` на доменные сервисы.
4. Добавить API-тесты на все UI routes.

Подробный план: [`docs/plans/2026-06-21-refactor-roadmap.md`](docs/plans/2026-06-21-refactor-roadmap.md).

## License

MIT

<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&height=100&section=footer&color=8B3A3A" alt="footer" />
</p>
