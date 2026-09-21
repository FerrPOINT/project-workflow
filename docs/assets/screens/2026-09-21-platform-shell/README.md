# Platform shell browser QA

Дата проверки: 2026-09-21.

## Матрица

- Маршруты: dashboard, workflows, phases, tasks, task detail и CLI settings.
- Viewport: 375x812, 768x900, 1440x900 и 2560x1200.
- Темы: dark, gray и light.
- Всего: 72 page states и 3 keyboard-сценария mobile drawer.

## Результат

- Header: до 61 px на mobile и 60 px на tablet/desktop.
- Навигация: drawer 320 px, tablet rail 72 px, desktop sidebar 264 px.
- Main offset: 0 / 72 / 264 px по breakpoint-контракту.
- Horizontal overflow, console/page/HTTP errors: 0.
- Мелкие или безымянные shell controls: 0.
- Active state корректен на всех маршрутах, включая task detail и CLI settings.
- Drawer удерживает фокус, закрывается по Escape и возвращает фокус trigger во
  всех трёх темах.

`qa-results.json` содержит машинные метрики для всех состояний. PNG рядом
сняты со штатной нейтральной smoke-fixture; drawer-файлы ограничены viewport,
чтобы fixed-слой не искажался full-page capture.
