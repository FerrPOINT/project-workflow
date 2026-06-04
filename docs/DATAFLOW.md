# DATAFLOW — основной поток данных

> Как данные движутся через систему: от seed до SQLite, от CLI до UI, от агента до wizard.

---

## 1. Инициализация системы (cold start)

```
references/seed.json
        ↓
   schema.py  ──load_phases()──→  list[Phase] (dataclasses)
        ↓
   ui.py  ──startup_event()──→  if DB empty:
        ↓
   _seed_to_sqlite()  ──INSERT──→  SQLite: phases, instructions, checks, evidence
        ↓
   workflow.db  ←──canonical source──→  все UI + API читают отсюда
```

**Правило:** `seed.json` загружается **один раз** при первом старте. После этого правда — в SQLite. Изменения через UI `/phase/{id}` или API `PUT /api/phases/{id}`.

---

## 2. Агент выполняет задачу

```
Агент
  │
  ├─→ hrflow init TASKNEIROKLYUCH-456 → создаёт info/ + progress.json
  │
  ├─→ hrflow wizard TASKNEIROKLYUCH-456 → получает инструкции фазы -1
  │
  │     wizard.py::get_phase_prompt() → берёт из SQLite (db.py::get_phase)
  │                           ↓
  │                    Фаза -1 (Task Intake)
  │                    ❗ Обязательно:
  │                       1. Прочитать Jira тикет
  │                       2. Понять задачу
  │                       3. Залогировать
  │
  │  # Агент работает...
  │
  ├─→ hrflow wizard TASKNEIROKLYUCH-456 \
  │       --report "Прочитал тикет, понял задачу, создал info/TASKNEIROKLYUCH-456_task.md"
  │
  │     wizard.py::evaluate(report)
  │        ↓
  │     _build_checklist(phase)  ←  instructions + checks + evidence из SQLite
  │        ↓
  │     _check_coverage(report, checklist)  ←  keyword matching
  │        ↓
  │     _check_repeatable(report)  ←  3 обязательных задания
  │        ↓
  │     PASS  →  next_phase = "0.0a" (Suite Verification)
  │        ↓
  │     conversation.py::add_phase_transition()  →  SQLite: transitions
  │
  │  # Следующая фаза...
  │
  └─→ hrflow wizard TASKNEIROKLYUCH-456 --report "..."
        ↓
     # ... и так до фазы 8 (Jira Done)
```

**Важно:** wizard НЕ делает Jira transition. Это отдельный шаг агента через `wartz-jira`.

---

## 3. UI показывает состояние

```
Пользователь открывает http://localhost:8811
        ↓
   GET /
        ↓
   ui.py::dashboard()  →  _get_db()::get_phases()  →  SQLite
        ↓
   Jinja2::dashboard.html  ←  phases (30 штук)
        ↓
   Браузер рендерит карточки
```

### /phases — Kanban
```
GET /phases
   ↓
ui.py::phases()  →  _get_db()::get_phases()  →  group_by(PHASE_TO_GROUP)
   ↓
templates/v2/phases.html  ←  6 групп: SETUP, RESEARCH, PLAN, DEV, QA, CLOSURE
```

### /phase/{id} — Редактирование
```
GET /phase/-1
   ↓
ui.py::phase_detail()  →  _get_service()::get_phase()  →  SQLite
   ↓
templates/v2/phase_detail.html  ←  phase + instructions + checks + evidence

# Пользователь редактирует
onblur → scheduleSave() → PUT /api/phases/-1
   ↓
ui.py::api_phase_update()  →  PhaseService::save_phase()  →  SQLite INSERT/UPDATE
   ↓
JSON response: {ok: true, ids: {...}}
```

### /execution — Граф
```
GET /execution
   ↓
ui.py::execution()  →  _build_execution_batches()  →  sync + parallel groups
   ↓
templates/v2/execution.html  ←  batches + Mermaid graph

# DND reorder
ondrop → PUT /api/phases/order  →  update phase_order в SQLite

# Merge parallel
ondrop на другой узел → PUT /api/phases/parallel  →  update parallel_with
```

### /settings — Конфигурация
```
GET /settings
   ↓
ui.py::settings_page()  →  config.load_settings()  →  ~/.wartz-workflow/settings.json
   ↓
templates/v2/settings.html  ←  key_patterns, jira_url, gitlab_url, port, host

# Сохранение
PUT /api/settings  →  config.save_settings()  →  settings.json
```

---

## 4. Wizard API для агента

```
GET /api/wizard/TASKNEIROKLYUCH-456/context
   ↓
ui.py::api_wizard_context()  →  WizardEngine::get_full_context()
   ↓
   ├─→ conversation.py::get_messages()  →  SQLite (transitions, notes)
   ├─→ schema.py::load_phases()  →  seed.json (fallback) / SQLite
   └─→ wizard.py::_check_repeatable()  →  статус
   ↓
JSON: {jira_key, current_phase, all_phases, completed_phases, repeatable_checks, ...}
```

```
POST /api/wizard/TASKNEIROKLYUCH-456/evaluate
Body: {"report": "..."}
   ↓
ui.py::api_wizard_evaluate()  →  WizardEngine::evaluate(report)
   ↓
   ├─→ _build_checklist()  →  SQLite
   ├─→ _check_coverage()  →  keyword matching
   ├─→ _check_repeatable()  →  3 задания
   └─→ _get_next_phase()  →  phases.py
   ↓
JSON: {verdict, covered, missing, next_phase, message}
```

---

## 5. Хранение данных

### SQLite: `~/.wartz-workflow/workflow.db`

| Таблица | Что хранит | Кто пишет | Кто читает |
|---------|-----------|-----------|------------|
| `phases` | Фазы (id, name, description, order, skills, execution_type, delegate_agent, rollback_target) | `_seed_to_sqlite()` на старте, `PhaseService.save_phase()` | Все страницы |
| `instructions` | Инструкции фазы (step_num, description, execution_type, tool) | `save_phase()` | `phase_detail.html`, wizard |
| `checks` | Чеки (description, optional) | `save_phase()` | wizard, `phase_detail.html` |
| `evidence` | Evidence (item, validator) | `save_phase()` | wizard, `phase_detail.html` |
| `questions` | Вопросы wizard (qtext, required, expected_keywords) | `_seed_to_sqlite()` | `wizard.html` |
| `agents` | Агенты (name, description) | `_seed_to_sqlite()` | `phase_detail.html` (dropdown) |
| `conversations` | История (task_id, jira_key, role, phase_id, content, tags, created_at) | `conversation.py` | wizard context |

### JSON: `~/.wartz-workflow/settings.json`

```json
{
  "jira_base_url": "...",
  "gitlab_base_url": "...",
  "gitlab_project_id": "...",
  "ui_port": 8811,
  "ui_host": "0.0.0.0",
  "key_patterns": ["^TASKNEIROKLYUCH-(?P<number>[0-9]+)$"]
}
```

**Кто пишет:** `config.save_settings()` (из UI Settings page)
**Кто читает:** `config.load_settings()` (UI port, key validation)

### Файлы проекта: `info/`

- `TASKNEIROKLYUCH-456_task.md` — описание задачи
- `progress.json` — текущая фаза
- `changelog.md` — история изменений
- `phase_X_log.md` — лог работы по фазе

**Кто пишет:** Агент (вручную или через команды)
**Кто читает:** Wizard (проверяет repeatable checks)

---

## 6. State Machine

```
┌─────────────┐     sync      ┌─────────────┐     parallel    ┌─────────────┐
│   Phase -1  │ ─────────────→│   Phase 0.6 │ ─────────────→│   Phase 1   │
│   Intake    │               │  Researcher#1│              │   Context   │
└─────────────┘               └──────┬──────┘               └─────────────┘
                                     │
                              ┌──────┴──────┐
                              │   Phase 0.6b│
                              │  Deep R     │
                              └──────┬──────┘
                                     │
                              ┌──────┴──────┐
                              │     JOIN    │
                              │   (sync)    │
                              └─────────────┘
```

- **sync** — выполняется последовательно, ждёт предыдущую
- **parallel** — в одном batch, выполняются одновременно
- **JOIN** — ждёт завершения всех parallel веток
- **blocker** — hard stop, нельзя пропустить
- **delegated** — назначен конкретный агент
- **rollback_target** — при FAIL → откат к указанной фазе

---

## 7. Типичный цикл работы

```
1. hrflow init TASK-456
   → создаёт info/, progress.json

2. hrflow wizard TASK-456
   → показывает фазу -1 + инструкции

3. # Агент работает
   → читает Jira, пишет task.md, логирует

4. hrflow wizard TASK-456 --report "сделал X, Y, Z"
   → wizard.evaluate() → PASS → фаза 0.0a

5. # Фаза 0.0a (Suite Verification)
   → запускает verify-suite.sh

6. hrflow wizard TASK-456 --report "verify-suite.sh PASS"
   → PASS → фаза 0.01

7. # ... и так до фазы 8

8. # Фаза 8 (Jira Done)
   → агент делает wartz-jira transition TASK-456 "Выполнено"
   → wizard.evaluate() → PASS → COMPLETE
```

---

## 8. Anti-patterns (запрещённые потоки)

| ❌ Запрещено | Почему |
|-------------|--------|
| UI напрямую пишет в `seed.json` | SQLite — canonical, seed.json только для инициализации |
| Агент читает `phases.yaml` | Устарело, canonical в SQLite |
| Wizard делает Jira transition | Wizard — gate evaluator, не integrator. Jira — отдельный шаг |
| UI делает API calls к Jira/GitLab | UI state-driven. Агент дергает CLI для интеграций |
| `progress.json` как canonical state | Для инфо, SQLite для атомарных операций |

---

## 9. Схема взаимодействия модулей

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│    CLI       │      │    Web UI    │      │   Agent      │
│  (commands)  │      │   (ui.py)    │      │  (wizard)    │
└──────┬───────┘      └──────┬───────┘      └──────┬───────┘
       │                     │                     │
       └─────────────────────┼─────────────────────┘
                             │
                    ┌────────┴────────┐
                    │  WizardEngine     │
                    │  (evaluate)       │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │  PhaseService     │
                    │  (save_phase)     │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │  WorkflowDB       │
                    │  (db.py)          │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │  SQLite           │
                    │  workflow.db      │
                    └─────────────────┘
```
