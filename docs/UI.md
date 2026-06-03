# UI — инструкция по использованию

> Web UI для wartz-workflow: визуализация фаз, настройки, граф выполнения.

---

## Запуск

```bash
hrflow ui --port 8811
# или
python -m wartz_workflow.ui --port 8811 --host 0.0.0.0
```

Open http://localhost:8811

---

## Страницы

### `/` — Dashboard

- Текущие задачи
- Быстрые ссылки на фазы

### `/phases` — Kanban

- Фазы в 3 колонках: Не начато / В работе / Выполнено
- Drag-and-drop между колонками
- Клик → детальная карточка

### `/phase/{id}` — Детальная карточка фазы

**Редактируемые поля:**
- name, description, skills, delegate_agent, delegate_timeout
- execution_mode (sync/parallel toggle)
- rollback_target, next_recommendation

**Секции:**
- **Инструкции** — sync (зелёные) + parallel (оранжевые) группы. Drag-and-drop reorder.
- **Чеки** — checklist с чекбоксами
- **Evidence** — обязательные артефакты
- **Скилы** — список + добавление/удаление inline

**Автосохранение:** onblur через 400ms debounce.

### `/execution` — Граф выполнения

- Вертикальный список фаз
- **SYNC** — одиночные узлы
- **PARALLEL** — группы из нескольких фаз с JOIN-узлом
- **Drag-and-drop:**
  - Перетащить между элементами → reorder (синяя полоска индикатора)
  - Наложить на другой узел → merge в parallel group (оранжевая подсветка, 200ms delay)
- **Кнопки:** Сохранить layout, Сбросить
- **Сохранение:** `PUT /api/phases/order` + `PUT /api/phases/parallel`

### `/settings` — Настройки

- **API Integration:** Jira URL, GitLab URL, GitLab Project ID
- **UI Server:** Port, Host
- **Группы фаз:** tag chips для категорий
- **Key patterns:** regex для валидации task keys
- Кнопки: Сохранить, Сбросить к defaults

### `/wizard` — Wizard

- Список всех фаз
- Клик → форма с вопросами + чеклист + evidence
- Submit → PASS/FAIL

---

## API Endpoints

| Endpoint | Method | Описание |
|----------|--------|----------|
| `/api/phases` | GET | Все фазы |
| `/api/phases/{id}` | GET | Детали фазы |
| `/api/phases/{id}` | PUT | Сохранить фазу + инструкции + чеки + evidence |
| `/api/phases/order` | PUT | Batch update phase_order (DND) |
| `/api/phases/parallel` | PUT | Batch update parallel groups |
| `/api/settings` | GET/PUT/DELETE | Настройки |
| `/api/wizard/{key}/context` | GET | Полный контекст для агента |

---

## Архитектура UI

```
HTTP Request
    ↓
FastAPI Router (ui.py)
    ↓
Controller (route handler)
    ↓
PhaseService (service.py)
    ↓
DB Access (db.py)
    ↓
SQLite
```

**Важно:** никаких `application/`, `domain/`, `infrastructure/` директорий — предыдущая попытка сломала импорты. Только flat modules.

---

## Шаблоны

```
templates/v2/
├── base.html          # layout, sidebar, CSS variables, toast
├── dashboard.html
├── phases.html        # Kanban board
├── phase_detail.html  # editable phase card + flow-run instructions
├── execution.html     # DND graph + Mermaid fallback
├── settings.html      # config form
├── wizard.html        # phase questionnaire
└── wizard_list.html   # phase list for wizard
```

---

## CSS Variables (тёмная тема)

```css
:root {
  --bg: #0B0F1A;
  --surface: #111827;
  --panel: #1E293B;
  --border: #374151;
  --text: #F1F5F9;
  --text-muted: #94A3B8;
  --accent: #3B82F6;
  --green: #10B981;
  --orange: #F59E0B;
  --red: #EF4444;
}
```

---

## Тесты UI

```bash
pytest tests/test_ui.py tests/test_graph.py -v
```

Покрытие:
- Все endpoints возвращают 200
- HTML содержит ожидаемые элементы
- API возвращает корректный JSON
