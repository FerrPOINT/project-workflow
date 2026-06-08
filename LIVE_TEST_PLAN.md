# Live Test Plan — WARTZ Workflow CLI / WizardEngine

## Цель
Проверить внутреннего агента (WizardEngine) через реальные CLI-вызовы на живой БД. Убедиться, что все 5 вердиктов, переходы, rollback, delegate, блокеры работают через `wartz-workflow step`.

## Предусловия

```bash
# 1. БД инициализирована
python -c "from wartz_workflow.db import WorkflowDB; w=WorkflowDB(); w.init()"

# 2. Smoke workflow загружен
python -c "from wartz_workflow.schema import ensure_phase_catalog; from wartz_workflow.db import WorkflowDB; ensure_phase_catalog(WorkflowDB())"

# 3. CLI доступен
which wartz-workflow || pip install -e .
```

## Сценарии тестирования

### 🔹 1. Happy Path — полный проход 6 фаз

**Инструкции** (что делать):
1. Создать задачу `SMOKE-103`.
2. Выполнить 6 шагов `wartz-workflow step --task SMOKE-103 --report "..."`.
3. Каждый отчёт должен содержать keywords из checks/instructions/evidence текущей фазы.
4. Проверить `history` — все записи должны иметь `verdict: pass`.
5. Проверить статус задачи в БД — `done`.

**Скиллы** (какие навыки нужны исполнителю):
- CLI execution (`wartz-workflow step`)
- Keyword matching (понимать, что wizard ищет keywords в отчёте)
- DB inspection (`sqlite3 workflow.db`)

**Проверки** (граничные условия):
- Нельзя пропускать фазы.
- Нельзя подать пустой `--report`.
- Последняя фаза `smoke.done` должна вернуть `next_phase: null`.

**Доказательства** (что фиксируем):
- JSON-вывод каждого `step --report`.
- `wartz-workflow history --task SMOKE-103 --n 10`.
- `SELECT status FROM tasks WHERE task_key = 'SMOKE-103';`.

### 🔹 2. Verdict: PARTIAL — неполный отчёт

**Инструкции**:
1. На фазе `smoke.intake` подать отчёт без обязательных keywords (например, без "requirements").
2. Ожидать `verdict: PARTIAL`.
3. Убедиться, что `current_phase` осталась той же.
4. Подать полный отчёт → PASS → переход к следующей фазе.

**Скиллы**:
- Намеренное создание неполного отчёта для проверки edge case.
- Чтение JSON-ответа CLI.

**Проверки**:
- `current_phase` не изменилась при PARTIAL.
- `status` остался `active` (не `blocked`).
- В `missing` перечислены конкретные пропущенные items.

**Доказательства**:
- JSON с `verdict: PARTIAL`.
- `SELECT current_phase FROM tasks WHERE task_key = 'SMOKE-103';` до и после.

### 🔹 3. Verdict: BLOCKED — blocker без rollback target

**Инструкции**:
1. На фазе `smoke.plan` подать отчёт: "blocked by missing requirements, cannot proceed".
2. Убедиться, что фаза `smoke.plan` не имеет `rollback_target`.
3. Ожидать `verdict: BLOCKED`.
4. Проверить, что задача перешла в статус `blocked`.

**Скиллы**:
- DB query: `SELECT rollback_target FROM phases WHERE code = 'smoke.plan';`.
- Формирование отчёта с explicit blocker.

**Проверки**:
- Если `rollback_target IS NULL`, то вердикт = BLOCKED (не ROLLBACK).
- `status` задачи = `blocked`.
- `current_phase` остаётся прежней.

**Доказательства**:
- JSON с `verdict: BLOCKED`.
- `SELECT status, current_phase FROM tasks WHERE task_key = 'SMOKE-104';`
- Запись в `supervisor_runs` с `verdict: blocked`.

### 🔹 4. Verdict: ROLLBACK — откат на предыдущую фазу

**Инструкции**:
1. Найти фазу с `rollback_target` (например, `smoke.review` → `smoke.plan`).
2. Дойти до неё через все предыдущие фазы.
3. Подать отчёт: "Tests failed, must rollback to plan phase".
4. Ожидать `verdict: ROLLBACK` и `rollback_target: smoke.plan`.
5. Убедиться, что `current_phase` = `smoke.plan`.

**Скиллы**:
- Workflow navigation (понимать rollback_target в schema).
- Создание негативного отчёта с rollback intent.

**Проверки**:
- Фаза имеет `rollback_target`.
- `rollback_phase_id` в `supervisor_runs` заполнен.
- `task_history` содержит запись `status: rollback`.

**Доказательства**:
- JSON с `verdict: ROLLBACK` и `rollback_target`.
- `SELECT current_phase FROM tasks WHERE task_key = 'SMOKE-105';` = `smoke.plan`.
- `wartz-workflow history --task SMOKE-105`.

### 🔹 5. Verdict: DELEGATE — делегирование

**Инструкции**:
1. Найти/создать фазу с `is_delegated = true` и assigned agent.
2. Подать отчёт: "delegate this to ops agent".
3. Ожидать `verdict: DELEGATE`.

**Скиллы**:
- Delegate signal generation.
- Проверка `is_delegated` в БД.

**Проверки**:
- `is_delegated = true` обязательно (иначе вердикт будет PARTIAL).
- Статус задачи остаётся `active`.

**Доказательства**:
- JSON с `verdict: DELEGATE`.
- DB: `SELECT is_delegated FROM phases WHERE code = '...';`

### 🔹 6. False Positive Guard — "rollback" в тексте не должен давать ROLLBACK

**Инструкции**:
1. На фазе `smoke.review` (rollback_target есть, но отчёт корректный).
2. Подать отчёт: "Rollback path reviewed, no issues found".
3. Ожидать `verdict: PASS` (не ROLLBACK!).

**Скиллы**:
- Понимание логики: `rollback` в тексте + `rollback_target` → ROLLBACK, но только если есть issues/blockers.

**Проверки**:
- Отчёт содержит слово "rollback".
- Нет blockers.
- Нет missing items.
- Вердикт = PASS.

**Доказательства**:
- JSON с `verdict: PASS`.
- Сравнение с предыдущим regression (было ROLLBACK до фикса).

### 🔹 7. Cache Coherence — PromptCache

**Инструкции**:
1. Создать задачу.
2. Вызвать `get_phase_prompt()` — cold.
3. Вызвать `get_phase_prompt()` — cached.
4. Выполнить `evaluate()` → transition.
5. Проверить, что snapshot в `supervisor_runs` — fresh (use_cache=False).

**Скиллы**:
- Performance measurement.
- DB inspection.

**Проверки**:
- Cache hit: <0.1ms.
- Cache miss after transition: rebuild.
- `context_snapshot` в DB содержит актуальный `current_phase`.

**Доказательства**:
- Benchmark timings.
- JSON `context_snapshot` из `supervisor_runs`.

### 🔹 8. Command Guard — только 2 команды

**Инструкции**:
1. Выполнить: `wartz-workflow --help`.
2. Убедиться, что доступны только `step` и `history`.
3. Попробовать: `wartz-workflow step --task TEST --skip` → FAIL.
4. Попробовать: `wartz-workflow step --task TEST --repo /tmp` → FAIL.

**Скиллы**:
- CLI option testing.
- Negative test design.

**Проверки**:
- `exit_code != 0` для rejected options.
- `--version` = 1.0.0.

**Доказательства**:
- `stderr` с `No such option`.
- `--help` output listing.

## Формат отчёта по выполнении

После каждого сценария фиксируем:

| Поле | Значение |
|------|----------|
| Task key | SMOKE-XXX |
| Сценарий | Happy Path / Partial / Blocked / Rollback / Delegate / False Positive |
| Команды | `wartz-workflow step --task KEY --report "..."` |
| Verdict | PASS / PARTIAL / BLOCKED / ROLLBACK / DELEGATE |
| DB state (до) | `current_phase`, `status` |
| DB state (после) | `current_phase`, `status`, `next_phase` |
| История | `wartz-workflow history --task KEY` |
| Скриншот | Если UI-часть задействована |

## Автоматизация

Скрипт live-тестирования:
```bash
bash scripts/test_cli_live.sh
```

Скрипт выполняет сценарии 1, 2, 3, 4 автоматически и сверяет JSON-ответы.
