# wartz-workflow

> **State-driven 30-phase engine for agent development workflows**
> CLI-first, UI-assisted, SQLite-backed.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-151%20passing-brightgreen.svg)]()

---

## Quick Start

```bash
cd /opt/dev/wartz-workflow-cli
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
hrflow --help
```

## Основные команды

### CLI

```bash
# Показать текущую фазу + инструкции
hrflow wizard TASKNEIROKLYUCH-456

# Агент шлёт отчёт → wizard оценивает
hrflow wizard TASKNEIROKLYUCH-456 --report "сделал X, проверил Y"
# exit 0 = PASS, exit 1 = FAIL

# Полный контекст для агента
hrflow wizard-context TASKNEIROKLYUCH-456

# Запустить Web UI
hrflow ui --port 8811
```

### Web UI (http://localhost:8811)

| Страница | Что делает |
|----------|------------|
| `/` | Dashboard |
| `/phases` | Kanban: фазы в колонках |
| `/phase/{id}` | Детальная карточка фазы: инструкции, чеки, evidence |
| `/settings` | Настройки: key_patterns, Jira/GitLab URLs, UI port |
| `/wizard` | Список фаз для wizard |
| `/wizard/{phase_id}` | Форма прохождения фазы |

---

## Архитектура

```
wartz_workflow/
├── cli/
│   ├── commands.py      # CLI: init, wizard, wizard-context, status...
│   └── ui.py            # CLI: ui --port
├── config.py            # settings.json, DEFAULT_SETTINGS
├── db.py                # SQLite CRUD (phases, instructions, checks, evidence, agents)
├── db_schema.sql        # DDL
├── models.py            # Domain dataclasses (Phase, Instruction, Check, Evidence)
├── schema.py            # seed.json → SQLite loader, YAML fallback
├── service.py           # PhaseService: Controller → Service → Data Access
├── ui.py                # FastAPI: routes + Jinja2 templates
├── wizard.py            # WizardEngine: evaluate(report), get_full_context()
├── conversation.py      # SQLite: transitions, questions, answers
├── phases.py            # phase_map, get_next_phase
├── profiles.py          # Agent profiles
├── task_validator.py    # Task key regex validation
├── verify.py            # verify-suite.sh runner
├── rollback.py          # Git rollback engine
├── engine.py            # Declarative engine
├── state.py             # progress.json + git ops
├── adapters/
│   ├── db/
│   ├── http/
│   └── ports.py
├── api/
│   └── routers/
├── references/
│   └── seed.json        # 30-phase seed data (canonical source)
└── templates/v2/
    ├── base.html
    ├── dashboard.html
    ├── phases.html
    ├── phase_detail.html
    ├── settings.html
    ├── wizard.html
    └── wizard_list.html

tests/
├── test_ui.py           # Web UI
├── test_integration.py  # End-to-end
├── test_db.py           # SQLite CRUD
├── test_db_constraints.py # DB CHECK constraints
├── test_wizard_context.py # WizardEngine.get_full_context()
├── test_wizard.py       # wizard CLI
├── test_phases.py
├── test_task_validator.py
├── test_profiles.py
├── test_rollback.py
├── test_state.py
├── test_verify.py
├── test_adapters.py
├── test_cli_core.py
└── test_cli_ui.py
```

---

## State Machine

```
Agent работает → шлёт отчёт → wizard.evaluate()
                      ↓
              PASS / FAIL
              ↓         ↓
        next phase    доработай
        (auto)        (retry)
```

- **Sync** — фаза выполняется последовательно, ждёт предыдущую
- **Parallel** — несколько фаз в одном batch, выполняются одновременно, JOIN ждёт всех
- **Blocker** — нельзя пропустить, FAIL → rollback
- **Delegated** — назначен агент, agent_id в поле `delegate_agent`
- **Critic** — review gate перед commit

---

## Wizard: как агент проходит фазу

1. **Получить инструкции**
   ```bash
   hrflow wizard TASKNEIROKLYUCH-456
   ```
   Wizard возвращает:
   - название фазы
   - description
   - checklist (instructions + checks + evidence)
   - repeatable checks (лог, progress, changelog)

2. **Выполнить и отчитаться**
   ```bash
   hrflow wizard TASKNEIROKLYUCH-456 --report "создал task-файл, заполнил секции"
   ```
   Wizard оценивает:
   - keyword matching по checklist
   - repeatable checks
   - возвращает JSON: `{verdict: PASS|FAIL, covered: [...], missing: [...]}`

3. **Полный контекст (для LLM-агента)**
   ```bash
   hrflow wizard-context TASKNEIROKLYUCH-456 --json
   ```
   Возвращает:
   - текущую фазу
   - выполненные фазы
   - все 30 фаз с инструкциями/чеками/evidence
   - историю переходов
   - статус repeatable checks

---

## Тесты

```bash
pytest tests/ -q
# 151 passed
```

---

## Настройки

Хранятся в `~/.wartz-workflow/settings.json`:

```json
{
  "jira_base_url": "https://jira.company.com",
  "gitlab_base_url": "https://gitlab.company.com",
  "gitlab_project_id": "42",
  "ui_port": 8811,
  "ui_host": "0.0.0.0",
  "key_patterns": [
    "^TASKNEIROKLYUCH-(?P<number>[0-9]+)$"
  ]
}
```

---

## License

MIT
