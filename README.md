# project-workflow

Internal loopback/private workflow tool для FerrPOINT: агент отчитывается через CLI, LLM Supervisor проверяет результат и переводит задачу по фазам с evidence and audit history.

| Поле | Значение |
|---|---|
| Статус | Internal `1.0.0`, runtime source of truth is PostgreSQL |
| Backend/UI | Python 3.10+, FastAPI/Jinja UI, Click/Rich CLI |
| Domain | Pydantic, SQLAlchemy, Alembic migrations |
| Runtime | Docker Compose on loopback, PostgreSQL, namespace-aware CLI wrappers |
| Порт | UI/API `127.0.0.1:8812` |
| Лицензия | [FerrPOINT Proprietary Source-Available Evaluation License v1.0](LICENSE) |

## Что есть

- Phase workflow templates with instructions, checks, evidence requirements and audit history.
- Mandatory LLM Supervisor gate before task phase transitions.
- Multiple CLI entrypoints with independent workflow binding, theme, display name and command.
- Web UI for workflows, phases, CLI entrypoints, agents and tasks.
- Append-only history for phases and `step` checks.
- Small base CLI surface: `step` and `history`; specialized commands are generated as wrappers.

## Границы

- Tool is designed for local/private execution, not public multi-tenant hosting.
- Compose binds PostgreSQL and API to `127.0.0.1`.
- Old dev volumes may need reset before a new baseline schema; see [docs/database-reset.md](docs/database-reset.md).
- `constraints.txt` is the tested dependency set and is also used by Docker builds.

## Быстрый старт

```bash
cp .env.example .env
docker compose up --build -d --wait
curl --fail http://127.0.0.1:8812/health
```

UI: `http://127.0.0.1:8812`.

## CLI wrappers

Each configured record stores a display name, description, workflow binding, UI icon/color and user-facing CLI command. The UI selector switches the active record across logo/name, accent color, dashboard, task lists, detail pages and `/phases`.

Selection is stored in `workflow_namespace_id`; `?namespace_id=` has priority over the cookie. Internal `/api/namespaces` and old alias routes stay only for compatibility.

Base CLI:

```bash
project-workflow step --task RUN-123 --report "Сделал X, проверил Y"
project-workflow history --task RUN-123 --n 10
```

Wrapper generation:

```bash
python scripts/install_namespace_clis.py --bin-dir ./.bin
workflow-qa step --task RUN-42 --report "Проверил сценарии"
workflow-dev history --task RUN-42
```

The wrapper sets `PROJECT_WORKFLOW_NAMESPACE_ID=<id>` and calls `project-workflow step/history`, so one external task can exist independently across several configured records.

## Разработка

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --constraint constraints.txt -e ".[dev,ui]"
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --constraint constraints.txt -e ".[dev,ui]"
```

## Проверки

```bash
make quality
make warnings
make compose-ready
```

Windows without `make`:

```powershell
pwsh -File scripts/quality.ps1 quality
pwsh -File scripts/quality.ps1 warnings
pwsh -File scripts/quality.ps1 compose-ready
```

## Структура

```text
project-workflow/
├── project_workflow/ # domain, application services, CLI, UI and supervisor
├── tests/            # unit, integration, UI and regression coverage
├── scripts/          # quality, DB init and CLI entrypoint helpers
├── docs/             # architecture and quality gate notes
├── docker-compose.yml
├── pyproject.toml
└── constraints.txt
```

## Документы

- [docs/architecture.md](docs/architecture.md) - CLI/UI/Supervisor boundaries, state/audit model and runtime scope.
- [docs/quality-gate.md](docs/quality-gate.md) - local gate, PostgreSQL integration, Compose readiness and browser smoke.
- [docs/bug-audit.md](docs/bug-audit.md) - defect audit notes.
- [LIVE_TEST_PLAN.md](LIVE_TEST_PLAN.md) - executor-driven E2E acceptance.

## Лицензия

Proprietary source-available. Not open source.

Viewing/evaluation only.

Commercial, production, resale, redistribution, SaaS/hosting use require written license from FerrPOINT. См. [LICENSE](LICENSE), [NOTICE](NOTICE) и [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
