# URL-state выбора воркфлоу

**Статус:** реализовано и проверено локально 24.09.2026.

## Проблема

Страница `/workflows` всегда открывает первую запись. Активный namespace не
влияет на начальный выбор, а выбор другого воркфлоу хранится только в DOM и
теряется после reload. Back/Forward не восстанавливают просмотренную запись.

## Решение

1. Принять `workflow_id` на page route, валидировать его как положительный ID и
   показывать локализованные HTML 422/404 вместо тихого fallback.
2. Без явного `workflow_id` выбирать воркфлоу активного namespace, затем первый
   доступный как fallback.
3. При выборе записи сохранять `workflow_id` в URL через History API, не теряя
   `namespace_id` и другие query-параметры.
4. На `popstate` восстанавливать форму и active state без нового запроса.
5. После delete/reload каталога заменять устаревший ID в URL на фактический
   выбор либо удалять параметр для пустого каталога.

## Проверка

- route tests: explicit, namespace-derived, malformed и missing workflow;
- template contract: push/replace state и popstate;
- focused и полный pytest, coverage, ruff, mypy;
- production candidate browser QA: direct URL, reload, Back/Forward,
  namespace context, mobile/desktop, три темы, overflow/Axe/runtime checks.

Фактический результат:

- focused route suite: `14 passed`;
- полный non-integration suite: `1488 passed, 38 deselected`;
- PostgreSQL integration: `38 passed` на изолированном PostgreSQL 16;
- coverage: `94.25%` при обязательном пороге `94%`;
- `ruff` и `mypy`: без ошибок;
- production Compose candidate: `/health` вернул HTTP 200 с исправной БД и
  схемой;
- live Chromium acceptance: direct URL, reload, Back/Forward, mobile picker,
  HTML 422/404 и отсутствие неожиданных API writes;
- визуальная матрица: 9/9 состояний (`dark`, `gray`, `light` на ширинах 375,
  1280 и 1920 px) без serious/critical Axe violations, горизонтального
  overflow, runtime-ошибок и недостаточных мобильных touch targets;
- временные namespace/workflow после проверки удалены, контрольный остаток:
  `0 / 0`.

## Вне объёма

- изменение API CRUD;
- redesign редактора;
- merge или deploy без отдельной команды.
