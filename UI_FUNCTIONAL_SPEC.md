# WARTZ Workflow UI — Полный аудит функционала

**Дата:** 2026-06-03  
**Версия:** 1.4.0  
**Статус:** Аудит завершён, требуется реализация

---

## 1. ЧТО УЖЕ РАБОТАЕТ (READY)

| # | Функция | Маршрут | Реализация | Примечание |
|---|---------|---------|------------|------------|
| 1 | Landing page | `GET /` | `index.html` | Описание + 2 команды CLI |
| 2 | Список фаз | `GET /phases` | `phases.html` + `_render_phases_list()` | 30 фаз, №1–№30, кликабельные |
| 3 | Деталь фазы | `GET /phase/{id}` | `phase_detail.html` + `_render_phase_detail_content()` | Инструкции, Checks, Evidence |
| 4 | JSON API фаз | `GET /api/phases` | `api_phases()` | Список фаз в JSON |
| 5 | Автоимпорт YAML → SQLite | `_yaml_to_sqlite()` | При первом запуске | 30 фаз, 83 инструкции, 36 checks |
| 6 | Тёмная тема | `PAGE_STYLE` | CSS-переменные | Inter + JetBrains Mono |
| 7 | SQLite-хранилище | `WorkflowDB` | 5 таблиц | phases, instructions, checks, evidence, checkups |

---

## 2. ЧАСТИЧНО РАБОТАЕТ / ТРЕБУЕТ ДОРАБОТКИ (PARTIAL)

| # | Функция | Проблема | Чего не хватает |
|---|---------|----------|-----------------|
| 1 | **Главная страница** | Только landing, не dashboard | KPI-карточки, задачи в работе, прогресс-бар |
| 2 | **Навигация** | Только «Фазы» | Нет «Задачи», «Jobs», «Настройки», «Wizard» |
| 3 | **Evidence** | Отображается, но данные пустые | В БД только `description`, нет `item`/`validator` из YAML |
| 4 | **Checkups** | Загружаются из БД, не отображаются | Нет секции на детальной странице |
| 5 | **Meta-информация фазы** | Не все поля из YAML | Нет `delegate_agent`, `timeout`, `next_recommendation`, `rollback_target` |
| 6 | **Группировка фаз** | Фазы в плоском списке | Нет групп по категориям (Setup, Research, Dev, QA, Closure) |
| 7 | **Тип выполнения инструкций** | Показывается `sync`/`parallel` | Захардкожено через `p.is_delegated` (скоро deprecated) |

---

## 3. ПОЛНОСТЬЮ ОТСУТСТВУЕТ (MISSING)

### 3.1 CRUD операции (редактирование фаз)

| # | Операция | Метод | URL | Приоритет |
|---|----------|-------|-----|-----------|
| 1 | Добавить инструкцию | `POST` | `/api/phases/{id}/instructions` | 🔴 Высокий |
| 2 | Редактировать инструкцию | `PUT` | `/api/instructions/{id}` | 🔴 Высокий |
| 3 | Удалить инструкцию | `DELETE` | `/api/instructions/{id}` | 🔴 Высокий |
| 4 | Reorder инструкций | `POST` | `/api/phases/{id}/instructions/reorder` | 🟡 Средний |
| 5 | Добавить check | `POST` | `/api/phases/{id}/checks` | 🔴 Высокий |
| 6 | Редактировать check | `PUT` | `/api/checks/{id}` | 🔴 Высокий |
| 7 | Добавить evidence | `POST` | `/api/phases/{id}/evidence` | 🟡 Средний |
| 8 | Редактировать evidence | `PUT` | `/api/evidence/{id}` | 🟡 Средний |

**Бэкенд:** `db.py` уже содержит CRUD-методы (созданы в прошлой сессии), но они не подключены к API.

### 3.2 Страницы и навигация

| # | Страница | URL | Статус | Что должно быть |
|---|----------|-----|--------|-----------------|
| 1 | **Dashboard** | `/` | ❌ Landing | 4 KPI-карточки, прогресс-бар, активные задачи |
| 2 | **Задачи** | `/tasks` | ❌ Нет | Список задач с Jira-ключом, текущей фазой, % выполнения |
| 3 | **Деталь задачи** | `/task/{jira_key}` | ❌ Нет | История фаз, timeline, отчёты агента |
| 4 | **Jobs** | `/jobs` | ❌ Нет | Фоновые задачи (`delegate_task`), статус, логи |
| 5 | **Wizard UI** | `/wizard/{jira_key}` | ❌ Только CLI | Пошаговый ассистент с вопросами фазы |
| 6 | **Answers** | `/answers/{jira_key}` | ❌ Нет | История ответов агента по фазам |
| 7 | **Config** | `/config` | ❌ Нет | Редактирование `phases.yaml`, настройки workflow |
| 8 | **Настройки** | `/settings` | ❌ Нет | Порт, токены, пути к репозиториям |

### 3.3 Взаимодействие и UX

| # | Функция | Статус | Описание |
|---|---------|--------|----------|
| 1 | **Поиск фаз** | ❌ | Фильтрация по названию/описанию/skills |
| 2 | **Drag-and-drop** | ❌ | Reorder инструкций/checks мышью |
| 3 | **Inline-редактирование** | ❌ | Клик по тексту → input, Enter → сохранить |
| 4 | **Toast-уведомления** | ❌ | «Сохранено», «Ошибка», «Запущено» |
| 5 | **Статус фазы** | ❌ | Готово / Активно / Ожидает (цветная точка) |
| 6 | **Прогресс задачи** | ❌ | N из 30 фаз выполнено, прогресс-бар |
| 7 | **Кнопка «Запустить агента»** | ❌ | Для delegated-фаз — `delegate_task` через API |
| 8 | **Автосохранение** | ❌ | Debounced POST при изменении полей |

---

## 4. ТЕКУЩАЯ АРХИТЕКТУРА UI

```
┌─────────────────────────────────────┐
│  FastAPI (uvicorn)                  │
│  ├── GET /                          │
│  ├── GET /phases                    │
│  ├── GET /phase/{id}               │
│  ├── GET /api/phases                │
│  └── (остальное — 404)              │
├─────────────────────────────────────┤
│  _render_template()                 │
│  └── Простой replace {{ key }}      │
│  └── Нет условий, нет циклов        │
├─────────────────────────────────────┤
│  Templates/*.html (7 файлов)        │
│  └── Только index, phases,          │
│      phase_detail используются      │
├─────────────────────────────────────┤
│  SQLite (workflow.db)                │
│  └── 30 фаз, 83 инструкции,         │
│      36 checks, 0 evidence rows     │
│  └── CRUD-методы в db.py есть,      │
│      но не выставлены на API        │
└─────────────────────────────────────┘
```

---

## 5. ПЛАН РЕАЛИЗАЦИИ (приоритеты)

### Phase 1 — Навигация + Dashboard (Foundation)
- [ ] Расширить header: Дашборд, Фазы, Задачи, Jobs, Настройки
- [ ] Переделать `/` в Dashboard с KPI-карточками
- [ ] Добавить `/tasks` — список задач из `state/`
- [ ] Добавить `/jobs` — фоновые задачи

### Phase 2 — CRUD API (Backend)
- [ ] POST/PUT/DELETE `/api/instructions/*`
- [ ] POST/PUT/DELETE `/api/checks/*`
- [ ] POST/PUT/DELETE `/api/evidence/*`
- [ ] POST `/api/instructions/reorder`

### Phase 3 — Редактирование фаз (Frontend)
- [ ] Inline-редактирование инструкций (contenteditable + POST)
- [ ] Форма добавления новой инструкции
- [ ] Удаление строки (×)
- [ ] Dropdown типа проверки (git_branch, file_exists...)
- [ ] Toast «Сохранено»

### Phase 4 — Управление задачами
- [ ] Карточка задачи с текущей фазой
- [ ] Timeline пройденных фаз
- [ ] Прогресс-бар (N/30)
- [ ] Кнопка «Следующая фаза» → `workflow` CLI

### Phase 5 — Wizard + Answers
- [ ] `/wizard/{jira_key}` — пошаговый UI
- [ ] `/answers/{jira_key}` — история ответов
- [ ] Интеграция с `conversation.py`

---

## 6. БЫСТРЫЕ ПОБЕДЫ (Low-hanging fruit)

Можно сделать за 1–2 часа:

1. **Расширить навигацию** — добавить ссылки в `HEADER_HTML` (5 мин)
2. **Создать заглушки страниц** — `/tasks`, `/jobs`, `/settings` (15 мин)
3. **Подключить CRUD к API** — выставить методы `db.py` (30 мин)
4. **Добавить inline-редактирование** — contenteditable + fetch POST (1 час)
5. **Исправить Evidence** — добавить `validator`/`item` в импорт из YAML (15 мин)
6. **Добавить checkups на детальную страницу** — `_render_checkups()` (15 мин)

---

## 7. РЕАЛЬНЫЕ КОМАНДЫ CLI (vs. задокументированные)

**Реально существуют в коде:**
```
hrflow workflow TASK-KEY ["отчёт..."]   — отчёт по фазе / получить инструкции
hrflow done-list TASK-KEY               — список пройденных фаз
hrflow ui [--port] [--host] [--daemon]  — запустить Web UI
hrflow wizard TASK-KEY [--repo]         — интерактивный wizard
```

**НЕ существуют (фиктивные):**
```
init, phase, next, status, verify, list-phases, merge-check,
check-env, next-step, rollback, delegate, delegate-batch,
jobs, playbook, audit
```

---

## 8. ВЫВОД

**Текущий UI** — это **read-only viewer** фаз с базовой навигацией. Он позволяет:
- ✅ Просматривать 30 фаз workflow
- ✅ Видеть инструкции, checks, evidence
- ✅ Получать JSON через API

**Для полноценного workflow management нужно:**
- 🔴 CRUD редактирование фаз (Phase 2–3)
- 🔴 Страница задач с прогрессом (Phase 1, 4)
- 🟡 Wizard UI (Phase 5)
- 🟡 Dashboard с KPI (Phase 1)

**Бэкенд (SQLite + CRUD) готов на 70%. Фронтенд — на 20%.**
