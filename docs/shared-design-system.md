# Подключение общей дизайн-системы

Продукт использует @pdlc/ui 0.3 и опубликованный документ Admin. Общие controls,
цвета, шрифты, плотность, скругления и popup принадлежат Base; запросы,
права, данные и callbacks сохраняются здесь. UI/SDK/skills pins независимы.

Канонический контракт: services-base/docs/platform/DESIGN_SYSTEM.md.
Компоненты искать через pdlc-ui search → show → example. Не создавайте
копии примитивов, собственный Toaster и глобальные определения Base tokens.
Существующие source-компоненты и preview получают общий UI; исторические
прототипы не являются установленным приложением. Установка выполняется отдельно.

PLATFORM_BRANDING_URL — явный public browser endpoint опубликованного branding.
Пустое значение сохраняет defaults. CSS/JS/fonts в templates/base экспортируются
штатным export-ssr.mjs; не редактируйте подготовленные файлы вручную.

Выбор иконки профессии — Base select_control + choice-runtime. Workflow передаёт
каталог SVG и renderOption; собственных popup, Escape и возврата focus нет.
Программная смена value завершается refreshChoice без input/change и записи.

Источник UI 0.3.0: `579749e19e9088be200c62e5563a3cb2db4d8c9f` в `.base-ui-revision`.
SDK и skills pins независимы; установка этим source-кандидатом не выполняется.
