# URL-state разделов редактора фазы

**Статус:** реализовано и проверено, ожидает review.

## Проблема

Outline редактора `/phase/{id}` записывает hash выбранного раздела через
`replaceState`. Из-за этого переходы между основным блоком, инструкциями,
проверками и подтверждениями не создают шаги браузерной истории, а Back/Forward
не восстанавливают выбранный раздел.

## Решение

1. Пользовательский переход по outline или mobile select записывать через
   `pushState`.
2. Initial deep link с hash канонизировать без нового шага через `replaceState`.
3. На `popstate` восстанавливать scroll position, active link и mobile select
   без изменения URL и API-запросов.
4. Не создавать дубликат истории при повторном выборе текущего раздела.

## Проверка

- template contract tests для push/replace/none и `popstate`;
- focused и полный pytest, PostgreSQL integration, coverage, ruff, mypy;
- production Compose candidate и `/health`;
- live Chromium: overview -> instructions -> checks -> Back -> Back -> Forward,
  reload deep link, desktop/mobile, отсутствие API writes/runtime errors/overflow;
- browser screenshot после восстановления раздела.

Фактический результат:

- focused UI contracts: 2 passed;
- полный pytest: 1492 passed, 38 deselected;
- PostgreSQL 16 integration: 38 passed;
- coverage: 94.26% при пороге 94%;
- ruff: all checks passed;
- mypy: no issues in 81 source files;
- production Compose candidate: healthy, `/health` подтвердил database/schema `ok`;
- live Chromium desktop/mobile: Back/Forward и reload deep link работают,
  API writes, runtime errors и horizontal overflow отсутствуют;
- mobile screenshot проверен на viewport 375 x 812.

## Вне объёма

- изменение CRUD редактора фазы;
- изменение структуры и визуального дизайна разделов;
- merge или deploy без отдельной команды.
