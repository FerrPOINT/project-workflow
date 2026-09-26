# URL-state выбора неймспейса

**Статус:** реализовано и проверено локально 24.09.2026.

## Проблема

Редактор `/namespaces` меняет `namespace_id` через `replaceState`. Из-за этого
выбор другой записи не создаёт шаг браузерной истории, а Back/Forward не
восстанавливают выбранный неймспейс и заполненную форму. Возврат из
`/namespaces/new` также должен сохранять режим создания и контекст для отмены.

## Решение

1. Пользовательский выбор неймспейса записывать через `pushState`.
2. Начальную канонизацию URL и refresh каталога выполнять через `replaceState`.
3. На `popstate` восстанавливать edit/create mode, форму, active state, тему и
   глобальный селектор без API-записей.
4. Проверять ID из URL по текущему каталогу до изменения UI.
5. Сохранить текущий неймспейс в query-параметре страницы создания, чтобы
   Cancel возвращал пользователя в ожидаемый контекст.

## Проверка

- template contract tests для push/replace state и `popstate`;
- focused и полный pytest, coverage, ruff, mypy;
- PostgreSQL integration suite;
- production Compose candidate и `/health`;
- live Chromium: direct URL, reload, A -> B -> Back -> Forward,
  create -> selection -> Back, отсутствие неожиданных API writes;
- мобильный screenshot и проверка runtime/overflow.

Фактический результат:

- focused UI suite: `201 passed`;
- полный non-integration suite: `1491 passed, 38 deselected`;
- PostgreSQL integration: `38 passed` на изолированном PostgreSQL 16;
- coverage: `94.26%` при обязательном пороге `94%`;
- `ruff` и `mypy`: без ошибок;
- production Compose candidate: контейнер healthy, `/health` вернул HTTP 200
  с исправной БД и схемой;
- live Chromium acceptance: direct URL, reload, A -> B -> Back -> Forward,
  create -> selection -> Back -> Cancel, неожиданных API writes нет;
- мобильный viewport 375 x 812: runtime-ошибок и горизонтального overflow нет,
  визуальный screenshot проверен.

## Вне объёма

- изменение CRUD API;
- визуальный redesign редактора;
- merge или deploy без отдельной команды.
