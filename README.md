# wartz-workflow

State-driven workflow CLI с FastAPI/Jinja2 веб-UI для просмотра и редактирования данных workflow.

## Что есть сейчас

- **CLI** — ровно 2 команды:
  - `step` — показать текущую фазу / подать отчёт и перейти дальше
  - `history` — история отчётов, переходов и статусов по задаче
  - Глобальный флаг `--json` — машиночитаемый вывод для автоматизации
- **SQLite** хранит:
  - **workflows** — workflow-шаблоны (с дефолтным)
  - **phases** — фазы workflow с `execution_type` (`sync` / `parallel`)
  - **instructions** — пошаговые инструкции фаз
  - **checks / evidence** — чек-листы и артефакты фаз
  - **projects** — проекты + `key_patterns` (source of truth для regex ключей задач)
  - **tasks** — задачи с `task_key` (ранее `jira_key`)
  - **agents** — агенты исполнители
  - **task_history** — история прохождения фаз
  - **supervisor_runs** — запуски встроенного workflow supervisor
  - **cli_history** — аудит CLI-вызовов
- **Встроенный workflow supervisor** — оценивает прогресс задачи по плану/фазам/артефактам/CLI-отчётам
- **TaskKeyValidator** — валидация ключей задач через настраиваемые regex из `projects.key_patterns`
- `/settings` — read-only реестр реальных CLI-команд (автообновляется при изменении CLI)
- `/skills` — просмотр скиллов проекта

## Установка

```bash
cd /opt/dev/hermes-workspace/wartz-workflow-cli
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ui]"
```

## CLI

```bash
wartz-workflow --help
```

### 1) step

Показать текущую фазу / перейти по отчёту:

```bash
wartz-workflow step --task TASKNEIROKLYUCH-456
wartz-workflow step --task TASKNEIROKLYUCH-456 --report "сделал X, проверил Y"
```

Параметры:
- `--task` — ключ задачи, обязателен
- `--report` — отчёт агента

### 2) history

История сообщений/переходов по задаче:

```bash
wartz-workflow history --task TASKNEIROKLYUCH-456
wartz-workflow history --task TASKNEIROKLYUCH-456 --n 50
```

Параметры:
- `--task` — ключ задачи, обязателен
- `--n` — количество записей; без параметра — вся история

### JSON-режим

```bash
wartz-workflow --json step --task TASKNEIROKLYUCH-456 --report "..."
```

## Web UI

Запуск:

```bash
python -m wartz_workflow.ui --host 0.0.0.0 --port 8811
```

Страницы:
- `/` — dashboard
- `/phases` — список фаз
- `/phase/{id}` — детальная карточка фазы (инструкции, чеки, эвиденс)
- `/tasks` — список задач
- `/task/{task_key}` — детальная карточка задачи + история supervisor
- `/projects` — CRUD проектов и regex ключей
- `/agents` — CRUD агентов
- `/workflows` — CRUD workflow-шаблонов
- `/skills` — скиллы проекта
- `/settings` — read-only реестр CLI-команд

## API

JSON endpoints:
- `/api/phases`
- `/api/phases/{phase_id}`
- `/api/phases/order` (PUT — изменение порядка)
- `/api/tasks`
- `/api/projects` (GET/POST/PUT/DELETE)
- `/api/agents` (GET/POST/PUT/DELETE)
- `/api/workflows` (GET/POST/PUT/DELETE)
- `/api/settings`
- `/api/skills`

## Структура проекта

```text
wartz_workflow/
├── __init__.py
├── config.py              # Конфигурация + константы
├── conversation.py        # История переговоров / keyword-поиск
├── db.py                  # WorkflowDB — ORM-lite над SQLite
├── db_schema.sql          # DDL схемы БД
├── models.py              # Pydantic модели
├── phases.py              # Управление фазами
├── schema.py              # Миграции / инициализация каталога фаз
├── service.py             # PhaseService — бизнес-логика
├── state.py               # WorkflowState
├── task_validator.py      # Валидация task_key через проектные regex
├── ui.py                  # FastAPI приложение + шаблоны
├── verify.py              # verify-suite.sh, .gitignore проверки
├── wizard.py              # WorkflowWizard — evaluate / переходы / supervisor
├── llm.py                 # OllamaClient (local/cloud) для SMART_EVALUATE
├── cli/
│   ├── __init__.py
│   ├── core.py            # Общий group, helpers, --json
│   └── ui.py              # Команды step / history
├── references/
│   ├── seed.json          # Сид-данные
│   └── smoke_seed.json    # Smoke-test сид
└── templates/v2/
    ├── base.html
    ├── dashboard.html
    ├── phases.html
    ├── phase_detail.html
    ├── tasks.html
    ├── task_detail.html
    ├── projects.html
    ├── agents.html
    ├── workflows.html
    ├── skills.html
    └── settings.html
```

## Тесты

```bash
pytest -q
```

Покрытие (~31 test-модуль):
- `test_cli_*.py` — CLI команды (core, UI, smart evaluate, e2e)
- `test_db*.py` — БД + constraints (плохие значения отклоняются)
- `test_models.py`, `test_phases.py`, `test_state.py`
- `test_wizard*.py` — wizard evaluate, transitions, parallel groups, coverage
- `test_llm.py` — OllamaClient (local/cloud/fallback)
- `test_ui*.py` — UI endpoints + API
- `test_verify.py` — verify-suite
- `test_supervisor.py` — supervisor runs
- `test_smoke_workflow.py` — сквозной smoke

## LLM Smart Evaluate (опционально)

При `SMART_EVALUATE=1` evaluate использует LLM (Ollama Cloud + kimi-k2.6) вместо keyword matching:

```bash
export SMART_EVALUATE=1
wartz-workflow step --task TASK-KEY --report "..."
```

- **Dual-mode OllamaClient**: local `/api/chat` или cloud `/v1/chat/completions`
- **Fallback**: при недоступности LLM → rule-based evaluate
- **Покрытие**: llm.py 100%, wizard.py ~94%
- **E2E**: пройдены все фазы от -1 до 5.5 через Ollama Cloud

## Примечания

- Web UI не должен попадать в CLI как отдельная команда.
- `/settings` подхватывает CLI-команды автоматически при изменении CLI.
- Пустые / синтетические badge и placeholder-текст в UI считаются мусором и удаляются.
- После выполнения задачи и прохождения проверок изменения должны быть закоммичены; завершённую работу нельзя оставлять в dirty working tree.
