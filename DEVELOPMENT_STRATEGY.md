# Стратегия разработки и тестирования WARTZ Workflow

> **Версия:** 2.0  
> **Дата:** 2026-06-03  
> **Основной урок:** Использовать проверенные инструменты вместо самодельных решений. Не изобретать велосипед.

---

## 1. Архитектура: выбор инструментов

### ❌ Что НЕ работало
| Проблема | Последствие |
|----------|-------------|
| Кастомный Jinja-like рендерер в `ui.py` | Не поддерживал вложенные циклы, сломался на `{% if %}`, ограниченная отладка |
| Inline CSS + HTML в Python-строках | ~20KB мусора в одном файле, нет подсветки синтаксиса, ад редактирования |
| Кастомный YAML-парсинг фаз | Неочевидные баги с типами данных |

### ✅ Что работает
| Инструмент | Зачем |
|------------|-------|
| **Jinja2** (стандартный) | Шаблоны в отдельных файлах, полная мощь синтаксиса, наследование `base.html`, кэширование |
| **FastAPI + `Jinja2Templates`** | Чистый API, type hints, авто-документация, правильная интеграция с Jinja2 |
| **SQLite** | Единый источник истины для UI, атомарные операции, не требует отдельного сервера |
| **CSS переменные + media queries** | Тёмная тема, адаптивность без отдельного "mobile скилла" |
| **Playwright** | Скриншоты для визуальной регрессии, тестирование responsive design |

**Правило:** Перед написанием кастомного решения — проверить, есть ли готовый инструмент в экосистеме Python/JS.

---

## 2. Фронтенд: шаблонизация

### Структура шаблонов
```
templates/v2/
├── base.html          # layout: sidebar, header, toast, CSS переменные
├── dashboard.html     # extends base.html
├── phases.html        # extends base.html
├── phase_detail.html  # extends base.html
├── tasks.html         # extends base.html
└── ...
```

### Принципы
1. **Предвычислять в Python**, не в шаблоне. Сложная логика (`group_count_suffix`, `is_blocker`) вычисляется в `ui.py`, в шаблоне только `{{ value }}`.
2. **Минимум условий в шаблонах**. `{% if %}` внутри `{% for %}` — запах. Вынести в Python.
3. **CSS в `base.html`**, не inline. Мобильная адаптивность через `@media(max-width:768px)`.
4. **Блок `extra_style`** для страничных стилей, не глобальных.

---

## 3. Бэкенд: FastAPI паттерны

### TemplateResponse — правильный синтаксис
```python
# ❌ Неправильно — старый формат Starlette
return templates.TemplateResponse(
    "tasks.html",
    {"request": request, "page": "tasks", "tasks": tasks},
)

# ✅ Правильно — FastAPI 0.100+
return templates.TemplateResponse(
    request=request, name="tasks.html", context={
        "request": request, "page": "tasks", "tasks": tasks,
    }
)
```
**Нарушение** приводит к: `TypeError: unhashable type: 'dict'`

### Жизненный цикл сервера
- **Jinja2 кэширует шаблоны** в память. После изменения `.html` требуется рестарт uvicorn.
- **SQLite соединение** инициализируется один раз при первом `_get_db()`.

---

## 4. Тестирование

### Пирамида тестов
```
    /\
   /  \  E2E (Playwright) — скриншоты ключевых страниц
  /----\  ~5%
 /      \
/--------\  Интеграционные (pytest + TestClient) — маршруты, API, DB
|        |  ~25%
|--------|
|        |
|________|  Unit (pytest) — schema, config, utils
            ~70%
```

### Что тестируем
| Уровень | Примеры |
|---------|---------|
| **Unit** | `test_phases.py` — порядок фаз, `get_next_phase`, парсинг YAML |
| **Integration** | `test_ui.py` — `GET /`, `GET /phases`, `GET /phase/{id}`, API JSON |
| **Visual** | `test_screenshots.py` — скриншоты dashboard, kanban, detail, mobile |

### Тесты UI: адаптивность
- Проверять HTML на наличие CSS-классов (не на точный текст).
- При смене дизайна обновлять assert'ы:
  ```python
  # Было
  assert 'class="phase-row"' in response.text
  # Стало (Kanban)
  assert 'class="kanban-card"' in response.text
  ```

---

## 5. Мобильная разработка

### Подход
Не нужен отдельный "mobile скилл". Достаточно CSS:

```css
/* Desktop */
.kanban { grid-template-columns: repeat(6, 1fr); }

/* Tablet */
@media(max-width:1200px) { .kanban { grid-template-columns: repeat(3, 1fr); } }

/* Mobile */
@media(max-width:768px) {
  .sidebar { transform: translateX(-100%); }  /* скрыть */
  .burger { display: flex; }                  /* показать ☰ */
  .kanban { grid-template-columns: 1fr; }      /* вертикально */
  .task-table { display: none; }              /* скрыть таблицу */
  .task-cards { display: flex; }              /* показать карточки */
}
```

### Тестирование mobile
```python
# Playwright: viewport iPhone 14
page = await browser.new_page(viewport={'width': 390, 'height': 844})
await page.goto(url)
await page.screenshot(path='mobile.png')
```

---

## 6. Работа с данными

### Единый источник истины
| Источник | Данные |
|----------|--------|
| `phases.yaml` | Источник фаз (импортируется в SQLite при первом запуске) |
| `SQLite` | Рабочая копия для UI (чтение + редактирование) |
| `state/*.json` | Прогресс задач (read-only для UI) |

### CRUD через БД
```python
# Получить фазы
phases = wdb.get_phases()

# Обновить инструкцию
wdb.update_instruction(inst_id, {"description": "Новый текст"})

# Удалить check
wdb.delete_check(check_id)
```

---

## 7. Паттерны, которые экономят время

### Предвычисление метаданных
```python
# Вместо сложной логики в шаблоне
def _group_phases(phases):
    groups = {k: [] for k in PHASE_GROUP_NAMES}
    for p in phases:
        group = PHASE_TO_GROUP.get(p["id"], "setup")
        insts = wdb.get_phase_instructions(p["id"])
        p["instruction_count"] = len(insts)
        groups[group].append(p)
    return groups
```

### Flatten структур
```python
# Вместо nested dict для шаблона
phase["delegate_agent"] = p.delegate.agent if p.delegate else None
phase["delegate_timeout"] = p.delegate.timeout_min if p.delegate else None
```

---

## 8. Чеклист перед коммитом

- [ ] `pytest tests/ -q` — все тесты проходят
- [ ] Скриншоты desktop + mobile сделаны и проверены визуально
- [ ] Бейджи БЛОКЕР/АГЕНТ не появились случайно
- [ ] Номера фаз — человеческие (№1–№30)
- [ ] Нет горизонтального скролла на mobile
- [ ] Burger-меню работает на mobile
- [ ] API endpoints отвечают 200

---

## 9. Антипаттерны (чего избегать)

1. **Самодельный рендерер** — всегда использовать Jinja2/Django Templates
2. **Inline HTML в Python** — всегда выносить в `.html`
3. **Сложная логика в шаблонах** — предвычислять в Python
4. **Отдельный mobile UI** — делать адаптив через CSS
5. **JSON вместо SQLite для state** — SQLite для атомарных операций
6. **Прямые API вызовы из UI** — UI state-driven, агент дергает CLI
