<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&height=180&text=project-workflow&desc=State-driven%20workflow%20platform&fontColor=F8FAFC&fontSize=60&fontAlignY=35&descAlignY=55&color=06B6D4" alt="project-workflow banner" />
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
  <img src="https://img.shields.io/badge/OpenAI%20Compatible-412991?style=flat-square&logo=openai&logoColor=white" alt="OpenAI Compatible" />
  <img src="https://img.shields.io/badge/Ollama-000000?style=flat-square&logo=ollama&logoColor=white" alt="Ollama" />
  <img src="https://img.shields.io/badge/OpenRouter-000000?style=flat-square&logo=openrouter&logoColor=white" alt="OpenRouter" />
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
Агент отчитывается через CLI, обязательный LLM-supervisor оценивает отчёт и выдаёт вердикт: **PASS**, **PARTIAL**, **ROLLBACK**, **BLOCKED** или **DELEGATE**.
Всё управление шаблонами workflow, фазами, проектами, агентами и задачами ведётся через Web UI.

CLI остаётся минимальным: ровно две команды — `step` и `history`.

В production используется **PostgreSQL**.

SQLite остаётся только для изолированных тестов с явно заданным DSN/engine.

<a name="features"></a>
## ✨ Features

| Feature | Описание |
|---------|----------|
| Пофазовый workflow | Каждая задача строго следует шаблону фаз с инструкциями, чек-листами и артефактами. |
| Рекомендации skills | Имена skills хранятся в PostgreSQL и передаются исполнителю прямо в контракте фазы; содержимое принадлежит [`relevanter/agent-skills`](https://gt.wmtgroup.ru/relevanter/agent-skills). |
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
| LLM / Supervisor | OpenAI-compatible Chat Completions | единственный evaluator отчётов; по умолчанию Ollama Online |
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

CLI ожидает `DATABASE_URL` и доступный OpenAI-compatible evaluator. По умолчанию используется Ollama Online:

```bash
export DATABASE_URL=postgresql+psycopg://project_workflow:project_workflow@localhost/project_workflow
export OPENAI_BASE_URL=https://ollama.com/v1
export OPENAI_MODEL=qwen3.5:397b
export OPENAI_TIMEOUT=120
export OPENAI_API_KEY=<ollama-api-key>
export OPENAI_REASONING_EFFORT=none
```

Для другого совместимого провайдера достаточно заменить `OPENAI_BASE_URL`, `OPENAI_MODEL` и `OPENAI_API_KEY`.
Если endpoint не поддерживает `reasoning_effort`, задайте `OPENAI_REASONING_EFFORT=`.
Ollama Online поддерживает это поле, а значение `none` оставляет token budget финальному JSON.
Локальный Ollama также подключается через совместимый endpoint `http://localhost:11434/v1`.

Fallback evaluator отсутствует: если провайдер недоступен или вернул некорректный JSON, команда остаётся на текущей фазе, возвращает `BLOCKED` и exit code `1`.
Повторный отчёт после `status=done` не вызывает evaluator и не создаёт новый run/history: CLI возвращает `PASS`, `status=done` и `next_phase=null`.

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

Перед первым запуском `scripts/init_db.py` применяет `alembic upgrade head` и заполняет
каталоги только в пустой БД. Последующие запуски не перезаписывают изменения из UI.

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
    Seed[packaged seed, empty DB only] --> DB
```

### Принципы

- Единый data layer: все операции через SQLAlchemy-модели и репозитории.
- Единственный evaluator — обязательный OpenAI-compatible LLM.
- UI-пакет (`project_workflow/interfaces/ui/`) — чистое FastAPI-приложение с отдельными routes, services, dependencies.
- Конфигурация централизована в `project_workflow.config` на Pydantic Settings; `DATABASE_URL` обязателен.
- PostgreSQL хранит каталог, задачи, историю, fingerprints и audit; packaged seed используется только для пустой БД.
- Skills являются рекомендациями внутри инструкций фазы; их канонические файлы хранятся в `relevanter/agent-skills`, отдельного runtime registry нет.

<a name="quality"></a>
## 🛡️ Quality Bar

| Проверка | Команда | Статус |
|---|---|---|
| Lint | `ruff check .` | **green** |
| Type check | `mypy project_workflow scripts` | **green, 83 source files** |
| Tests | `pytest -q --timeout=60` | **878 passed, 13 integration deselected** |
| PostgreSQL integration | `pytest -q -m integration tests/test_postgres_integration.py --timeout=180` | **13 passed** |
| Coverage | `pytest --cov=project_workflow --cov-report=term --timeout=60` | **95.31%** |
| Systemd UI health | `curl http://localhost:8811/api/tasks` | **200** |

<a name="roadmap"></a>
## 🗺️ Roadmap

- [x] Конфигурация на Pydantic Settings (`DATABASE_URL` required)
- [x] SQLAlchemy-модели, репозитории и unit-of-work
- [x] Alembic-миграции + `scripts/init_db.py` для автоматического baseline
- [x] Docker Compose: Postgres + migrate + UI
- [x] UI/API переведены на SQLAlchemy-сервисы
- [x] Один runtime dataflow: CLI/UI → Wizard → OpenAI-compatible evaluator → PostgreSQL
- [x] Полный suite: 861 тест green + 13 PostgreSQL integration tests
- [x] Postgres-интеграционные тесты
- [x] `WizardEngine` и wizard-модули собраны в пакет `project_workflow/wizard/`
- [x] API-тесты на все UI routes
- [x] Production hardening: `/health` endpoint, graceful shutdown, PG connection retry
- [x] Coverage > 95%
- [x] mypy `--check-untyped-defs` для wizard/core.py
- [x] UI-доработки: execution_type на отдельной строке, русское склонение счётчиков, очистка рабочей БД от мусора
- [x] Wizard evaluate: DB-backed history/audit, idempotent replay и явный parallel rendering
- [x] Packaged 27-phase catalog bootstrapped once into an empty PostgreSQL database
- [x] Forward-миграция seed-managed каталога с legacy Jira/GitLab-контрактов на текущий GitHub/OpenAI-compatible runtime
- [x] Forward-миграция пустых skill-рекомендаций существующей PostgreSQL без перезаписи UI-значений

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


