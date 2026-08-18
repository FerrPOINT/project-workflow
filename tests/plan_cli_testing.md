# План тестирования CLI — выполнен

## Окружение

```bash
export DATABASE_URL=''
export WORKFLOW_DIR=/tmp/pw_manual_cli
```

## Выполненные шаги

### 1. Исправить состав фаз в `seed.json`

| Группа | Было | Стало |
|---|---|---|
| `0.6` ↔ `1` | `0.6` parallel → `1`, `1` sync | оба `parallel`, взаимно |
| `1.5` ↔ `2` | `1.5` parallel → `2`, `2` sync | оба `parallel`, взаимно |
| `4.5` ↔ `5` | `4.5` parallel → `5`, `5` sync | оба `parallel`, взаимно |
| `7.5` ↔ `7.6` ↔ `7.6.R` | `7.5` sync → `7.6`, остальные parallel | все `parallel` |

### 2. Проверить `smoke_seed.json`

- `smoke.parallel-a` ↔ `smoke.parallel-b` взаимно.
- Все инструкции в parallel-фазах имеют `execution_type=parallel`.

### 3. Исправить `DB_PATH`

- Добавлена функция `get_db_path()` в `project_workflow/infrastructure/db/__init__.py`.
- `SAUnitOfWork` теперь использует `get_db_path()` вместо кешированного `DB_PATH`.
- `WORKFLOW_DIR` из env теперь работает в одном процессе.

### 4. Создать автоматический e2e тест

- `tests/manual_workflow_seed.json` — кастомный workflow с параллельными/последовательными фазами и инструкциями.
- `tests/test_cli_manual_workflow.py` — 7 тестов на Click runner.

### 5. Ручное тестирование через CLI

| # | Команда | exit | Наблюдение |
|---|---|---|---|
| 1 | `step --task MANUAL-1` | 0 | `manual.intake`, список инструкций/чекапов/доказательств |
| 2 | `step --task MANUAL-2 --report <intake>` | 0 | PASS, `manual.intake` → `manual.plan` |
| 3 | `step --task MANUAL-3 --report <plan>` | 0 | PASS, `manual.plan` → `manual.parallel-a` |
| 4 | `step --task MANUAL-3 --report <partial>` | 0 | SOFT_FAIL, остался в `manual.parallel-a`, missing frontend |
| 5 | `step --task MANUAL-3 --report <full>` | 0 | PASS, `manual.parallel-a` → `manual.seq-instr` |
| 6 | `step --task MANUAL-1 --report <seq>` | 0 | PASS, `manual.seq-instr` → `manual.rollback-demo` |
| 7 | `step --task MANUAL-6 --report <rollback>` | 0 | ROLLBACK, `manual.rollback-demo` → `manual.seq-instr` |
| 8 | `step --task MANUAL-7 --report <delegate>` | 0 | DELEGATE, `manual.delegate-demo` |
| 9 | `step --task MANUAL-5 --report <done>` | 0 | PASS, `manual.done` |
| 10 | `--json step --task MANUAL-5` | 0 | `phase: manual.done`, `status: done`, без `prompt` |
| 11 | `--json history --task MANUAL-6` | 0 | 5 записей, только по `MANUAL-6` |

## Исправленные замечания

1. **SOFT_FAIL возвращает exit code 1** → теперь `PASS` и `SOFT_FAIL` возвращают `0`, только `HARD_FAIL`/`BLOCKED`/`ROLLBACK` — `1`.
2. **JSON-mode при завершённой задаче возвращает большой prompt** → для `status=done` возвращается компактный контракт: `phase`, `status`, `instructions`, без `prompt`.
3. **History `--task` возвращал записи всех задач** → теперь сначала резолвится `task_id`, потом фильтруется по `task_id` и `task_key`.
4. **Флаги `is_delegated`, `is_blocker`, `is_critic` не сохранялись** → добавлены колонки в `phases`, поля в domain `Phase`, маппинг в `_row_to_phase`, `schema.py` и seed-загрузку.

## Результаты автотестов

```bash
DATABASE_URL='' python -m pytest tests/test_cli_manual_workflow.py tests/test_cli_core.py tests/test_wizard_unit.py tests/test_wizard_coverage.py tests/test_phase_fsm.py tests/test_wizard_core_gaps.py tests/test_wizard_fk_types.py -q --tb=short
```
