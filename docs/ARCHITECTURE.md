# Анализ структуры проекта + Целевая архитектура

## Диагностика текущего состояния

### Распределение кода

| Файл | Строк | Зона ответственности | Проблема |
|------|-------|----------------------|----------|
| **cli.py** | **965** | CLI-парсинг + бизнес-логика + UI-команды + субпроцессы + состояние | **God Object** — 17 команд, 21 функций, импорты 12 модулей |
| **ui.py** | 530 | FastAPI + HTML-шаблоны + Jinja-like fallback + CLI-entry | Смешаны слои: API, рендеринг, утилиты |
| **wizard.py** | 353 | Интерактивный диалог + анализ ответов + чеклист + gate | Большой, но концентрированный |
| **jira_gitlab.py** | 277 | Jira REST + GitLab API + fallback на файлы + 2 токена | Мешаны два API + локальные проверки |
| **engine.py** | 256 | декларативный engine + проверки + subprocess | Мешан декларативный DSL и императивные проверки |
| **state.py** | 205 | progress.json + git-операции + поиск репозитория | I/O с side-эффектами (git reset, git rebase) |
| **conversation.py** | 192 | SQLite CRUD + digest + поиск фазы | OK, но singleton DB без сессий |
| **rollback.py** | 151 | Git-откат | OK, отдельный модуль |
| **profiles.py** | 188 | YAML-профили + GitLab merge settings | OK, но завязан на click.options |
| **schema.py** | 162 | 6 dataclasses + YAML-парсинг | OK, но `PhaseQuestions` — устарел |
| **task_validator.py** | 245 | Валидация ключей + key_patterns + config | OK, но `KeyStyle` enum — переусложнён |
| **config.py** | 75 | Константы + BLOCKER_PHASES + WARTZ_DIR | OK, но `WARTZ_DIR` — глобальное состояние |
| **phases.py** | 175 | `phase_map` + `get_next_phase` + `get_phase_by_id` | OK, тонкий слой над schema |
| **verify.py** | 86 | внешние проверки через bash-команды | OK, но subprocess — скрытый side-effect |

### Тестовое покрытие

| Модуль | Тесты | Норма | Дефицит |
|--------|-------|-------|---------|
| verify.py | 1.1x строк теста | ОК | |
| rollback.py | 0.9x | ОК | |
| profiles.py | 0.8x | Почти OK | |
| **cli.py** | **0.0x** (44 lines / 965) | **Критическая** | 921 строк untested |
| **engine.py** | **0.0x** | **Критическая** | 256 строк untested |
| **conversation.py** | **0.0x** | **Критическая** | 192 строк untested |
| **schema.py** | **0.0x** | **Критическая** | 162 строк untested |

### Side-effects (скрытые)

| Side-effect | Где | Проблема |
|-------------|-----|----------|
| `subprocess.run(..., shell=True)` | cli.py(1), engine.py(4), state.py(5), verify.py(3), wizard.py(1) | Код нельзя тестировать без патча subprocess; shell=True — безопасность |
| `sqlite3.connect(DB_PATH)` | conversation.py(глобально) | Singleton без сессий; гонки в параллельных тестах |
| `os.makedirs(...)` | cli.py, state.py, verify.py | Файловые операции без абстракции |
| `json.dump(..., state_file)` | state.py | Прямая запись на диск без rollback ошибки |
| `requests.get(...)` | jira_gitlab.py | HTTP без retry, backoff, circuit breaker |
| `git reset --hard`, `git rebase` | state.py | Деструктивные git-команды без подтверждения |

### Устаревшее

| Конструкт | Зачем был нужен | Почему устарел |
|-----------|-----------------|----------------|
| `PhaseQuestion` | Сложные вопросы с keywords | wizard v4.1 сразу берёт из checklist |
| `AnswerAnalysis` namedtuple | Сложная эвристика покрытия | Заменён на простые списки |
| `key_patterns` в validator | Гибкие regex-паттерны | База уже выросла; новые ключи — легаси |
| `PhaseDelegate` | Делегаты для `delegate_task` | Используется, но YAML схема переусложнена |

---

## Целевая архитектура (v2.0)

### Принципы

1. **Clean Architecture** — зависимости направлены ВНУТРЬ (к центру)
2. **Порт-Адаптер** — бизнес-логика независима от CLI / API / БД
3. **Dependency Injection** — сервисы получают репозитории через конструктор
4. **No God Objects** — cli.py < 200 строк; ui.py < 200 строк
5. **Test Doubles** — каждый boundary-адаптер mockable

### Структура директорий

```
wartz_workflow/
├── __init__.py
│
├── # ═════════ DOMAIN (ядро, чистые классы) ═════════
├── domain/
│   ├── __init__.py
│   ├── phase.py          ← Phase, PhaseCheck, PhaseEvidence, PhaseInstruction
│   ├── task.py           ← Task, TaskKey, TaskStatus
│   ├── checklist.py        ← Checklist, CheckItem, Coverage
│   └── transition.py       ← Transition, Blocker, GateResult
│
├── # ════════ APPLICATION (юзкейсы, без I/O) ════════
├── application/
│   ├── __init__.py
│   ├── wizard_usecase.py   ← WizardEngine (только логика, нет rich)
│   ├── jira_usecase.py     ← Получить статус задачи (абстракция)
│   └── state_usecase.py    ← Чтение/запись состояния (абстракция)
│
├── # ═════ ADAPTERS (внешний мир -- заменяемые) ══════
├── adapters/
│   ├── __init__.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── conversation_repo.py   ← sqlite3 CRUD
│   │   └── schema.yaml            ← сюда переехать phases.yaml
│   ├── http/
│   │   ├── __init__.py
│   │   ├── jira_client.py         ← requests → Jira
│   │   └── gitlab_client.py       ← requests → GitLab
│   ├── file/
│   │   ├── __init__.py
│   │   ├── state_store.py          ← progress.json
│   │   ├── info_store.py           ← info/ папки
│   │   └── changelog_store.py      ← changelog.md
│   └── shell/
│       ├── __init__.py
│       └── runner.py               ← subprocess.run (единственный файл)
│
├── # ══════ PORTS (интерфейсы для DI) ════════
├── ports/
│   ├── __init__.py
│   ├── jira_port.py        ← JiraPort (abc)
│   ├── state_port.py       ← StatePort (abc)
│   ├── convo_port.py       ← ConversationPort (abc)
│   └── shell_port.py       ← ShellRunnerPort (abc)
│
├── # ══════ API (FastAPI -- thin wrapper) ══════
├── api/
│   ├── __init__.py
│   ├── app.py              ← FastAPI factory
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── phases.py       ← GET /phases
│   │   ├── tasks.py        ← GET /tasks, /task/{id}
│   │   ├── wizard.py       ← POST /wizard/{task_id}/answer
│   │   └── config.py       ← GET /config
│   └── templates/
│       ├── index.html
│       ├── ...
│
└── # ══════ CLI (thin wrapper над usecases) ══════
    cli/
    ├── __init__.py
    ├── main.py             ← click.Group + общие opts
    ├── commands/
    │   ├── __init__.py
    │   ├── init.py         ← hrflow init
    │   ├── wizard.py       ← hrflow wizard
    │   ├── note.py         ← hrflow note
    │   ├── ui.py           ← hrflow ui
    │   ├── status.py       ← hrflow status
    │   └── rollback.py     ← hrflow rollback
    └── renderers/
        ├── __init__.py
        ├── rich_renderer.py    ← Все rich console prints
        └── json_renderer.py    ← --json output mode

config/
├── __init__.py
└── settings.py             ← Pydantic Settings (env vars, defaults)

tests/
├── unit/
│   ├── domain/
│   ├── application/
│   └── ports/
├── integration/
│   ├── adapters/
│   └── api/
└── e2e/
    └── cli/
```

### Поток данных

```
Пользователь → CLI (click) → Application UseCase → Domain Model
                                      ↓
                                  Adapters (DB, HTTP, File, Shell)
                                      ↓
                              Внешний мир (Jira, GitLab, SQLite, bash)

Пользователь → API (FastAPI) → Application UseCase → [то же ядро]
```

### Dependency Rule

**Внутренние слои не знают о внешних.**

- `domain/` → ничего не импортирует (чистые dataclasses)
- `application/` → импортирует только `domain/`
- `adapters/` → импортирует `application/ports` (интерфейсы)
- `cli/`, `api/` → импортируют `application/` и инициализируют адаптеры

---

## Чеклист миграции

### Phase 1: Выделить чистое ядро (domain/)
- [ ] Перенести `schema.py` → `domain/phase.py` (6 dataclasses)
- [ ] Удалить `PhaseQuestion`, `PhaseDelegate`
- [ ] Создать `domain/checklist.py` (CoverItem, CheckResult)
- [ ] Создать `domain/task.py` (TaskKey с валидацией)
- [ ] **Тесты**: unit/domain/ с pytest-dataclasses assertion

```bash
# Соотношение test/code: 1.5x для domain
pytest tests/unit/domain/ -v
```

### Phase 2: Выделить порты (ports/)
- [ ] Создать `ports/jira_port.py` (ABC)
- [ ] Создать `ports/state_port.py` (ABC)
- [ ] Создать `ports/convo_port.py` (ABC)
- [ ] Создать `ports/shell_port.py` (ABC, без shell=True)
- [ ] **Тесты**: проверить что порты — чистые ABC

### Phase 3: Рефактор adapters/
- [ ] `conversation.py` → `adapters/db/conversation_repo.py`
- [ ] Добавить `session` параметр (не глобальный DB_PATH)
- [ ] `jira_gitlab.py` → `adapters/http/jira_client.py` + `adapters/http/gitlab_client.py`
- [ ] `state.py` → `adapters/file/state_store.py` + `adapters/file/info_store.py`
- [ ] Выделить `shell/runner.py` — единственный файл с subprocess
- [ ] Заменить `shell=True` на list-аргументы везде
- [ ] **Тесты**: integration test каждого адаптера с fake/testdouble

### Phase 4: Application usecases
- [ ] `wizard.py` логика → `application/wizard_usecase.py` (без rich)
- [ ] Добавить `WizardPresenter` port (интерфейс для вывода)
- [ ] `engine.py` → `application/engine_usecase.py`
- [ ] **Тесты**: unit/application/ без I/O

### Phase 5: CLI refactor
- [ ] Разбить `cli.py` (965 → ~150):
  - `cli/main.py` — click.Group + entry point
  - `cli/commands/init.py` — hrflow init
  - `cli/commands/wizard.py` — hrflow wizard
  - `cli/commands/note.py` — hrflow note
  - `cli/commands/ui.py` — hrflow ui
  - ... и т.д.
- [ ] Перенести все `console.print` → `cli/renderers/rich_renderer.py`
- [ ] Добавить `--json` renderer → `cli/renderers/json_renderer.py`
- [ ] **Тесты**: e2e/cli/ через `click.testing.CliRunner`

### Phase 6: API refactor
- [ ] Разбить `ui.py` (530 → ~100):
  - `api/app.py` — FastAPI factory
  - `api/routers/phases.py` — endpoints
  - `api/routers/tasks.py`
  - `api/routers/wizard.py`
  - `api/routers/config.py`
- [ ] HTML templates остаются, но вынесены из Python-кода
- [ ] **Тесты**: integration/api/ через TestClient

### Phase 7: Config через Pydantic Settings
- [ ] `config.py` → `config/settings.py`
- [ ] Все `os.environ` + `os.getenv` → Pydantic BaseSettings
- [ ] `.env` через `python-dotenv`
- [ ] **Тесты**: unit/config/

### Phase 8: Запуск + Cleanup
- [ ] Удалить `__pycache__` references
- [ ] Улучшить `.gitignore` для build artifacts
- [ ] `pyproject.toml` — обновить packages
- [ ] **E2E test**: полный happy-path через CLI

---

## Критерий "готово"

### Качество кода
```
Все файлы <= 300 строк:
  ❌ cli.py 965 → ✅ split into 10 files
  ❌ ui.py  530  → ✅ split into 5 routers + templates
  ❌ jira_gitlab.py 277 → ✅ jira_client.py 120 + gitlab_client.py 120
  ❌ engine.py 256 → ✅ engine_usecase.py 180 + shell/adapter.py 80
```

### Тесты
```
Каждый адаптер:
  ✅ unit test с mock boundary
  ✅ integration test с real boundary (отдельно с @pytest.mark.integration)

Каждая команда CLI:
  ✅ e2e через CliRunner
  ✅ --json и --rich режимы

Каждый endpoint API:
  ✅ TestClient GET/POST
  ✅ 404/422/500 error paths
```

### Метрики
```
Code coverage: 60% → 85%+
Cyclomatic complexity: макс A (~5)
Fan-out (число зависимостей): каждый модуль <= 5 imports
Fan-in (использований): каждый порт >= 2 клиента
```

---

## Почему это важно

**Сейчас:** Добавить фичу в cli.py → трогаешь 965 строк → ломаешь 12 модулей → тестируешь вручную.
**После:** Добавить фичу → пишешь usecase (50 строк) → добавляешь endpoint + command (по 10 строк) → тесты проходят.

**Сейчас:** wizard и ui.py импортируют одну логику, но нельзя переиспользовать.
**После:** Один `WizardUseCase` → используется и в CLI, и в API, и в cron job.

**Сейчас:** HTTP-вызовы без retry → падают на flaky wifi.
**После:** `JiraClient` с `httpx` + `backoff` + circuit breaker, testable.

**Сейчас:** Тесты запускают `subprocess.run("git reset --hard")` реальный.
**После:** `ShellRunnerPort` → `FakeShellRunner` в тестах, `RealShellRunner` в проде.
