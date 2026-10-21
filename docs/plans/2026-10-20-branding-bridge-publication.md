# Публикация адаптера опубликованного брендинга

Восстановить bounded same-origin JSON bridge из незалитой реализации, отдельно
от конфликтующего старого React UI. Сохранить текущие SSO/UoW middleware,
namespace и SSR оболочку. Маршрут /api/platform/branding читает только заданный
оператором public источник; browser credentials не отправляются upstream.
Проверить 200/304/404, ETag, timeout, redirects, disabled и лимит 64 KiB;
не обслуживать upstream HTML/JavaScript с origin Workflow.
Renderer/SSR exporter и переход потребителя на новый UI pin — отдельный этап.
Runtime, migrations и состояние БД не устанавливаются.

Результат: 21 целевой тест, 100% строк нового модуля, repository Ruff, Mypy
(139 source files), 13 documentation tests и проверки закреплённого SDK прошли.
Полный native gate не квалифицирован: timeout SQLite commit; повтор одинакового
префикса коллекции прошёл и на baseline, и на кандидате (113 passed, 1 skipped).
Linux/PostgreSQL/full-project coverage остаются отдельным gate перед merge.
