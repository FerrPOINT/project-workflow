<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&height=180&text=workflow-cli&desc=State-driven%20workflow%20engine&color=gradient&customColorList=0,2,2,5,30" alt="workflow-cli banner" />
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

**workflow-cli** — это пофазовый движок задач с жёстким контролем переходов.
Каждая задача проходит по заранее определённому workflow из фаз с инструкциями, чек-листами и артефактами.
CLI агент отчитывается текстом — supervisor оценивает отчёт и решает: PASS, ROLLBACK или BLOCK.
Всё управление workflow-шаблонами, фазами, проектами и агентами делается через веб-UI.

---

<a name="features"></a>
## ✨ Features

| Feature | Описание |
|---------|----------|
| **Жёсткий пофазовый workflow** | Каждая задача привязана к workflow; переходы контролируются `WizardEngine` + `PhaseFSM`. |
| **Двухкомандный CLI** | Только `step` и `history`. JSON-режим для автоматизации. |
| **Web UI** | 11 страниц: dashboard, phases, projects, workflows, agents, tasks, settings, skills. |
| **JSON API** | 23 endpoint для CRUD фаз, workflow, проектов, агентов и задач. |
| **TaskKeyValidator** | Валидация ключей задач по настраиваемым regex из `projects.key_patterns`. |
| **SMART evaluate** | Опциональная LLM-оценка отчёта (Ollama Cloud / local) с fallback на rule-based. |
| **Слои Clean Architecture** | `domain/` → `application/` → `infrastructure/` → `workflow_cli/ui/` / `cli/`. |
| **SQLite + Alembic** | Миграции, SQLAlchemy repositories, единый `WorkflowService` / `PhaseServiceApp`. |

---

<a name="cli"></a>
## 🖥️ CLI

> **Правило проекта:** в CLI ровно две команды — `step` и `history`.
> CRUD workflows / phases / projects / agents и администрирование выполняются через Web UI.
> Подробный план рефакторинга: [`docs/plans/2026-06-21-refactor-roadmap.md`](docs/plans/2026-06-21-refactor-roadmap.md).

### Установка

```bash
git clone https://github.com/FerrPOINT/project-workflow-cli.git
cd project-workflow-cli
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ui]"
```

### step

Показать текущую фазу или подать отчёт и перейти дальше:

```bash
workflow-cli step --task TASK-42
workflow-cli step --task TASK-42 --report "сделал X, проверил Y"
```

### history

История отчётов, переходов и статусов по задаче:

```bash
workflow-cli history --task TASK-42
workflow-cli history --task TASK-42 --n 50
```

### JSON-режим

```bash
workflow-cli --json step --task TASK-42 --report "..."
```

---

<a name="ui"></a>
## 🌐 Web UI

Запуск через systemd:

```bash
systemctl restart wartz-ui.service
```

Или вручную для разработки:

```bash
python -m workflow_cli.ui --host 0.0.0.0 --port 8811
```

### Страницы

| Страница | URL | Что делает |
|----------|-----|-----------|
| Dashboard | `/` | Сводка по задачам, фазам, агентам |
| Phases | `/phases` | Список фаз + порядок |
| Phase detail | `/phase/{phase_id}` | Инструкции, чеки, эвиденс |
| Tasks | `/tasks` | Список задач |
| Task detail | `/task/{task_key}` | История и текущая фаза |
| Projects | `/projects` | CRUD проектов + key patterns |
| Workflows | `/workflows` | CRUD workflow-шаблонов |
| Agents | `/agents` | CRUD агентов |
| Skills | `/skills` | Справочник скиллов |
| Settings | `/settings` | Read-only реестр CLI-команд |

### API

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/api/workflows` | GET / POST | Список / создание workflow |
| `/api/workflows/{id}` | PUT / DELETE | Обновление / удаление workflow |
| `/api/phases` | GET / POST | Список / создание фазы |
| `/api/phases/{id}` | GET / PUT / DELETE | Детали / обновление / удаление фазы |
| `/api/phases/order` | PUT | Изменение порядка фаз |
| `/api/projects` | GET / POST / PUT / DELETE | CRUD проектов |
| `/api/agents` | GET / POST / PUT / DELETE | CRUD агентов |
| `/api/tasks` | GET | Список задач |
| `/api/tasks/{task_key}` | GET | Детали задачи |
| `/api/skills` | GET | Каталог скиллов |
| `/api/settings` | GET | Настройки и CLI-реестр |

---

<a name="architecture"></a>
## 🏗️ Architecture

```mermaid
flowchart TD
    subgraph CLI["🖥️ CLI"]
        step[step]
        history[history]
    end

    subgraph UI["🌐 Web UI"]
        pages[HTML pages]
        api[JSON API]
    end

    subgraph App["application/"]
        ws[WorkflowService]
        ps[PhaseServiceApp]
        prs[ProjectService]
        ts[TaskService]
        ags[AgentService]
    end

    subgraph Domain["domain/"]
        models[Models + Repository interfaces]
    end

    subgraph Infra["infrastructure/db/"]
        sa[SQLAlchemy models]
        repo[Repositories]
        alembic[Alembic migrations]
    end

    subgraph Legacy["legacy db/"]
        wdb[WorkflowDB — в процессе миграции]
    end

    CLI -->|wizard| App
    UI -->|routes| App
    App --> Domain
    Domain -->|implemented by| Infra
    App -.->|ещё используется| Legacy
```

### Принципы

- **Application services** — единая точка входа для бизнес-логики.
- **Domain** не зависит от SQLAlchemy; `infrastructure/db/repositories.py` реализует интерфейсы из `domain/repositories.py`.
- **UI routes** только валидируют входные данные, вызывают сервисы и формируют ответ.
- **Raw SQL** допустим только в Alembic-миграциях.
- **Seed/sync default workflow** — явная операция, не side-effect при каждом запросе.

---

<a name="workflow"></a>
## 🔄 Жизненный цикл задачи

```mermaid
flowchart LR
    A[Создание задачи] --> B{Определить workflow}
    B --> C[Текущая фаза]
    C --> D[Агент выполняет инструкции]
    D --> E[Отчёт через CLI step]
    E --> F{Supervisor evaluate}
    F -->|PASS| G[Следующая фаза]
    F -->|ROLLBACK| H[Предыдущая фаза]
    F -->|BLOCK| I[Блокировка задачи]
    G --> C
    H --> C
```

---

<a name="quality"></a>
## 🛡️ Quality Bar

| Контроль | Текущее состояние | Цель |
|----------|-------------------|------|
| Tests | **727 passed** | зелёный full suite |
| Lint | **ruff green** | сохранять green |
| Type check UI | **mypy workflow_cli/ui/ green** | mypy по всему `workflow_cli/` |
| Coverage | не измерялась | ≥ 90% |
| Raw SQL в production | 1 endpoint + legacy `db/base.py` | 0 вне миграций |

---

<a name="roadmap"></a>
## 🗺️ Roadmap

Подробный план: [`docs/plans/2026-06-21-refactor-roadmap.md`](docs/plans/2026-06-21-refactor-roadmap.md).

- [x] Разбить монолит `ui.py` на пакет `workflow_cli/ui/`
- [x] Внедрить Pydantic-схемы для API inputs
- [x] Добавить `workflow_cli/ui/__main__.py` для systemd
- [x] Довести `mypy workflow_cli/ui/` до зелёного
- [ ] Перевести UI routes с legacy `WorkflowDB` на application services
- [ ] Дополнить application services до полного CRUD
- [ ] Удалить / сузить `WorkflowDB` до Alembic-миграций
- [ ] Типизировать `wizard.py` и декомпозировать логику
- [ ] Добиться `mypy workflow_cli/ --ignore-missing-imports` green

---

## 📫 Links

<p align="center">
  <a href="https://github.com/FerrPOINT/project-workflow-cli"><img src="https://img.shields.io/badge/GitHub-100000?style=for-the-badge&logo=github&logoColor=white" /></a>
</p>

---

<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&height=100&section=footer&color=gradient&customColorList=0,2,2,5,30" alt="footer" />
</p>
