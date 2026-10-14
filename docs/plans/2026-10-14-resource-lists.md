# Общие списки ресурсов Base

Утверждённый объём: одинаковые отступы, разделители, hover/focus обычных списков; продукт сохраняет данные, раскладку, маршруты и действия. Backend/skills pins не меняются.

## Контракт

Боковой отступ — 16 px. Normal: вертикальный 8 px, минимум 48 px; comfortable: 16 px, минимум 56 px. Высота не фиксируется. Семантика нативная; контейнер с несколькими действиями не становится кнопкой. CSS Base используется React и штатным SSR-экспортом.

## Покрытие

| Участок | Результат | Основание |
|---|---|---|
| `project_workflow/interfaces/ui/templates/dashboard.html` | migrated | Dashboard tasks and professions, shared SSR classes |

Сайдбары, document trees, маркированные пояснения/ошибки, формы, редакторы, таблицы и схемы исключены по назначению, а не по совпадению CSS-класса.

## Приёмка

Компонентные тесты и Chromium contract: семантика/действия, 16 px, grid, темы, длинный текст, 375/1281/1920 px, native disclosure. Затем продуктовые тесты, lint, typecheck/build, packed SDK и SSR drift. Установленная PDLC1 проверяется через IAB; происхождение images фиксируется отдельно от source/CI. Изменённые сервисы обновляются через private bundle с rollback images.
