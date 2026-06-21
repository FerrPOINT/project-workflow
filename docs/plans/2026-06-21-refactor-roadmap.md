# План рефакторинга `project_workflow` (без расширения CLI)

> Правило проекта: CLI остаётся ровно с двумя командами — `step` и `history`. Весь CRUD workflows/phases/projects/agents и администрирование выполняется через Web UI. Новые CLI-команды запрещены.

## Цель

Привести проект к production-ready архитектуре:
- один data layer (SQLAlchemy services/repositories);
- полная типизация (`mypy project_workflow/` — зелёный);
- UI routes работают через application services, а не legacy `WorkflowDB`;
- wizard/core логика декомпозирована и типизирована;
- тесты остаются зелёными на каждом этапе.

---

## Этап 1. Подготовка и стабилизация

| Задача | Что делать | Контрольный результат |
|---|---|---|
| 1.1 Зафиксировать архитектурные правила | Добавить в `README.md` и `docs/ARCHITECTURE.md` запрет на новые CLI-команды и принцип "весь CRUD через UI". | Раздел "Архитектура и ограничения" в `README.md`. |
| 1.2 Утвердить границы слоёв | Описать: `domain/` — модели + интерфейсы; `infrastructure/db/` — SQLAlchemy реализации; `application/` — use-case сервисы; `project_workflow/ui/` — presentation; `project_workflow/db/` — legacy SQLite (только до миграции). | `docs/ARCHITECTURE.md`. |
| 1.3 Усилить тестовый контракт UI | В `tests/test_ui_api.py` добавить JSON-schema проверки ответов `/api/*`, чтобы рефакторинг endpoint'ов не ломал контракт. | Новые тесты проходят. |
| 1.4 Заморозить CLI | Проверить, что `test_only_two_commands_allowed` всё ещё ловит любую новую команду; при необходимости усилить assert. | `pytest tests/test_ui.py::test_only_two_commands_allowed` green. |

---

## Этап 2. Дополнить application-сервисы до полного CRUD

| Сервис | Что добавить | Почему |
|---|---|---|
| `PhaseServiceApp` | `save_instructions`, `save_checks`, `save_evidence`, `reorder_phases`, `delete_workflow_phases`. | UI редактирует фазы и их вложенные сущности; workflow delete требует каскадного удаления фаз. |
| `TaskService` | `list_tasks`, `delete_task`, `set_current_phase`. | UI `/tasks` и `/task/{task_key}` нуждаются в полноценном CRUD. |
| `WorkflowService` | `reorder_phases`, `delete_workflow_with_phases`. | Сейчас в `api_workflow_delete` raw SQL `DELETE FROM phases`. |
| `ProjectService` | уже есть CRUD, но уточнить валидацию `key_patterns`. | `key_patterns` — source of truth для `TaskKeyValidator`. |
| `AgentService` | уже есть CRUD; проверить completeness. | — |

### Контрольные результаты этапа 2
- `tests/test_application_services.py` удвоился и покрывает все новые методы.
- Ни один endpoint UI не использует `WorkflowDB` для create/update/delete.

---

## Этап 3. Перевести UI API на application-сервисы

### Файлы
- `project_workflow/ui/routes/api.py`

### Задачи
- [ ] `api_phases`, `api_phase_create`, `api_phase_update`, `api_phase_delete` — через `PhaseServiceApp` + Pydantic-схемы.
- [ ] `api_workflow_create`, `api_workflow_update`, `api_workflow_delete` — через `WorkflowService`; удалить raw SQL.
- [ ] `api_project_*` — через `ProjectService`.
- [ ] `api_agent_*` — через `AgentService`.
- [ ] `api_tasks`, `api_task_detail`, `api_task_set_phase` — через `TaskService`.
- [ ] Сохранить response shape, чтобы `tests/test_ui*.py` не сломались.

### Контрольный результат
- `project_workflow/ui/routes/api.py` не содержит `wdb.create_phase`, `wdb.update_phase`, `wdb.delete_phase`, `DELETE FROM phases`.
- `pytest tests/test_ui*.py` — green.

---

## Этап 4. Перевести wizard и CLI на application-сервисы

### Файлы
- `project_workflow/wizard.py`
- `project_workflow/wizard_context.py`
- `project_workflow/wizard_store.py`
- `project_workflow/service.py`
- `project_workflow/cli/core.py`
- `project_workflow/cli/ui.py`

### Задачи
- [ ] Создать read-only/audit сервисы для wizard: `SupervisorRunService`, `TaskHistoryService`.
- [ ] `WizardEngine` читает фазы/проекты/задачи через `PhaseServiceApp`, `ProjectService`, `TaskService` вместо `WorkflowDB`.
- [ ] `cli/ui.py` `history_cmd` читает supervisor runs через `SupervisorRunService`.
- [ ] `cli/core.py` `_get_task_key_validator` получает проекты через `ProjectService`.
- [ ] `service.py` `PhaseService` убрать после переноса его методов в `PhaseServiceApp`.

### Контрольный результат
- `WorkflowDB` больше не импортируется в `wizard.py`, `wizard_context.py`, `wizard_store.py`, `service.py`, `cli/ui.py`, `cli/core.py`.
- Все wizard-тесты green.

---

## Этап 5. Удалить/сузить legacy `WorkflowDB`

### Файлы
- `project_workflow/db/base.py`
- `project_workflow/db/__init__.py`
- `project_workflow/db/db_schema.sql` (оставить как DDL-справочник)

### Задачи
- [ ] Перенести оставшиеся raw-SQL методы, которые нужны для UI seed/миграций, в SQLAlchemy.
- [ ] Методы `ensure_default_workflows`, `sync_phase_catalog`, seed-import перенести в `infrastructure/db/seed.py` или `application/seed_service.py`.
- [ ] Удалить `WorkflowDB` как класс.
- [ ] Обновить `tests/test_db*.py`, чтобы они тестировали SQLAlchemy repositories/services, а не `WorkflowDB`.

### Контрольный результат
- Raw SQL в production-коде = 0 (кроме миграций Alembic).
- `mypy project_workflow/db/` — green или директория удалена.

---

## Этап 6. Типизация и декомпозиция wizard

### Файлы
- `project_workflow/wizard.py`
- `project_workflow/wizard_evaluate.py`
- `project_workflow/wizard_checks.py`

### Задачи
- [ ] Вынести из `WizardEngine`:
  - `_get_parallel_group` → `project_workflow/wizard_logic/parallel.py`
  - `_build_parallel_checklist` → `project_workflow/wizard_logic/checklist.py`
  - `_build_checklist` → `project_workflow/wizard_logic/checklist.py`
  - `_check_coverage` → `project_workflow/wizard_logic/coverage.py`
  - `_extract_blockers` → `project_workflow/wizard_logic/blockers.py`
  - `_determine_verdict` → `project_workflow/wizard_logic/verdict.py`
  - `_get_next_phase`, `_get_next_phase_after_group` → `project_workflow/wizard_logic/transitions.py`
- [ ] `format_result` перенести в `project_workflow/ui/format.py` (presentation layer) или `project_workflow/cli/format.py`.
- [ ] Добавить типы всем параметрам и возвращаемым значениям.

### Контрольный результат
- `mypy project_workflow/wizard*.py` — зелёный.
- `WizardEngine` < 60 строк на метод; логика — в `wizard_logic/`.

---

## Этап 7. Разделить `db/base.py` по доменам

> Выполняется параллельно с этапом 5, если разработчик уверен в SQLAlchemy-слое.

| Домен | Новый файл | Что переносить |
|---|---|---|
| Workflows | `infrastructure/db/repositories/workflows.py` | `SAWorkflowRepository` (уже есть) |
| Phases | `infrastructure/db/repositories/phases.py` | `SAPhaseRepository` (уже есть) |
| Projects | `infrastructure/db/repositories/projects.py` | `SAProjectRepository` (уже есть) |
| Tasks | `infrastructure/db/repositories/tasks.py` | `SATaskRepository` (уже есть) |
| Agents | `infrastructure/db/repositories/agents.py` | `SAAgentRepository` (уже есть) |
| Supervisor runs | `infrastructure/db/repositories/supervisor_runs.py` | `SASupervisorRunRepository` (уже есть) |
| Seed/migration helpers | `infrastructure/db/seed.py` | `ensure_phase_catalog`, `sync_phase_catalog`, `_ensure_default_workflows` |

### Контрольный результат
- `project_workflow/db/base.py` удалён.
- `mypy` green.

---

## Этап 8. Улучшить конфигурацию и runtime-константы

### Файлы
- `project_workflow/config.py`
- `project_workflow/schema.py`
- `project_workflow/ui/dependencies.py`

### Задачи
- [ ] Заменить глобальные mutable `PHASE_ORDER` и `LEGACY_PHASE_REDIRECTS` на функции, читающие из БД.
- [ ] `ensure_phase_catalog` вызывать явно при seed/bootstrap, а не на каждый `get_db()`.
- [ ] В `_AppState.get_db()` убрать автоматический seed-resync; сделать `seed()` отдельным методом/CLI-командой.
- [ ] Добавить `from __future__ import annotations` в файлы, где отсутствует.

### Контрольный результат
- Повторный запуск UI не затирает ручную reorder-затем фазы.
- Тест `test_phases_order_api_persists_reordered_default_workflow_sequence` проходит.

---

## Этап 9. Рефакторинг UI helper'ов

### Файлы
- `project_workflow/ui/services.py`

### Задачи
- [ ] Разбить `_get_task_detail` (158 строк) на:
  - `_build_phase_history`
  - `_build_supervisor_runs`
  - `_build_task_progress`
  - `_build_next_contract`
- [ ] Вынести `_load_dashboard`, `_load_phases`, `_load_projects` в `project_workflow/ui/queries.py` или `project_workflow/ui/use_cases/`.
- [ ] Удалить дублирование `_load_workflows` / `_load_phases` / `_load_projects`.

### Контрольный результат
- Нет функций > 80 строк в `project_workflow/ui/`.
- Unit-тесты на UI helpers проходят.

---

## Этап 10. Mypy green по всему проекту

| Файл | Ошибок сейчас | Как чинить |
|---|---|---|
| `project_workflow/db/base.py` | 68 | удаляется на этапе 5 |
| `project_workflow/infrastructure/db/repositories.py` | 50 | типизация Column/Model; разделение по файлам |
| `project_workflow/wizard.py` | 39 | этап 6 |
| `project_workflow/application/__init__.py` | 15 | return types + параметры |
| `project_workflow/schema.py` | 11 | generic dict + seed helpers |
| `project_workflow/infrastructure/db/migrations/...` | 11 | оставить как есть или `# type: ignore` |

### Контрольный результат
- `python -m mypy project_workflow/ --ignore-missing-imports` — **0 errors**.

---

## Этап 11. Рефактор тестов

| Что | Почему | Как |
|---|---|---|
| UI-тесты | слишком много знают о internal helpers | вынести contract tests в `tests/test_ui_api_contract.py` |
| БД-тесты | тестируют legacy `WorkflowDB` | переписать на repositories/services |
| Wizard-тесты | часто интеграционные | добавить unit-тесты на `wizard_logic/*` |

### Контрольный результат
- Тесты быстрее; 727+ тестов green.

---

## Порядок работы (рекомендуемый)

1. Этап 1 — зафиксировать правила.
2. Этап 2 + Этап 3 — application services + UI API.
3. Этап 4 — wizard/CLI на сервисы.
4. Этап 5 + 7 — удаление `WorkflowDB`.
5. Этап 6 — декомпозиция wizard.
6. Этап 8 — конфиг/seed.
7. Этап 9 — UI helpers.
8. Этап 10 — mypy green.
9. Этап 11 — переработка тестов.

> Каждый этап должен заканчиваться: `ruff check`, `mypy project_workflow/ui/`, `pytest -q` green.

---

## Архитектурные запреты (must-have)

- ❌ Новые команды в CLI. Только `step` и `history`.
- ❌ Raw SQL вне Alembic-миграций.
- ❌ UI routes работают с `WorkflowDB` напрямую.
- ❌ Глобальный `_AppState` без `reset()` между тестами.
- ❌ Добавление новых шаблонов/страниц без тестов на контракт API.

## Архитектурные принципы (should-have)

- ✅ Application services — единая точка входа для бизнес-логики.
- ✅ UI routes только валидируют input, вызывают сервис, формируют response.
- ✅ Domain-модели не знают о SQLAlchemy; infrastructure реализует интерфейсы из `domain/repositories.py`.
- ✅ Seed/sync — явная операция, не side-effect при каждом запросе.
