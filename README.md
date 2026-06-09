# wartz-workflow

State-driven workflow CLI with a small FastAPI web UI for viewing and editing workflow data.

## Что есть сейчас

- CLI: **ровно 2 команды**
  - `step`
  - `history`
- Web UI запускается **отдельно**, не через CLI-команду
- SQLite хранит:
  - фазы
  - задачи
  - проекты
  - группы фаз
  - агентов
- `projects.key_patterns` — source of truth для regex ключей задач
- `/settings` — это **read-only реестр реальных CLI-команд**, а не редактор runtime-конфига

## Установка

```bash
cd /opt/dev/hermes-workspace/wartz-workflow-cli
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ui]"
```

## CLI

Показать help:

```bash
wartz-workflow --help
```

Доступны только две команды.

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
- `--n` — количество записей; без параметра выводится вся история

## Web UI

Запуск:

```bash
python -m wartz_workflow.ui --host 0.0.0.0 --port 8811
```

Основные страницы:
- `/` — dashboard
- `/phases` — список фаз
- `/phase/{id}` — детальная карточка фазы
- `/tasks` — список задач
- `/task/{task_key}` — детальная карточка задачи
- `/projects` — CRUD проектов и regex ключей
- `/agents` — CRUD агентов
- `/settings` — read-only реестр CLI-команд

## API

Основные JSON endpoints:
- `/api/phases`
- `/api/tasks`
- `/api/projects`
- `/api/agents`
- `/api/settings`

## Структура проекта

```text
wartz_workflow/
├── __init__.py
├── config.py
├── conversation.py
├── db.py
├── db_schema.sql
├── models.py
├── phases.py
├── schema.py
├── service.py
├── state.py
├── task_validator.py
├── ui.py
├── verify.py
├── wizard.py
├── cli/
│   ├── __init__.py
│   ├── core.py
│   └── ui.py
├── references/
│   └── seed.json
└── templates/v2/
    ├── agents.html
    ├── base.html
    ├── dashboard.html
    ├── phase_detail.html
    ├── phases.html
    ├── projects.html
    ├── settings.html
    ├── task_detail.html
    └── tasks.html
```

## Тесты

```bash
pytest -q
```

## Примечания

- Web UI не должен попадать в CLI как отдельная команда.
- Если в Click CLI появится новая команда, `/settings` подхватит её автоматически.
- Пустые/синтетические badge'и и placeholder-текст в UI считаются мусором и должны удаляться.
- После выполнения задачи и прохождения проверок изменения должны быть закоммичены; завершённую работу нельзя оставлять в dirty working tree.

## LLM Smart Evaluate (опционально)

При `SMART_EVALUATE=1` evaluate использует LLM (Ollama Cloud + kimi-k2.6) вместо keyword matching:

```bash
export SMART_EVALUATE=1
wartz-workflow step --task TASK-KEY --report "..."
```

- **Dual-mode OllamaClient**: local `/api/chat` или cloud `/v1/chat/completions`
- **Fallback**: при недоступности LLM → rule-based evaluate
- **Покрытие**: llm.py 100%, wizard.py 94%
- **E2E**: пройдены все фазы от -1 до 5.5 через Ollama Cloud
