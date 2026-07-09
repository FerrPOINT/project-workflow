# Live Test Plan — project-workflow CLI / WizardEngine

## Цель
Проверить внутреннего агента (`WizardEngine`) через реальные CLI-вызовы на живой БД. Убедиться, что вердикты, переходы, rollback, delegate и блокеры работают через `project-workflow step`.

## Предусловия

```bash
# 1. БД инициализирована и smoke-данные загружены
python - <<'PY'
from project_workflow.application.state import _AppState
from project_workflow.infrastructure.db import schema

state = _AppState()
uow = state.get_uow()
schema.ensure_phase_catalog(uow)
uow._bootstrap_smoke_project_and_workflow()
PY

# 2. CLI доступен
which project-workflow || pip install -e ".[dev,ui]"
```

## Smoke workflow

Текущий smoke seed содержит **6 фаз**:

| Order | Code | Name | Execution type | Rollback target | Parallel with |
|---|---|---|---|---|---|
| 1 | `smoke.intake` | Document Intake | sync | — | — |
| 2 | `smoke.plan` | Schema & Architecture Plan | sync | — | — |
| 3 | `smoke.parallel-a` | Parser & Data Layer | parallel | — | `smoke.parallel-b` |
| 4 | `smoke.parallel-b` | Editor UI | parallel | — | `smoke.parallel-a` |
| 5 | `smoke.review` | Integration & Validation Gate | sync | `smoke.plan` | — |
| 6 | `smoke.done` | Release & Docs | sync | — | — |

## Сценарии тестирования

### 🔹 1. Happy Path — полный проход 6 фаз

**Инструкции**:
1. Сгенерировать уникальный ключ: `TASK_KEY="SMOKE-$(date +%s)"`.
2. Выполнить 6 шагов `project-workflow --json step --task "$TASK_KEY" --report "..."`.
3. Каждый отчёт должен содержать keywords из `checks`/`instructions`/`evidence` текущей фазы.
4. Проверить `history` — записи должны иметь `verdict: PASS`.
5. Проверить статус задачи в БД — `done`.

**Проверки**:
- Нельзя пропускать фазы.
- Нельзя подать пустой `--report`.
- Последняя фаза `smoke.done` должна вернуть `next_phase: null`.

**Доказательства**:
- JSON-вывод каждого `step --report`.
- `project-workflow history --task "$TASK_KEY" --json`.
- `SELECT status FROM tasks WHERE task_key = '<TASK_KEY>';`.

---

### 🔹 2. Verdict: PARTIAL — неполный отчёт

**Инструкции**:
1. Сгенерировать ключ: `TASK_PARTIAL="SMOKE-$(date +%s)-P"`.
2. На фазе `smoke.intake` подать отчёт без обязательных keywords (например, без "formats", "scope").
3. Ожидать `verdict: PARTIAL`.
4. Убедиться, что `current_phase` осталась той же.
5. Подать полный отчёт → `PASS` → переход к следующей фазе.

**Проверки**:
- `current_phase` не изменилась при `PARTIAL`.
- `status` остался `active` (не `blocked`).
- В `missing` перечислены конкретные пропущенные items.

**Доказательства**:
- JSON с `verdict: PARTIAL`.
- `SELECT current_phase FROM tasks WHERE task_key = '<TASK_PARTIAL>';` до и после.

---

### 🔹 3. Verdict: BLOCKED — blocker без rollback target

**Инструкции**:
1. Сгенерировать ключ: `TASK_BLOCKED="SMOKE-$(date +%s)-B"`.
2. Пройти `smoke.intake` полным отчётом.
3. На фазе `smoke.plan` подать отчёт: "blocked by missing requirements, cannot proceed".
4. Убедиться, что фаза `smoke.plan` не имеет `rollback_target`.
5. Ожидать `verdict: BLOCKED`.

**Проверки**:
- Если `rollback_target IS NULL`, то вердикт = `BLOCKED` (не `ROLLBACK`).
- `status` задачи = `blocked`.
- `current_phase` остаётся прежней.

**Доказательства**:
- JSON с `verdict: BLOCKED`.
- `SELECT status, current_phase FROM tasks WHERE task_key = '<TASK_BLOCKED>';`
- Запись в `supervisor_runs` с `verdict: blocked`.

---

### 🔹 4. Verdict: ROLLBACK — откат на предыдущую фазу

**Инструкции**:
1. Сгенерировать ключ: `TASK_ROLL="SMOKE-$(date +%s)-R"`.
2. Дойти до `smoke.review` через все предыдущие фазы.
3. Подать отчёт: "Tests failed, must rollback to plan phase".
4. Ожидать `verdict: ROLLBACK` и `rollback_target: smoke.plan`.
5. Убедиться, что `current_phase` = `smoke.plan`.

**Проверки**:
- Фаза имеет `rollback_target`.
- `rollback_phase_id` в `supervisor_runs` заполнен.
- `task_history` содержит запись `status: rollback`.

**Доказательства**:
- JSON с `verdict: ROLLBACK` и `rollback_target`.
- `SELECT current_phase FROM tasks WHERE task_key = '<TASK_ROLL>';` = `smoke.plan`.
- `project-workflow history --task <TASK_ROLL> --json`.

---

### 🔹 5. Verdict: DELEGATE — делегирование

**Инструкции**:
1. Сгенерировать ключ: `TASK_DEL="SMOKE-$(date +%s)-D"`.
2. Подать на `smoke.intake` отчёт с delegate-сигналом, например: "delegate this to ops agent".
3. Ожидать `verdict: DELEGATE` (только если фаза помечена как delegated и в отчёте есть delegate signal).

**Проверки**:
- `is_delegated = true` обязательно (иначе вердикт будет `PARTIAL`/`HARD_FAIL`).
- Статус задачи остаётся `active`.

**Доказательства**:
- JSON с `verdict: DELEGATE`.
- DB: `SELECT is_delegated FROM phases WHERE code = 'smoke.intake';`

---

### 🔹 6. False Positive Guard — "rollback" в тексте не должен давать ROLLBACK

**Инструкции**:
1. Сгенерировать ключ: `TASK_FP="SMOKE-$(date +%s)-FP"`.
2. Дойти до `smoke.review` (rollback target есть, но отчёт корректный).
3. Подать отчёт: "Rollback path reviewed, no issues found".
4. Ожидать `verdict: PASS` (не `ROLLBACK`).

**Проверки**:
- Отчёт содержит слово "rollback".
- Нет blockers / missing items.
- Вердикт = `PASS`.

**Доказательства**:
- JSON с `verdict: PASS`.
- Сравнение с предыдущим regression (было `ROLLBACK` до фикса).

---

### 🔹 7. Command Guard — только 2 команды

**Инструкции**:
1. Выполнить: `project-workflow --help`.
2. Убедиться, что доступны только `step` и `history`.
3. Попробовать: `project-workflow step --task TEST --skip` → FAIL.
4. Попробовать: `project-workflow step --task TEST --repo /tmp` → FAIL.

**Проверки**:
- `exit_code != 0` для rejected options.
- `--version` = `1.0.0`.

**Доказательства**:
- `stderr` с `No such option`.
- `--help` output listing.

## Формат отчёта по выполнении

После каждого сценария фиксируем:

| Поле | Значение |
|---|---|
| Task key | `SMOKE-<timestamp>[-SUFFIX]` |
| Сценарий | Happy Path / Partial / Blocked / Rollback / Delegate / False Positive / Command Guard |
| Команды | `project-workflow --json step --task KEY --report "..."` |
| Verdict | `PASS` / `PARTIAL` / `BLOCKED` / `ROLLBACK` / `DELEGATE` |
| DB state (до) | `current_phase`, `status` |
| DB state (после) | `current_phase`, `status`, `next_phase` |
| История | `project-workflow history --task KEY --json` |
| Скриншот | Если UI-часть задействована |

## Автоматизация

Скрипт live-тестирования:

```bash
bash scripts/test_cli_live.sh
```

Скрипт выполняет сценарии 1, 2, 3, 4, 5 автоматически и сверяет JSON-ответы.
