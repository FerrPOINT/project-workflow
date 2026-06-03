# Архитектура wartz-workflow

> Текущее состояние — flat modules, SQLite-first, CLI + Web UI.

---

## Принципы

1. **CLI-first** — всё основное через `hrflow` команду
2. **State-driven** — не job queue, а phase transitions
3. **Flat modules** — никаких `application/`, `domain/`, `infrastructure/`
4. **SQLite canonical** — `seed.json` загружается в SQLite, всё читаем из DB
5. **Controller → Service → Data Access** — layered внутри модуля, не между директориями

---

## Диаграмма

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   CLI Layer     │     │   Web UI Layer  │     │   Agent Layer   │
│  (cli/commands) │     │  (ui.py / Jinja2)│    │  (wizard.py)    │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────▼─────────────┐
                    │      Service Layer        │
                    │    (service.py:           │
                    │     PhaseService)          │
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │      Data Access Layer    │
                    │    (db.py: WorkflowDB)     │
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │        SQLite             │
                    │   ~/.wartz-workflow/       │
                    │      workflow.db           │
                    └─────────────────────────────┘
```

---

## Модули

| Модуль | Ответственность | Строки | Тесты |
|--------|-----------------|--------|-------|
| `cli/commands.py` | CLI: init, wizard, wizard-context, status, verify | 269 | — |
| `cli/ui.py` | CLI: `hrflow ui --port` | 57 | — |
| `ui.py` | FastAPI routes, Jinja2 templates | 776 | test_ui.py |
| `service.py` | PhaseService: bulk save, ID return | 120 | test_ui.py |
| `db.py` | SQLite CRUD: phases, instructions, checks, evidence, agents | 600+ | test_db.py |
| `db_schema.sql` | DDL | 80 | — |
| `schema.py` | seed.json → SQLite loader, YAML fallback | 200 | — |
| `models.py` | Domain dataclasses | 80 | — |
| `wizard.py` | WizardEngine: evaluate, get_full_context, get_phase_prompt | 417 | test_wizard_context.py, test_wizard.py |
| `conversation.py` | SQLite: transitions, questions, answers | 192 | — |
| `phases.py` | phase_map, get_next_phase | 175 | test_phases.py |
| `config.py` | settings.json, DEFAULT_SETTINGS | 120 | test_ui.py |
| `task_validator.py` | Task key regex validation | 245 | test_task_validator.py |
| `profiles.py` | Agent profiles | 188 | test_profiles.py |
| `verify.py` | verify-suite.sh runner | 86 | test_verify.py |
| `rollback.py` | Git rollback | 151 | test_rollback.py |
| `engine.py` | Declarative engine | 256 | — |
| `state.py` | progress.json + git ops | 205 | test_state.py |

---

## Данные

### Canonical source: `references/seed.json`

30 фаз с полным описанием:
```json
{
  "phases": [
    {
      "id": "-1", "name": "Task Intake", "phase_num": 1,
      "description": "...",
      "skills": ["workflow-requesting-code-review"],
      "instructions": [...],
      "checks": [...],
      "evidence": [...]
    }
  ]
}
```

### DB Schema

```sql
phases          (id, name, description, phase_order, skills, ...)
instructions    (id, phase_id, step_num, description, execution_type, tool)
checks          (id, phase_id, description, optional)
evidence        (id, phase_id, item, validator)
questions       (id, phase_id, qtext, required, expected_keywords)
agents          (id, name, description)
conversations   (id, task_id, jira_key, role, phase_id, content, tags, created_at)
```

---

## CLI Flow

```
hrflow init TASK-456 → создаёт info/ + progress.json
     ↓
hrflow wizard TASK-456 → показывает инструкции текущей фазы
     ↓
# агент работает...
     ↓
hrflow wizard TASK-456 --report "сделал X" → wizard.evaluate()
     ↓
PASS → next phase
FAIL → retry
```

---

## UI Flow

```
/ → dashboard
/phases → Kanban (drag between columns)
/phase/{id} → редактирование фазы (autosave)
/execution → DND graph (reorder + merge parallel)
/settings → конфигурация
/wizard/{id} → прохождение фазы
```

---

## Wizard Flow

```
agent report
    ↓
WizardEngine.evaluate(report)
    ↓
_build_checklist(phase)  ← instructions + checks + evidence
    ↓
_check_coverage(report, checklist)  ← keyword matching
    ↓
_check_repeatable(report)  ← 3 обязательных задания
    ↓
PASS / FAIL
```

---

## State Machine

```
┌─────────┐     sync      ┌─────────┐     parallel    ┌─────────┐
│  Phase  │ ─────────────→│  Phase  │ ─────────────→│  Phase  │
│   -1    │               │   0.6   │               │   1     │
│ Intake  │               │Researcher#1│               │ Context │
└─────────┘               └────┬────┘               └─────────┘
                               │
                          ┌────┴────┐
                          │  Phase  │
                          │  0.6b   │
                          │ Deep R  │
                          └────┬────┘
                               │
                          ┌────┴────┐
                          │  JOIN   │
                          │ sync    │
                          └─────────┘
```

- **sync** — ждём предыдущую
- **parallel** — выполняются одновременно, JOIN ждёт всех
- **blocker** — hard stop, нельзя пропустить
- **delegated** — назначен агент
- **critic** — review gate

---

## Anti-patterns (запрещено)

| ❌ Запрещено | Почему |
|-------------|--------|
| `application/`, `domain/`, `infrastructure/` | Circular imports, сломалось |
| `phases.yaml` | Устарело, canonical = `seed.json` |
| Inline CSS в Python | ~20KB мусора, нет подсветки |
| `subprocess(shell=True)` | Безопасность, тестируемость |
| Singleton DB без сессий | Гонки в параллельных тестах |

---

## Тесты

```bash
pytest tests/ -q
# 151 passed
```

| Модуль | Тесты |
|--------|-------|
| test_ui.py | Web UI endpoints |
| test_graph.py | Execution batches + DND |
| test_db.py | SQLite CRUD |
| test_wizard_context.py | WizardEngine.get_full_context() |
| test_wizard.py | wizard CLI |
| test_phases.py | phase_map |
| test_task_validator.py | key validation |
| test_profiles.py | profiles |
| test_rollback.py | rollback |
| test_state.py | state |
| test_verify.py | verify-suite |
| test_adapters.py | adapters |

---

## Settings

```json
~/.wartz-workflow/settings.json
{
  "jira_base_url": "...",
  "gitlab_base_url": "...",
  "gitlab_project_id": "...",
  "ui_port": 8811,
  "ui_host": "0.0.0.0",
  "key_patterns": ["^TASKNEIROKLYUCH-(?P<number>[0-9]+)$"]
}
```
