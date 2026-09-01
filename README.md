<p align="center">
  <img src="docs/assets/project-workflow-banner.jpg" alt="project-workflow banner" />
</p>

<p align="center">
  <a href="#features"><img src="https://img.shields.io/badge/%E2%9C%A8%20Features-0B1220?style=for-the-badge" alt="Features" /></a>
  <a href="#stack"><img src="https://img.shields.io/badge/%F0%9F%94%A7%20Stack-111827?style=for-the-badge" alt="Stack" /></a>
  <a href="#entrypoints"><img src="https://img.shields.io/badge/%F0%9F%A7%A9%20Entry%20Points-18202F?style=for-the-badge" alt="Entry Points" /></a>
  <a href="#cli"><img src="https://img.shields.io/badge/%F0%9F%96%A5%EF%B8%8F%20CLI-1F2937?style=for-the-badge" alt="CLI" /></a>
  <a href="#ui"><img src="https://img.shields.io/badge/%F0%9F%8C%90%20Web%20UI-374151?style=for-the-badge" alt="Web UI" /></a>
  <a href="#screenshots"><img src="https://img.shields.io/badge/%F0%9F%96%BC%EF%B8%8F%20Screens-475569?style=for-the-badge" alt="Screenshots" /></a>
  <a href="#architecture"><img src="https://img.shields.io/badge/%F0%9F%8F%97%EF%B8%8F%20Architecture-4B5563?style=for-the-badge" alt="Architecture" /></a>
  <a href="#quality"><img src="https://img.shields.io/badge/%F0%9F%9B%A1%EF%B8%8F%20Quality-6B7280?style=for-the-badge" alt="Quality" /></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python" />
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
  <img src="https://img.shields.io/badge/source--available-FerrPOINT-111827?style=flat-square" alt="FerrPOINT source-available" />
</p>

---

## 🎯 Позиционирование

**project-workflow** — внутренняя private-платформа для пофазного ведения задач.
Агент отчитывается через CLI, обязательный LLM Supervisor проверяет отчет и выдает вердикт: **PASS**, **ROLLBACK** или **BLOCK**.

Центр управления workflow, фазами, namespaces, агентами и задачами живет в Web UI.
CLI намеренно остается маленьким: `step` и `history`; дополнительные namespace-команды работают как wrappers поверх этих двух операций.

Runtime-источник данных — **PostgreSQL**. SQLite используется только для изолированных тестов и локальных smoke-сценариев.

## 📌 Snapshot

| Поле | Значение |
|---|---|
| Статус | Internal `1.0.0` |
| Runtime | PostgreSQL + SQLAlchemy/Alembic |
| Docker UI/API | `http://127.0.0.1:8812` |
| App/systemd port | `8811` внутри приложения |
| CLI selector | `PROJECT_WORKFLOW_NAMESPACE_ID` |
| UI selector | cookie `workflow_namespace_id`, query override `?namespace_id=` |
| License | FerrPOINT Proprietary Source-Available Evaluation License v1.0 |

<a name="features"></a>
## ✨ Features

| Feature | Описание |
|---|---|
| Phase workflow | Задача идет по шаблону фаз с инструкциями, checks, evidence и audit history. |
| Supervisor gate | Переход фазы проходит через обязательную оценку отчета и фиксирует `PASS` / `ROLLBACK` / `BLOCK`. |
| Namespace runtime | Несколько entrypoints могут иметь свои workflow, задачи, стиль UI и CLI-команду. |
| Web UI | CRUD для workflows, phases, namespaces и agents; просмотр задач и audit history. |
| Append-only history | История фаз и `step`-проверок не затирается. |
| CLI freeze | Публичный CLI остается управляемым и предсказуемым: `step` / `history`. |
| Wrapper commands | `workflow-qa`, `workflow-dev` и другие команды генерируются из записей PostgreSQL. |
| Automatic baseline | `docker compose up` поднимает Postgres, применяет миграции и загружает стартовый каталог. |

<a name="stack"></a>
## 🔧 Core Stack

| Zone | Tech | Роль |
|---|---|---|
| Runtime | Python 3.10+ | application runtime and packaging target |
| Data | PostgreSQL | source of truth for UI, CLI and supervisor state |
| ORM | SQLAlchemy 2 | models, repositories, unit-of-work |
| Migrations | Alembic | schema history and baseline |
| API/UI | FastAPI + Jinja2 | server-side UI and JSON endpoints |
| Validation | Pydantic | settings, schemas and DTO boundaries |
| CLI | Click + Rich | compact agent-facing command surface |
| Tooling | uv + constraints.txt | repeatable local and container dependency set |
| Quality | pytest, ruff, mypy | local quality gate |

<a name="entrypoints"></a>
## 🧩 CLI Entry Points

Each namespace/entrypoint stores:

| Field | Role |
|---|---|
| Name and description | UI identity and human-facing purpose |
| Bound workflow | Phase template used by tasks in this entrypoint |
| Icon and theme color | Header, dashboard and task-detail styling |
| Custom CLI command | User-facing wrapper, for example `workflow-qa` |

The top UI selector switches logo/name, accent color, dashboard, task list, task detail and `/phases`.
The selected entrypoint is stored in cookie `workflow_namespace_id`; `?namespace_id=` has priority over the cookie.

Canonical API: `/api/namespaces`; old UI/API alias routes are not part of the public surface.

<a name="cli"></a>
## 🖥️ CLI

CLI expects `DATABASE_URL`:

```bash
export DATABASE_URL=postgresql+psycopg://project_workflow:project_workflow@localhost:5432/project_workflow
```

Run the current phase and receive the supervisor verdict:

```bash
project-workflow step --task RUN-123 --report "Сделал X, проверил Y"
```

Read phase and supervisor history:

```bash
project-workflow history --task RUN-123 --n 10
```

Generate namespace wrapper commands:

```bash
python scripts/install_namespace_clis.py --bin-dir ./.bin

workflow-qa step --task RUN-42 --report "Проверил сценарии"
workflow-dev history --task RUN-42
```

The wrapper sets `PROJECT_WORKFLOW_NAMESPACE_ID=<id>` and calls `project-workflow step/history`, so the same external task key can exist independently in different namespaces.
The executor receives the configured wrapper command in `phase_contract.cli_actor.entrypoint`, not a hardcoded global CLI name.

<a name="ui"></a>
## 🌐 Web UI

Docker Compose mode:

```bash
cp .env.example .env
docker compose up --build -d --wait
curl --fail http://127.0.0.1:8812/health
```

UI: `http://127.0.0.1:8812`.

Compose binds PostgreSQL and API to `127.0.0.1`. Before starting a fresh baseline over an old dev volume, follow [docs/database-reset.md](docs/database-reset.md).

App/systemd mode uses the application port from `.env`:

```bash
sudo systemctl daemon-reload
sudo systemctl restart project-workflow-ui.service
curl --fail http://127.0.0.1:8811/health
```

At startup the app verifies database connectivity; the Compose `migrate` service applies schema migrations and bootstraps the default workflow catalog.

| Area | Route |
|---|---|
| Dashboard | `/` |
| Namespaces | `/namespaces`, `/namespaces/new` |
| Tasks | `/tasks`, task detail |
| Phases | `/phases`, phase detail |
| Workflows | `/workflows` |
| Agents | `/agents` |
| Settings | `/settings` |

<a name="screenshots"></a>
## 🖼️ Screenshots

<table>
  <tr>
    <td><strong>Dashboard</strong></td>
    <td><strong>QA dashboard</strong></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/dashboard.png" alt="Dashboard" /></td>
    <td><img src="docs/screenshots/dashboard-qa.png" alt="QA dashboard" /></td>
  </tr>
  <tr>
    <td><strong>Namespaces</strong></td>
    <td><strong>Namespace creation</strong></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/namespaces.png" alt="Namespaces" /></td>
    <td><img src="docs/screenshots/namespace-new.png" alt="Namespace creation" /></td>
  </tr>
  <tr>
    <td><strong>Tasks</strong></td>
    <td><strong>QA phases</strong></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/tasks.png" alt="Tasks" /></td>
    <td><img src="docs/screenshots/phases-qa.png" alt="QA phases" /></td>
  </tr>
  <tr>
    <td><strong>QA tasks</strong></td>
    <td><strong>Workflows</strong></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/tasks-qa.png" alt="QA tasks" /></td>
    <td><img src="docs/screenshots/workflows.png" alt="Workflows" /></td>
  </tr>
</table>

Agents:

<p align="center">
  <img src="docs/screenshots/agents.png" alt="Agents" />
</p>

Workflow graph:

<p align="center">
  <img src="docs/screenshots/phases.png" alt="Workflow phases" />
</p>

Same task key in two selected entries:

<table>
  <tr>
    <td><strong>Development detail</strong></td>
    <td><strong>QA detail</strong></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/task-detail-dev.png" alt="Development task detail" /></td>
    <td><img src="docs/screenshots/task-detail-qa.png" alt="QA task detail" /></td>
  </tr>
</table>

Mobile dashboard:

<p align="center">
  <img src="docs/screenshots/mobile-dashboard.png" alt="Mobile dashboard" width="390" />
</p>

## 🛠️ Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --constraint constraints.txt -e ".[dev,ui]"
```

`constraints.txt` fixes the tested dependency set; Docker uses the same file.

<a name="architecture"></a>
## 🏗️ Architecture

```mermaid
flowchart TD
    CLI[project-workflow CLI] -->|step / history| App[Application services]
    Wrap[Namespace wrapper] -->|PROJECT_WORKFLOW_NAMESPACE_ID| CLI
    UI[FastAPI + Jinja2 UI] -->|HTML / JSON| App
    App --> Domain[Domain validation + contracts]
    App --> UoW[SQLAlchemy Unit of Work]
    UoW --> Repo[Repositories]
    Repo --> DB[(PostgreSQL)]
    App --> Supervisor[LLM Supervisor]
    Supervisor -->|PASS / ROLLBACK / BLOCK| App
```

### Принципы

- Runtime state lives in PostgreSQL; code paths should not grow hidden in-memory truth.
- Domain validation stays outside SQLAlchemy models.
- UI routes validate requests, call application services and return HTML/API responses.
- Supervisor decisions are auditable and connected to phase history.
- Compatibility aliases stay only where current runtime still needs them.

<a name="quality"></a>
## 🛡️ Quality Bar

| Проверка | Команда |
|---|---|
| Full local gate | `make quality` |
| Warning-focused gate | `make warnings` |
| Compose readiness | `make compose-ready` |
| Windows quality | `pwsh -File scripts/quality.ps1 quality` |
| Windows warnings | `pwsh -File scripts/quality.ps1 warnings` |
| Windows readiness | `pwsh -File scripts/quality.ps1 compose-ready` |

`make quality` includes unit tests, PostgreSQL integration tests, coverage, ruff and mypy. UI-facing changes also require browser smoke and screenshots.

## 🗺️ Roadmap

- [x] PostgreSQL runtime, SQLAlchemy repositories and Alembic baseline
- [x] FastAPI/Jinja2 Web UI for workflows, phases, namespaces, agents and tasks
- [x] Namespace selector, theme metadata and wrapper CLI commands
- [x] Supervisor verdict audit trail for phase transitions
- [x] FerrPOINT proprietary source-available licensing
- [ ] Automated browser screenshot smoke in the regular quality gate
- [ ] Broader API-route regression coverage for namespace/workflow mutations
- [ ] Further application-service split where legacy compatibility still hides domain boundaries

## 🧭 Project Map

```text
project-workflow/
├── project_workflow/ # domain, application services, CLI, UI and supervisor
├── tests/            # unit, integration, UI and regression coverage
├── scripts/          # quality, DB init and namespace CLI helpers
├── docs/             # architecture, quality gate, bug audit and screenshots
├── docker-compose.yml
├── pyproject.toml
└── constraints.txt
```

## 📚 Документы

- [docs/architecture.md](docs/architecture.md) — CLI/UI/Supervisor boundaries, state/audit model and runtime scope.
- [docs/quality-gate.md](docs/quality-gate.md) — local gate, PostgreSQL integration, Compose readiness and browser smoke.
- [docs/bug-audit.md](docs/bug-audit.md) — defect audit notes.
- [docs/database-reset.md](docs/database-reset.md) — safe reset for old local Compose volumes.
- [LIVE_TEST_PLAN.md](LIVE_TEST_PLAN.md) — executor-driven E2E acceptance.

<a name="license"></a>
## 🔒 License

Proprietary source-available. Not open source.

Viewing/evaluation only.

Commercial, production, resale, redistribution, SaaS/hosting use require written license from FerrPOINT. См. [LICENSE](LICENSE), [NOTICE](NOTICE) и [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
