# Wizard — инструкция для агента

> Как агент проходит фазы workflow через wizard gate.

---

## Принцип

Wizard — это **gate evaluator**. Агент выполняет фазу, шлёт отчёт, wizard проверяет покрытие по чеклисту. Только PASS → переход к следующей фазе.

---

## CLI-команды

### 1. Получить инструкции текущей фазы

```bash
hrflow wizard TASKNEIROKLYUCH-456
```

**Вывод:**
```
🎯 Фаза 3 — Task Docs Setup
📋 Создать task-описание в info/, настроить шаблоны

❗ Обязательно выполнить:
   1. Создать info/TASKNEIROKLYUCH-456_task.md
   2. Заполнить секции: Цель, Критерии, Этапы
   3. Прикрепить скриншот дашборда

🔄 Повторяющиеся задания (каждый ход):
   1. Залогировать работу по фазе в файл info/
   2. Обновить progress.json текущей фазой
   3. Добавить запись в changelog.md

Когда выполнишь — пришли отчёт:
   hrflow wizard TASKNEIROKLYUCH-456 --report "описание что сделал"
```

### 2. Отправить отчёт и получить verdict

```bash
hrflow wizard TASKNEIROKLYUCH-456 --report "Создал info/TASKNEIROKLYUCH-456_task.md, заполнил все секции, прикрепил скриншот. Лог записан в info/phase_3_log.md. progress.json обновлён."
```

**Exit код:**
- `0` — PASS, переход к следующей фазе
- `1` — FAIL, нужно доработать

**Вывод при PASS:**
```json
{
  "verdict": "PASS",
  "phase": "3",
  "phase_name": "Task Docs Setup",
  "covered": [
    "Создать info/TASKNEIROKLYUCH-456_task.md",
    "Заполнить секции: Цель, Критерии, Этапы",
    "Прикрепить скриншот дашборда"
  ],
  "missing": [],
  "repeatable": [
    "залогировать фазу",
    "обновить progress",
    "добавить в changelog"
  ],
  "next_phase": "4",
  "next_phase_name": "Git Identity Check",
  "message": "✅ Фаза 3 пройдена. Переходим к фазе 4 — Git Identity Check"
}
```

**Вывод при FAIL:**
```json
{
  "verdict": "FAIL",
  "phase": "3",
  "covered": [
    "Создать info/TASKNEIROKLYUCH-456_task.md"
  ],
  "missing": [
    "Заполнить секции: Цель, Критерии, Этапы",
    "Прикрепить скриншот дашборда"
  ],
  "repeatable": ["добавить в changelog"],
  "message": "❌ Фаза 3 — требуются доработки..."
}
```

### 3. Полный контекст (для LLM-агента)

```bash
hrflow wizard-context TASKNEIROKLYUCH-456
# или --json для машинного вывода
```

**Возвращает:**
- `current_phase` — текущая фаза
- `completed_phases` — пройденные фазы
- `all_phases` — все 30 фаз с инструкциями, чеками, evidence
- `repeatable_checks` — статус повторяющихся заданий
- `phase_history` — история переходов

---

## Как это работает внутри

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

## API (для внешних интеграций)

```bash
# Оценить отчёт
POST /api/wizard/{jira_key}/evaluate
Body: {"report": "..."}
Response: {"verdict": "PASS|FAIL", ...}

# Полный контекст
GET /api/wizard/{jira_key}/context
Response: {"jira_key": "...", "current_phase": "...", "all_phases": [...]}
```

---

## Что проверяет wizard

| Проверка | Как | Пример |
|----------|-----|--------|
| **Чеклист фазы** | Keyword matching | "создал task-файл" → находит "Создать info/...task.md" |
| **Repeatable** | Гибкое matching | "лог", "progress", "changelog" в отчёте |
| **Повторяющиеся** | Всегда 3 пункта | залогировать, обновить, добавить |

**Важно:** wizard НЕ делает Jira transition. Это отдельный шаг агента через `wartz-jira`.

---

## Примеры отчётов

### Хороший отчёт (PASS)
```
Создал info/TASKNEIROKLYUCH-456_task.md с описанием задачи.
Заполнил все секции: Цель, Критерии, Этапы.
Прикрепил скриншот дашборда.
Залогировал работу в info/phase_3_log.md.
Обновил progress.json текущей фазой.
Добавил запись в changelog.md.
```

### Плохой отчёт (FAIL)
```
Сделал task-файл. Всё готово.
```
Проблема: нет конкретики, нет proof-of-work, нет repeatable checks.

---

## Ограничения текущей реализации

1. **Keyword matching** — ищет слова >3 букв. Не понимает синонимы.
2. **Нет сохранения verdict в DB** — результат возвращается, но не пишется в таблицу.
3. **Repeatable checks захардкожены** — 3 строки в коде, не настраиваются.
4. **Linear flow** — не учитывает parallel/branches/rollback в state machine.
