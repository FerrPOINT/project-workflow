# План тестирования CLI — выполнен

## Окружение

```bash
export SMART_EVALUATE=false
export DATABASE_URL=''
export WORKFLOW_DIR=/tmp/pw_manual_cli
```

## Выполненные шаги

### 1. Исправить состав фаз в `seed.json`

**Цель:** параллельные группы должны быть симметричны.

| Группа | Было | Стало |
|---|---|---|
| `0.6` ↔ `1` | `0.6` parallel → `1`, `1` sync | оба `parallel`, взаимно |
| `1.5` ↔ `2` | `1.5` parallel → `2`, `2` sync | оба `parallel`, взаимно |
| `4.5` ↔ `5` | `4.5` parallel → `5`, `5` sync | оба `parallel`, взаимно |
| `7.5` ↔ `7.6` ↔ `7.6.R` | `7.5` sync → `7.6`, `7.6` parallel, `7.6.R` parallel | все `parallel` |

### 2. Проверить `smoke_seed.json`

- `smoke.parallel-a` ↔ `smoke.parallel-b` взаимно.
- Все инструкции в parallel-фазах имеют `execution_type=parallel`.

### 3. Исправить `DB_PATH`

- Добавлена функция `get_db_path()` в `project_workflow/infrastructure/db/__init__.py`.
- `SAUnitOfWork` теперь использует `get_db_path()` вместо кешированного `DB_PATH`.
- `WORKFLOW_DIR` из env теперь работает в одном процессе.

### 4. Создать автоматический e2e тест

- `tests/manual_workflow_seed.json` — кастомный workflow с параллельными/последовательными фазами и инструкциями.
- `tests/test_cli_manual_workflow.py` — 5 тестов на Click runner.

### 5. Ручное тестирование через CLI

| # | Команда | Ожидание | Факт |
|---|---|---|---|
| 1 | `step --task MANUAL-1` | показать текущую фазу | ✅ `Intake` |
| 2 | `step --task MANUAL-1 --report <intake>` | PASS → `Plan` | ✅ |
| 3 | `step --task MANUAL-1 --report <plan>` | PASS → `Parallel Phase A` | ✅ |
| 4 | `step --task MANUAL-1 --report <partial>` | SOFT_FAIL, остаться в группе | ✅ exit 1, missing frontend |
| 5 | `step --task MANUAL-1 --report <full>` | PASS → `Sequential Instructions` | ✅ |
| 6 | `step --task MANUAL-1 --report <seq>` | PASS → `Done` | ✅ |
| 7 | `step --task MANUAL-1 --report <done>` | PASS | ✅ |
| 8 | `--json step --task MANUAL-1` | `phase: manual.done` | ✅ |

## Найденные замечания

1. **SOFT_FAIL возвращает exit code 1.** Это может ломать скрипты, которые считают 1 ошибкой. Возможно, для SOFT_FAIL стоит возвращать 0, а для FAIL/BLOCK — 1.
2. **JSON-mode при завершённой задаче возвращает большой prompt.** Это технический деталь, а не report-вывод. Для `--json` стоит возвращать только контракт без prompt, когда задача завершена.
3. **Параллельные инструкции (`execution_type=parallel`) внутри sync-фазы** отображаются как пометка, но не меняют логику оценки. Все checks/evidence фазы всё равно требуются.

## Результаты автотестов

```bash
SMART_EVALUATE=false DATABASE_URL='' python -m pytest tests/test_cli_manual_workflow.py -v --tb=short
# 5 passed in 17.28s
```

## Следующие шаги (предлагаемые)

1. Прогнать существующие wizard/CLI тесты после изменения `seed.json`.
2. Решить, должен ли SOFT_FAIL возвращать exit code 0.
3. Очистить JSON-вывод для завершённых задач.
4. Закоммитить изменения.
