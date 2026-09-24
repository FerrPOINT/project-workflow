# Контраст verdict на detail задачи

**Статус:** реализовано и проверено, ожидает review.

## Проблема

На `/task/{task_key}` verdict `blocked` в тёмной теме использовал красный текст
`#ef4444` на мягком красном фоне `#2c181c`. Axe измерил контраст `4.44:1` при
минимуме `4.5:1`; дефект воспроизводился на всех проверенных ширинах от 375 до
2560 px.

## Решение

1. Использовать основной читаемый цвет текста для blocked verdict, как в
   каталоге задач.
2. Сохранить семантический красный цвет в фоне и рамке badge.
3. Не менять status chip задачи и остальные verdict-типы без подтверждённого
   дефекта.

## Проверка

- template contract на читаемый текст и семантическую рамку;
- focused и полный pytest, PostgreSQL integration, coverage, ruff, mypy;
- production Compose candidate и `/health`;
- live Chromium для phase/task detail: 30 theme/viewport состояний, Axe,
  overflow, runtime/network, read-only requests и task anchor history;
- визуальная проверка mobile screenshot 375 x 812.

Фактический результат:

- focused UI contracts: 2 passed;
- полный pytest: 1492 passed, 38 deselected;
- PostgreSQL 16 integration: 38 passed;
- coverage: 94.26% при пороге 94%;
- ruff: all checks passed;
- mypy: no issues in 81 source files;
- production Compose candidate: healthy, `/health` подтвердил database/schema `ok`;
- live Chromium: 30/30 phase/task detail состояний в трёх темах и пяти
  viewport, serious/critical Axe, overflow, runtime/network и API writes — 0;
- task anchor Back и mobile screenshot 375 x 812 проверены.

## Вне объёма

- изменение данных или структуры task detail;
- редизайн всех status/verdict цветов;
- merge или deploy без отдельной команды.
