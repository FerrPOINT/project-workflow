# Планы развития — архив

Все дорожные карты до 2026-06-21 устарели: проект перешёл на PostgreSQL +
SQLAlchemy 2, legacy `WorkflowDB`/`db/base.py` и SQLite runtime removed.

Файлы перемещены сюда для истории. Актуальное состояние — в
`docs/plans/current-state.md` и `README.md`.

| Файл | Дата | Тема | Статус |
|---|---|---|---|
| `2026-06-06-smart-agent-chatgpt-subscription-plan.md` | 2026-06-06 | подписка ChatGPT | отменён |
| `2026-06-13-workflow-refactor.md` | 2026-06-13 | рефакторинг workflow | выполнен частично, затем пересмотрен |
| `2026-06-21-detailed-roadmap.md` | 2026-06-21 | Postgres + Docker | устарел: Docker не используется, SQLite убран |
| `2026-06-21-improvements-roadmap.md` | 2026-06-21 | улучшения | устарел |
| `2026-06-21-refactor-roadmap.md` | 2026-06-21 | рефакторинг | устарел |

Последнее крупное обновление: 2026-06-26 — полный цикл чистки legacy,
detete API для задач, broad except → конкретные исключения, UI polish,
структурное логирование, актуализация README/AGENTS.
