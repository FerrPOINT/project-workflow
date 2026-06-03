# План: CRUD фаз workflow на SQLite

> Применены скиллы: `test-driven-development`, `workflow-writing-plans`, `fastapi-admin-dashboard`

---

## Цель

Заменить YAML-runtime на SQLite. Дать CRUD API и UI для управления фазами, инструкциями, проверками, evidence и чекапами.

---

## Схема (итоговая — 5 таблиц)

| Таблица | Поля | Зачем |
|---------|------|-------|
| **phases** | `id`, `name`, `description`, `phase_order`, `skills` (JSON) | Карточка фазы |
| **instructions** | `id`, `phase_id`, `step_num`, `description`, `execution_type` (sync/parallel), `tool` | Шаги внутри фазы |
| **checks** | `id`, `phase_id`, `description`, `command` | Ручные проверки (гейты) |
| **evidence** | `id`, `phase_id`, `description` | Что собрать агенту |
| **checkups** | `id`, `phase_id`, `name`, `check_type`, `target`, `interval_min`, `last_status`, `last_run`, `fail_action` | Авто/периодические проверки |

---

## 1. База данных (`wartz_workflow/db.py`)

- [ ] **Task 1.1.** Класс `WorkflowDB`
  - `init(db_path)` — создаёт таблицы из `db_schema.sql`
  - `import_phases(phases: list[Phase])` — заливает YAML в SQLite (разово)
  - `get_phases() -> list[dict]` — все фазы с `phase_order`
  - `get_phase(phase_id) -> dict` — фаза + instructions + checks + evidence + checkups

- [ ] **Task 1.2.** CRUD фаз
  - `create_phase(data)`, `update_phase(id, data)`, `delete_phase(id)` (каскадом)

- [ ] **Task 1.3.** CRUD instructions
  - `add_instruction(phase_id, data)`, `update_instruction(id, data)`, `delete_instruction(id)`
  - `reorder_instructions(phase_id, ids[])` — поменять порядок

- [ ] **Task 1.4.** CRUD checks
  - `add_check(phase_id, data)`, `update_check(id, data)`, `delete_check(id)`

- [ ] **Task 1.5.** CRUD evidence
  - `add_evidence(phase_id, data)`, `update_evidence(id, data)`, `delete_evidence(id)`

- [ ] **Task 1.6.** CRUD checkups
  - `add_checkup(phase_id, data)`, `update_checkup(id, data)`, `delete_checkup(id)`
  - `run_checkup(id)` — выполнить проверку, обновить `last_status` + `last_run`
  - `get_pending_checkups()` — чекапы которые пора проверить

- [ ] **Task 1.7.** Тесты `tests/test_db.py` **(RED → GREEN)**
  - init, import 2 фаз, get_phases, get_phase с инструкциями, чекапами
  - CRUD each table

- [ ] **Verify:** `pytest tests/test_db.py -v` — все проходят

---

## 2. CRUD API (`wartz_workflow/api.py` или в `ui.py`)

- [ ] **Task 2.1.** Phases
  - `GET    /api/phases`          → список
  - `GET    /api/phases/{id}`     → деталь (со всеми связанными)
  - `POST   /api/phases`          → создать
  - `PATCH  /api/phases/{id}`     → обновить name/description/skills
  - `DELETE /api/phases/{id}`     → удалить каскадом

- [ ] **Task 2.2.** Instructions
  - `POST   /api/phases/{id}/instructions`  → добавить шаг
  - `PATCH  /api/instructions/{id}`           → обновить
  - `DELETE /api/instructions/{id}`         → удалить
  - `POST   /api/phases/{id}/instructions/reorder` → поменять порядок

- [ ] **Task 2.3.** Checks
  - `POST   /api/phases/{id}/checks`        → добавить
  - `PATCH  /api/checks/{id}`               → обновить
  - `DELETE /api/checks/{id}`              → удалить

- [ ] **Task 2.4.** Evidence
  - `POST   /api/phases/{id}/evidence`      → добавить
  - `PATCH  /api/evidence/{id}`             → обновить
  - `DELETE /api/evidence/{id}`             → удалить

- [ ] **Task 2.5.** Checkups
  - `POST   /api/phases/{id}/checkups`      → добавить чекап
  - `PATCH  /api/checkups/{id}`            → обновить
  - `POST   /api/checkups/{id}/run`         → запустить проверку
  - `DELETE /api/checkups/{id}`             → удалить
  - `GET    /api/checkups/pending`          → получить просроченные

- [ ] **Task 2.6.** Тесты `tests/test_api.py` **(RED → GREEN)**
  - ~20 тестов на весь CRUD

- [ ] **Verify:** `pytest tests/test_api.py -v` — все проходят

---

## 3. UI на чтение из SQLite + формы редактирования

- [ ] **Task 3.1.** Заменить `load_phases()` в `ui.py`
  - Читать из `WorkflowDB.get_phases()` вместо `schema.load_phases()`

- [ ] **Task 3.2.** Форма редактирования фазы
  - `GET /phase/{id}/edit` — форма: name, description, skills (JSON textarea)
  - `POST /phase/{id}/edit` — сохранить → редирект на detail

- [ ] **Task 3.3.** Управление инструкциями в UI
  - Список с drag-n-drop сортировкой (или ↑↓ кнопками)
  - Кнопка "Добавить" → поля: description, execution_type (select), tool

- [ ] **Task 3.4.** Управление checks в UI
  - Список, добавить: description + command textarea

- [ ] **Task 3.5.** Управление evidence в UI
  - Аналогично — простые textarea

- [ ] **Task 3.6.** Чекапы в UI
  - Список чекапов фазы с бейджем статуса (ok/fail/running/unknown)
  - Кнопка "Добавить": name, check_type (select), target, interval (мин), fail_action (select)
  - Кнопка "▶ Запустить" → POST /api/checkups/{id}/run, рефреш страницы
  - Бейдж цвета: зелёный=ok, красный=fail, жёлтый=running, серый=unknown

- [ ] **Verify:** `pytest tests/test_ui.py -v` + ручная проверка

---

## 4. CLI и авто-инициализация базы

- [ ] **Task 4.1.** Авто-инициализация при старте UI
  - При старте `python -m wartz_workflow.ui` проверить `~/.wartz-workflow/workflow.db`
  - Если БД не существует — создать и `import_phases()` из YAML (разово)

- [ ] **Task 4.2.** Команда `hrflow workflow TASK-123 "отчёт..."`
  - Текущая команда — читает текущую фазу из БД, записывает отчёт

- [ ] **Task 4.3.** Команда `hrflow done-list TASK-123`
  - Текущая команда — показывает выполненные фазы из БД

- [ ] **Verify:** Старт UI → БД создана → `sqlite3 ~/.wartz-workflow/workflow.db ".tables"`

---

## 5. Итоговая проверка

- [ ] `pytest tests/ -q` — все тесты зелёные
- [ ] `ruff check .` — линтер чистый
- [ ] UI `/phases` — 30 фаз, номера №1–№30
- [ ] UI `/phase/1/edit` — форма редактирования работает
- [ ] UI чекапы: бейджи ok/fail/running, кнопка запуска
- [ ] API `GET /api/phases/{id}` — JSON со всеми связанными сущностями
- [ ] CLI `hrflow db-init` + `hrflow checkup-run` работают
- [ ] Commit + push

---

## Структура файлов (итог)

| Файл | Назначение |
|------|------------|
| `wartz_workflow/db_schema.sql` | DDL — 5 таблиц |
| `wartz_workflow/db.py` | Класс WorkflowDB — CRUD SQLite |
| `wartz_workflow/api.py` | FastAPI CRUD JSON API (опционально отдельно) |
| `wartz_workflow/ui.py` | FastAPI + HTML рендер (чтение + формы) |
| `wartz_workflow/templates/edit_phase.html` | Форма редактирования |
| `tests/test_db.py` | Тесты на SQLite |
| `tests/test_api.py` | Тесты на CRUD API |
| `docs/plan-db-crud.md` | Этот план |
