<p align="center">
  <img src="docs/assets/project-workflow-banner.jpg" alt="Project Workflow - phased work orchestration" />
</p>

<p align="center">
  <a href="#overview"><img src="https://img.shields.io/badge/Overview-1d4ed8?style=for-the-badge" alt="Overview" /></a>
  <a href="#capabilities"><img src="https://img.shields.io/badge/Capabilities-1e40af?style=for-the-badge" alt="Capabilities" /></a>
  <a href="#entrypoints"><img src="https://img.shields.io/badge/Entry_Points-18202f?style=for-the-badge" alt="Entry Points" /></a>
  <a href="#quick-start"><img src="https://img.shields.io/badge/Quick_Start-1e3a8a?style=for-the-badge" alt="Quick start" /></a>
  <a href="#ui"><img src="https://img.shields.io/badge/Web_UI-0f766e?style=for-the-badge" alt="Web UI" /></a>
  <a href="#visual-proof"><img src="https://img.shields.io/badge/Visual_Proof-155e75?style=for-the-badge" alt="Visual proof" /></a>
  <a href="#architecture"><img src="https://img.shields.io/badge/Architecture-334155?style=for-the-badge" alt="Architecture" /></a>
  <a href="#quality"><img src="https://img.shields.io/badge/Quality-475569?style=for-the-badge" alt="Quality" /></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.10 or later" />
  <img src="https://img.shields.io/badge/FastAPI-API-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/PostgreSQL-Runtime-4169e1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL runtime" />
  <img src="https://img.shields.io/badge/SQLAlchemy-2-d71f00?style=flat-square&logo=sqlalchemy&logoColor=white" alt="SQLAlchemy 2" />
  <img src="https://img.shields.io/badge/Pydantic-E92063?style=flat-square&logo=pydantic&logoColor=white" alt="Pydantic" />
  <img src="https://img.shields.io/badge/Alembic-6B8E23?style=flat-square&logo=alembic&logoColor=white" alt="Alembic" />
  <img src="https://img.shields.io/badge/uv-000000?style=flat-square&logo=astral&logoColor=white" alt="uv" />
  <img src="https://img.shields.io/badge/CI-.github%2Fworkflows%2Fci.yml-15803d?style=flat-square" alt="Repository CI" />
</p>

---

## 🎯 Позиционирование

**project-workflow** — внутренняя private-платформа для пофазного ведения задач. Агент отчитывается через CLI, обязательный LLM Supervisor проверяет отчёт и выдаёт вердикт: **PASS**, **ROLLBACK** или **BLOCK**.

Центр управления workflow, фазами, namespaces и агентами живёт в Web UI. В UI доступен просмотр задач, а не их создание или продвижение. CLI намеренно остаётся маленьким: `step` и `history`; первое `step` создаёт задачу, последующие передают отчёты и двигают её по workflow. Дополнительные namespace-команды работают как wrappers поверх этих двух операций.

Для изолированных контейнеров исполнителей сохранён private runtime bridge `/internal/runtime/step` и `/internal/runtime/history`: это отдельный service-to-service контракт с role tokens, не пользовательский UI API. Он включается только при `PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON` и должен быть доступен лишь во внутренней сети или на host loopback.

Fleet Control читает каталог через `GET /internal/runtime/catalog` с отдельным
`PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN` (не менее 32 символов). Этот токен
не разрешает `step` и `history` и не меняет `PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON`.
Маршрут должен оставаться во внутренней сети или на host loopback.

Browser UI поддерживает общий Central Auth Authorization Code + PKCE. При
заданном `AUTH_ISSUER` все UI и human API routes требуют активную центральную
сессию; локального password fallback нет. Публичный issuer и внутренний адрес
обмена/JWKS задаются отдельно через `AUTH_ISSUER` и
`AUTH_INTERNAL_BASE_URL`.

**Режим без авторизации (по умолчанию):** если `AUTH_ISSUER` не задан, SSO
middleware не активируется — UI и API работают без входа. Для standalone
запуска достаточно одного репозитория: `docker compose up -d --wait` поднимает
db + migrate + api на `127.0.0.1:8812` без Central Auth и без соседних
репозиториев.

Runtime-источник данных — **PostgreSQL**. SQLite используется только для изолированных тестов и локальных smoke-сценариев.

<a name="overview"></a>

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

<a name="capabilities"></a>

## ✨ Возможности

| Feature | Описание |
|---|---|
| Phase workflow | Задача идёт по шаблону фаз с инструкциями, checks, evidence и audit history. |
| Supervisor gate | Переход фазы проходит через обязательную оценку отчёта и фиксирует `PASS` / `ROLLBACK` / `BLOCK`. |
| Namespace runtime | Несколько entrypoints могут иметь свои workflow, задачи, стиль UI и CLI-команду. |
| Web UI | Управление workflows, phases, namespaces и agents; просмотр задач и audit history. |
| Append-only history | История фаз и `step`-проверок не затирается. |
| CLI freeze | Публичный CLI остаётся управляемым и предсказуемым: `step` / `history`. |
| Wrapper commands | `workflow-qa`, `workflow-dev` и другие команды генерируются из записей PostgreSQL. |
| Automatic baseline | `docker compose up` поднимает Postgres, применяет миграции и загружает стартовый каталог. |

## 🔧 Стек

| Zone | Tech | Роль |
|---|---|---|
| Runtime | Python 3.10+ | application runtime и packaging target |
| Data | PostgreSQL | source of truth для UI, CLI и supervisor state |
| ORM | SQLAlchemy 2 | models, repositories, unit-of-work |
| Migrations | Alembic | schema history и baseline |
| API/UI | FastAPI + Jinja2 | server-side UI и JSON endpoints |
| Validation | Pydantic | settings, schemas и DTO boundaries |
| CLI | Click + Rich | компактный agent-facing command surface |
| Tooling | uv + constraints.txt | повторяемый локальный и container dependency set |
| Quality | pytest, ruff, mypy | локальный quality gate |

<a name="entrypoints"></a>

## 🧩 CLI Entry Points

Каждый namespace/entrypoint хранит:

| Field | Role |
|---|---|
| Name и description | UI identity и human-facing purpose |
| Bound workflow | Phase template для задач этого entrypoint |
| Icon и theme color | Стилизация header, dashboard и task-detail |
| Custom CLI command | Пользовательская wrapper-команда, например `workflow-qa` |

Верхний UI selector переключает logo/name, accent color, dashboard, task list, task detail и `/phases`. Выбранный entrypoint хранится в cookie `workflow_namespace_id`; `?namespace_id=` имеет приоритет над cookie.

Канонический API: `/api/namespaces`; старые UI/API alias-роуты не входят в публичную поверхность.

## 🖥️ CLI

По умолчанию локальный CLI ожидает `DATABASE_URL`:

```bash
export DATABASE_URL=postgresql+psycopg://project_workflow:project_workflow@localhost:5432/project_workflow
```

Платформенный token mode не подключается к БД напрямую. При заданном
`SDLC_API_TOKEN` команды `step` и `history` используют защищённый HTTP API и
общий transport package `sdlc-cli-core` (ставится отдельно из
`services-base/python/cli-core`; в standalone-сборку не входит):

```bash
export PROJECT_WORKFLOW_URL=http://localhost:8812
export SDLC_API_TOKEN='<personal token from Admin Panel>'
workflow-dev step --task RUN-42 --report "Проверил сценарий"
```

Central Auth проверяет срок, отзыв и scopes
`project-workflow:read/write`. Значение токена не передаётся в URL и не
сохраняется приложением.

Генерация пользовательских wrapper-команд:

```bash
python scripts/install_namespace_clis.py --bin-dir ./.bin
```

Запуск выбранного workflow через настроенную команду:

```bash
workflow-run step --task RUN-123 --report "Сделал X, проверил Y"
```

Чтение истории фаз и supervisor-а того же entrypoint:

```bash
workflow-run history --task RUN-123 --n 10
```

Параллельные entrypoints используют собственные настроенные команды:

```bash
workflow-qa step --task RUN-42 --report "Проверил сценарии"
workflow-dev history --task RUN-42
```

Wrapper выставляет `PROJECT_WORKFLOW_NAMESPACE_ID=<id>` и вызывает внутренний `step/history` CLI, поэтому один и тот же внешний task key может существовать независимо в разных namespaces. Исполнитель получает настроенную wrapper-команду в `phase_contract.cli_actor.entrypoint`, а не хардкоженное глобальное имя CLI.

<a name="ui"></a>

<a name="quick-start"></a>

## 🌐 Web UI

Docker Compose mode:

```bash
cp .env.example .env
docker compose up --build -d --wait
curl --fail http://127.0.0.1:8812/health
```

UI: `http://127.0.0.1:8812`.

Compose привязывает PostgreSQL и API к `127.0.0.1`. Перед стартом свежего baseline поверх старого dev-тома следуйте [docs/database-reset.md](docs/database-reset.md).

Локальный app mode использует БД из `DATABASE_URL` и порт приложения из CLI-флагов:

```bash
python -m project_workflow.interfaces.ui --host 127.0.0.1 --port 8812
curl --fail http://127.0.0.1:8812/health
```

При старте приложение проверяет connectivity БД; Compose `migrate`-сервис применяет миграции схемы и загружает дефолтный workflow-каталог.

| Area | Route |
|---|---|
| Dashboard | `/` |
| Namespaces | `/namespaces`, `/namespaces/new` |
| Tasks | `/tasks`, `/task/{task_key}` (только наблюдение) |
| Phases | `/phases`, `/phase/{phase_id}`, `/instructions?phase_id={phase_id}` |
| Workflows | `/workflows` |
| Agents | `/agents` |
| Settings | `/settings` |

<a name="visual-proof"></a>

## 🖼️ Визуальные доказательства

Браузерные свидетельства сняты full-page с нейтральной изолированной фикстурой (neutral isolated fixture): generic namespace-имена и UI-testing copy, без credentials, реальных task keys, URL и filesystem-путей. Покрытие — active, blocked и done состояния задач.

<figure>
  <figcaption><strong>Дашборд / Разработка</strong></figcaption>
  <img src="docs/screenshots/dashboard.png" alt="Дашборд / Разработка full-page evidence" width="100%" />
</figure>

<figure>
  <figcaption><strong>Дашборд / Проверка качества</strong></figcaption>
  <img src="docs/screenshots/dashboard-qa.png" alt="Дашборд / Проверка качества full-page evidence" width="100%" />
</figure>

<figure>
  <figcaption><strong>Неймспейсы</strong></figcaption>
  <img src="docs/screenshots/namespaces.png" alt="Неймспейсы full-page evidence" width="100%" />
</figure>

<figure>
  <figcaption><strong>Создание неймспейса</strong></figcaption>
  <img src="docs/screenshots/namespace-new.png" alt="Создание неймспейса full-page evidence" width="100%" />
</figure>

<figure>
  <figcaption><strong>Задачи / Разработка</strong></figcaption>
  <img src="docs/screenshots/tasks.png" alt="Задачи / Разработка full-page evidence" width="100%" />
</figure>

<figure>
  <figcaption><strong>Задачи / Проверка качества</strong></figcaption>
  <img src="docs/screenshots/tasks-qa.png" alt="Задачи / Проверка качества full-page evidence" width="100%" />
</figure>

<figure>
  <figcaption><strong>Воркфлоу</strong></figcaption>
  <img src="docs/screenshots/workflows.png" alt="Воркфлоу full-page evidence" width="100%" />
</figure>

<figure>
  <figcaption><strong>Фазы / Разработка</strong></figcaption>
  <img src="docs/screenshots/phases.png" alt="Фазы / Разработка full-page evidence" width="100%" />
</figure>

<figure>
  <figcaption><strong>Фазы / Проверка качества</strong></figcaption>
  <img src="docs/screenshots/phases-qa.png" alt="Фазы / Проверка качества full-page evidence" width="100%" />
</figure>

<figure>
  <figcaption><strong>Инструкции</strong></figcaption>
  <img src="docs/screenshots/instructions.png" alt="Инструкции full-page evidence" width="100%" />
</figure>

<figure>
  <figcaption><strong>Агенты</strong></figcaption>
  <img src="docs/screenshots/agents.png" alt="Агенты full-page evidence" width="100%" />
</figure>

<figure>
  <figcaption><strong>CLI-настройки</strong></figcaption>
  <img src="docs/screenshots/settings.png" alt="CLI-настройки full-page evidence" width="100%" />
</figure>

<figure>
  <figcaption><strong>Одна задача / Разработка</strong></figcaption>
  <img src="docs/screenshots/task-detail-dev.png" alt="Одна задача / Разработка full-page evidence" width="100%" />
</figure>

<figure>
  <figcaption><strong>Одна задача / Проверка качества</strong></figcaption>
  <img src="docs/screenshots/task-detail-qa.png" alt="Одна задача / Проверка качества full-page evidence" width="100%" />
</figure>

На мобильных ширинах карточки стекаются, редактор остаётся одноколоночной формой.

<a name="architecture"></a>

## 🏗️ Архитектура

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

- Runtime state живёт в PostgreSQL; код-пути не должны растить скрытое in-memory truth.
- Domain validation остаётся вне SQLAlchemy-моделей.
- UI-роуты валидируют запросы, вызывают application services и возвращают HTML/API-ответы.
- Решения Supervisor-а аудируемы и связаны с историей фаз.
- Compatibility aliases остаются только там, где текущий runtime их ещё требует.

<a name="quality"></a>

## 🛠️ Разработка

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --constraint constraints.txt -e ".[dev,ui]"
```

`constraints.txt` фиксирует протестированный dependency set; Docker использует тот же файл.

<a name="safety"></a>

## 🛡️ Качество и проверки

| Проверка | Команда |
|---|---|
| Full local gate | `make quality` |
| Warning-focused gate | `make warnings` |
| Compose readiness | `make compose-ready` |
| Documentation regression | `pytest -q tests/test_docs_quality.py --timeout=60` |
| README assets и anchors | `python scripts/verify_readme.py` |
| Unit/UI tests | `pytest -q --timeout=60` |
| PostgreSQL integration | `pytest -q -m integration tests/test_postgres_integration.py --timeout=120` |
| Coverage | `pytest --cov=project_workflow --cov-report=term --timeout=60` |
| Lint и типы | `ruff check .` и `mypy project_workflow scripts` |
| Windows quality | `pwsh -File scripts/quality.ps1 quality` |

`make quality` включает unit/UI-тесты, PostgreSQL integration tests, coverage, ruff и mypy. Тот же набор автоматически выполняет GitHub Actions на push и pull request в `master`.

## 🗺️ Roadmap

- [x] PostgreSQL runtime, SQLAlchemy repositories и Alembic baseline
- [x] FastAPI/Jinja2 Web UI для workflows, phases, namespaces, agents и tasks
- [x] Namespace selector, theme metadata и wrapper CLI commands
- [x] Supervisor verdict audit trail для phase transitions
- [x] FerrPOINT proprietary source-available licensing
- [ ] Automated browser screenshot smoke в регулярном quality gate
- [ ] Более широкое API-route regression покрытие для namespace/workflow мутаций
- [ ] Дальнейшее разделение application services, где legacy compatibility ещё скрывает доменные границы

## 🧭 Карта проекта

```text
project-workflow/
├── project_workflow/ # domain, application services, CLI, UI и supervisor
├── tests/            # unit, integration, UI и regression coverage
├── scripts/          # quality, DB init и namespace CLI helpers
├── docs/             # architecture, quality gate, bug audit и screenshots
├── docker-compose.yml
├── pyproject.toml
└── constraints.txt
```

## 📚 Документы

- [docs/architecture.md](docs/architecture.md) — CLI/UI/Supervisor boundaries, state/audit model и runtime scope.
- [docs/quality-gate.md](docs/quality-gate.md) — local gate, PostgreSQL integration, Compose readiness и browser smoke.
- [docs/bug-audit.md](docs/bug-audit.md) — defect audit notes.
- [docs/database-reset.md](docs/database-reset.md) — безопасный reset старых локальных Compose-томов.
- [LIVE_TEST_PLAN.md](LIVE_TEST_PLAN.md) — executor-driven E2E acceptance.

<a name="license"></a>

## 🔒 Лицензия

Proprietary source-available. Not open source. Viewing/evaluation only.

Commercial, production, resale, redistribution, SaaS/hosting use require written license from FerrPOINT. См. [LICENSE](LICENSE), [NOTICE](NOTICE) и [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
