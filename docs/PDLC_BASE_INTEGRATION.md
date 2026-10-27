# PDLC и интеграция с Base

## Текущий source-кандидат UI

Точный UI SHA: `cf88f7094044a403e6bb7105cfa88b12c4208c96` ([pin](../.base-ui-revision)).
Компоненты и reference берутся из этой версии Base; открытый справочник другой
версии не подтверждает доступность контракта в продукте. SDK/skills pins
независимы. Это исходники собственного checkout; установка и authenticated
приёмка runtime этим значением не подтверждаются. Датированные разделы ниже
описывают прежние квалификации и не заменяют проверку итогового кандидата.

Ключи задач используют resource_list_title/description technical/tone. Общая choice label и mobile header geometry принадлежат Base; backing control, данные профессий, маршруты и события сохраняются Workflow.

## Исходный baseline до объединения UI

До объединения `.base-ui-revision` был `4856b4ffc40bc1b47066e5e8410ba4a7217b2201` ([pin](../.base-ui-revision)).
Он обновлён основной веткой для совместимого чтения текущих прав; не описывает
незавершённые общие компоненты этой задачи. SDK и skills pins независимы.

Объединённый UI pin выставляется после регенерации Base. Сохранены общий брендинг,
типографика и SSR exporter из основной ветки; добавлены исходный срок доступа,
отзыв приватного DOM, остановка autosave и BFCache. SDK и skills pins независимы.
Это source-кандидат; установка и live-приёмка ещё не выполнены.

Рабочая копия общего UI расширяет SSR button нативной ссылкой и использует
section_header/text_link/state в Workflow. Её SSR assets получены штатным
экспортом из task-owned Base worktree, fingerprints проверены. Это ещё не
поставка из указанного выше SHA: после сведения свежих main/master нужен итоговый
Base commit, точный UI pin и повторная квалификация совпадающих inputs. SDK и
skills pins не меняются. Несовпадение source-кандидата с baseline не считать
merge-ready или установкой.

Датированные разделы ниже описывают историю квалификаций. Текущий pin сам по себе не подтверждает установку или authenticated-приёмку.

Канонические определения находятся у Base: [TERMS](https://github.com/FerrPOINT/services-base/blob/02e1ebbd3d2fcbf1c5e0f55a39d3cf554b085217/docs/platform/TERMS.md),
[ADR 0005](https://github.com/FerrPOINT/services-base/blob/02e1ebbd3d2fcbf1c5e0f55a39d3cf554b085217/docs/adr/0005-pdlc-base-sdlc-terminology.md),
[BRANDING](https://github.com/FerrPOINT/services-base/blob/02e1ebbd3d2fcbf1c5e0f55a39d3cf554b085217/docs/BRANDING.md). Документы продукта ссылаются на эти определения.

## Ответственность продукта

Продукт владеет: определения процессов, профессии и фазы. Запросы, DTO, маршруты, права и предметные правила
остаются здесь. Общие компоненты и механизмы получают данные и callbacks.
SDLC API/scopes/roles/workflow IDs сохраняются как предметные контракты.

## Воспроизводимые зависимости

Dependency-free Python namespace contract экспортируется из Base по новому независимому `.base-revision`; CI проверяет generated-файл. Это не установка HTTP SDK и не изменение skills/catalog pin.

SSR export принадлежит `base-modules/ui/ssr`; продукт хранит штатно экспортированные templates/base и fingerprint. React-примеры справочника не являются SSR macros. `.base-ui-revision` и SDK pin проверяются независимо.

UI SHA хранится в `.base-ui-revision`; SSR tooling и Docker используют
`services-base/base-modules/ui`. React-потребители обновляют также package/lockfiles. Приложения `components-dictionary`
и `base-platform` расположены отдельно и не входят в UI-пакет продукта.
Визуальный каталог запускается только при необходимости проверки примера.

## Переходные контракты

Общий SDK распознаёт оба PAT-префикса и явно доверенную пару JWT audiences.
Проверки issuer, подписи, срока действия и предметных прав сохраняются.
Канонические общеплатформенные env-переменные используют `PDLC_*`; временные
`SDLC_*` aliases не должны конфликтовать. Собственные env-префиксы продукта
сохраняются. Значения credentials не выводятся при диагностике конфликта.

SSO readers поддерживают прежние транзакции. Новые writers включаются
отдельной установкой после принимающих сторон. Опубликованный пользовательский
branding сохраняет приоритет над default PDLC. Исторические ADR, evidence,
миграции и идентификаторы данных не переписываются ради имени платформы.

Локальные source-тесты, hosted CI, установка и authenticated browser-приёмка
фиксируются отдельно. Этот source-комплект не меняет установленный runtime,
credentials или группы `pdlc1`, `pdlc2`, `pdlc3`, `pdlc-common`.

## Локальные доказательства

PostgreSQL integration: 77 тестов прошли на собственном disposable PostgreSQL.
Полный unit/coverage-прогон дал 2542 успешных теста; 16 failures исправлены
в mocks общего SSR global и явном UTF-8 для Node subprocess. Повтор затронутых
модулей и соседних сценариев: 28 passed; итоговый appended coverage 94.17%.
Ruff и mypy (127 файлов) прошли; документационный gate — 13 тестов.
SSR fingerprint и generated Python contract проверены штатными exporters Base.

IAB использовал собственную SQLite smoke-базу с синтетическими данными, без
центральной сессии и внешнего LLM. При ширине 375 проверены dashboard, drawer,
Back/Forward, reload и phase deep link. Неподтверждённый ввод вызывает общий
диалог Base; отмена сохраняет введённое значение, уход после очистки работает.
Это отдельная локальная UI-проверка, не evidence установленного SSO/runtime.

![Dashboard на мобильной ширине](assets/pdlc-namespace-20261015/workflow-dashboard-375.jpg)

![Общий диалог защиты правок](assets/pdlc-namespace-20261015/workflow-dirty-guard-375.jpg)

## Source-структура Base

Python SDK расположен в `services-base/base-modules/python/cli-core`; UI и SSR
exporter — в `services-base/base-modules/ui`. Библиотека, Auth, оператор, host и
справочник имеют отдельные границы по
[ADR 0006](https://github.com/FerrPOINT/services-base/blob/a4dea438ec99103ca83b51540d11de548b1ee82d/docs/adr/0006-base-repository-layout.md).
Имена imports, credentials и wire-контракты сохраняются; UI/SDK/skills pins
остаются независимыми. SSR assets получаются штатным exporter и проверяются
по fingerprints. Общие CSS/mechanisms не редактируются в продуктовой копии.
Установка и authenticated межпродуктовая приёмка выполняются отдельно.

## UI-кандидат 2026-10-18

SSR/UI pin: `6f1c797a0b11380f7e36db5ced0360f25a0265a5`.
SDK и skills pins независимы. Обновлены канонические SSR CSS и fingerprint штатным exporter Base: поля формы
получают собственный border-box и не зависят от reset продукта.
Защита черновика и namespace-состояние сохраняют продуктового владельца.
Source-проверки не означают установки в PDLC2.

## Общий каркас Base, source 2026-10-18

UI pin обновлён на `4b80fbfbfae48d95219011a4612dd9427a1a4b92`; SSR CSS и fingerprint
получены штатным exporter Base и проверены на совпадение. Изменение не затрагивает
Workflow state, запросы, Python/SDK/skills pins или installed runtime. React
AppShell не переносится в SSR: здесь сохраняются канонические macros/JS/CSS Base.

## Справочник и общий каркас: 2026-10-18

UI pin `1eb905ffe1d7d983af9464c98e67ee90ead20e18` обновляет подготовленный справочник, проверяемые API-примеры и инструменты проверки Base. Общий CSS ограничивает ширину ProjectPicker и переносит длинные идентификаторы ResourceList; логика React, HTTP API, SDK и skills не меняются. SSR CSS и fingerprint получены штатным exporter. CLI работает offline: `pdlc-ui check` в начале задачи или после смены pin → `search "задача"` → `show ExportName` → один `example`. Полный fingerprint не вычисляется на каждом поиске.

Карточки и демонстрации поддерживаются [приложением Base](https://github.com/FerrPOINT/services-base/tree/main/components-dictionary). Общие каркас, навигация, темы и мобильное меню принадлежат Base; запросы, DTO, права и предметные состояния остаются у продукта. Приёмка source-кандидата не означает установку или production-приёмку.

Workflow остаётся SSR-потребителем. Экспорт и fingerprints канонических macros/JS/CSS проверяются штатным exporter; React AppShell в серверные шаблоны не переносится.

## Кандидат SDK жизненного цикла identity

`.base-revision` закрепляет `2bb386503eeb009e2238160e88970eae0fab2824`:
[протокол Base v1](https://github.com/FerrPOINT/services-base/blob/2bb386503eeb009e2238160e88970eae0fab2824/docs/contracts/IDENTITY_DELETION_V1.md).
Namespace exporter без дополнительных зависимостей, UI и skills pins остаются
независимыми. Workflow реализует строгие Python DTO и собственные durable guards
для ссылок на identity; [inventory и квалификация](plans/2026-10-22-identity-deletion-owner.md)
не означают merge, установку или сквозную приёмку Auth.

## Общие строки действий — 2026-10-26

UI producer: `c0d2245e40303efffc04c7d8c24eb3746afd1439`. В Base добавлен ActionGroup и SSR action_group;
PageHeader, SectionHeader, PageNavigation и ChatComposerActions используют общий
каркас. Данные, права, курсоры, submit/pending, неизвестный результат записи и
readback сохраняются у продукта. Для пояснений используется ResourceListDescription.
Внешние margin/width/grid placement и sticky-контейнер принадлежат экрану;
общие gap, разделитель и мобильная компоновка — Base. Нативные формы,
тип кнопок, hidden, IDs и callbacks сохраняются. SDK и skills pins не изменены.

Проверены шесть offline frozen installs, singleton React, CLI/reference,
frontend types, guards и штатный SSR fingerprint. Изменённые React-сценарии
имеют scoped regression checks; общий UI проверен в IAB на трёх темах и
ширинах320/375/1920/2560. Это source adoption; установленный runtime, SSO
и продуктовые данные не изменялись. Полный release/hosted/runtime gate отдельно.

## Нативные подписи ресурсов — 2026-10-26

UI-кандидат `73665aa7bb64cbf16b1537f81c6e8f6129373738` расширяет SSR
resource_list_description необязательными tag=span/p/div, class_name, hidden
и caller. Старый span/id-контракт сохраняется. Пять счётчиков/пояснений
используют общий macro; native IDs, hidden, условия и обработчики остаются
у Workflow. Общий CSS/macros/fingerprints получают штатным exporter;
ручная копия и продуктовые шрифты/цвета для этих подписей не нужны.
UI/SDK/skills pins независимы; source adoption не означает установку.

## Навигация режимов и контекст фаз — 2026-10-26

На действующем UI pin `c2ca61094a904706fceeda8eb8f3b3cfd2e7cdfc` Workflow
использует SSR action_group для формы и переключателей вида фаз,
section_navigation для реальных ссылок режимов и Notice separated для
пояснения барьера параллельной группы. Native anchors сохраняют href,
data-mode-id/testid и aria-current; это переходы страниц, а не Tabs.
IDs, права, scope, submit/cancel/delete, phase jump и весь extra_script
не меняются. Данные графа, сортировка и резерв места под меню остаются
предметной композицией Workflow. Отдельного динамического renderer пояснения
нет: setPhaseView переключает оформление существующей разметки.

Пройдены 114 distinct scoped cases: новые контракты/шаблон, режимы и sidebar,
а также выбранные workflows/phases routes. Два устаревших shell-assertions
воспроизведены на исходном шаблоне и исправлены под действующий контракт Base.
Ruff и штатный SSR fingerprint прошли. Изменения только в шаблоне и тестах;
UI-пакет, SDK/skills pins и artifacts других приложений не пересобирались.

[Компонентная проверка IAB](assets/screens/shared-context-20261026/README.md)
покрывает native iframe ширины 320/375/1920/2560 и три темы. Проверены
клавиатурный Select режима, route parameters, RadioGroup и focus phase jump.
Это точные SSR-фрагменты с синтетическими данными; установленное приложение,
авторизация, запись и реальный browser zoom 200% этим не проверены.

Следующий scoped проход перевёл panel-actions профессии на тот же action_group,
две доступные подписи номера фазы — на base-visually-hidden, а строки dashboard
используют общий цвет/hover ResourceListRow без продуктовой копии. Owner IDs,
права, тексты, href и scripts сохранены. Пройдены 40 шаблонных и 81 выбранный
route case, Ruff; с предыдущим набором эти числа не суммируются. В IAB отдельно
проверены 12 сочетаний темы/ширины, размеры скрытой подписи, доступное имя,
общие действия и клавиатурный focus ссылки. Полный backend/runtime gate этим
не заменяется; UI/SDK/skills pins и подготовленные SSR assets не менялись.

## Вертикальные группы действий — 2026-10-26

Принят UI producer `7294a7974a898f182c22034b511c6b4b15205cef`; SDK/skills pins сохранены.
Совместимый `ActionGroup orientation="vertical"` и SSR `action_group`
описаны в [контракте Base](https://github.com/FerrPOINT/services-base/blob/7294a7974a898f182c22034b511c6b4b15205cef/docs/plans/action-orientation-20261026.md).
Проверены архив UI, offline frozen install шести React-потребителей,
singleton React, CLI/reference, шесть frontend types и SSR fingerprint.
Forge дополнительно прошёл19 адресных тестов и lint двух изменённых модулей;
остальные backend/application builds не выполнялись.

IAB проверяет source-компонент Forge с синтетическими callbacks:24 сочетания
темы, ширины и направления; это не приёмка установленного приложения.
Данные, права, pending и подтверждения остаются у продукта; сетка корзины
Tracker связана с её данными и не получает общий breakpoint из Base.
Публикация, полный интеграционный gate и установка учитываются отдельно.

## Подготовленный HTML и клавиатура — 2026-10-27

Принят совместимый UI producer `a95d9fe7b31cca23e1f6432bae43246120859efb`; SDK/skills pins сохранены.
Общий Prose keyboardScroll документирован в [Base](https://github.com/FerrPOINT/services-base/blob/a95d9fe7b31cca23e1f6432bae43246120859efb/docs/platform/DESIGN_SYSTEM.md).
Штатный SSR export и fingerprint актуальны; нового клиентского HTML
преобразования в SSR macro нет.
Backend build, hosted CI, общий интеграционный gate и установка здесь
не выполнялись; source adoption не меняет установленный runtime.

## Динамические знаки и метки профессий — 2026-10-27

Статические и динамические знаки используют один `namespace_mark` — продуктовую
композицию SVG-словаря с `icon_mark` Base. Header choice и палитра клонируют
малый знак; карточки — обычный. Счётчик карточки клонирует результат `badge`.
Геометрия, ARIA и оформление общего примитива больше не повторяются в JS;
namespace IDs, SVG paths, имена, значения цвета и pluralize остаются у Workflow.

В палитре убраны локальные 20 px и окрашивание самого SVG: общий IconMark
тонирует подложку и сохраняет читаемый foreground темы даже для белого цвета.
Название остаётся доступным, экземпляры знаков и шаблоны не меняют друг друга.
Продуктовые handlers, URLs, выбор workflow и операции сохранены вне renderer
границ; проекция всех десяти rendered script blocks это проверяет.

Пройдены четыре DOM-теста с фрагментами из настоящих Jinja/Base macros,
59 namespace-route tests, шесть role-view tests и scoped Ruff.
Codex IAB проверяет 36 иконок, light/dark/gray × 320/375/1920/2560,
End/Escape, focus, перенос длинного имени, одинаковые названия с разными ID,
один синтетический callback и отсутствие видимых native select/overflow.
[Снимки и область проверки](assets/screens/template-marks-20261027/README.md).

UI pin не менялся; штатный SSR fingerprint совпадает, прежний архив Base
переиспользован. Install, compile, reference generation и app/backend builds
не повторялись. Это source-компоненты и синтетические callbacks без API/Auth;
не установленное приложение и не приёмка серверных операций.

## Общая подпись навигации — 2026-10-27

Принят совместимый UI 0.3.4, producer `efa4babe176b42530a3e17fc25f10e8678f82d33`.
Новый SidebarItemLabel доступен через публичный API; локальная композиция
данного продукта не требовала замены подписи. Сохранены прежние контракты.
Проверены настоящий архив, offline CLI и frozen adoption: шесть React consumers
с одним React, седьмой SSR consumer — через штатный export/check. SDK/skills
pins неизменны; это source-кандидат, без установки и hosted CI.

## Нативные атрибуты SSR Button — 2026-10-27

Текущий UI 0.3.5: `8bdd8ecd54eb6a6f553bfbadcfaf07c99f4a801d`. Сохраняются React API и независимые SDK/skills pins.
27 кнопок четырёх шаблонов используют Base button с caller/attributes.
Сохранены owner handlers/data/IDs, native submit и ARIA; из JS не создаётся
новый dispatcher. Динамическая параллельная метка клонирует Base badge template.
Пройдены 216 DOM-проекций, 81 scoped tests и 37 subtests; JS вне клонирования
badge совпадает полностью. UI contract gate и Ruff пройдены.
Архив UI и offline frozen adoption проверены; общий интеграционный gate,
hosted CI, публикация и установка здесь не выполнялись.

## Нативные поля, карточки и меню SSR — 2026-10-27

Принят UI 0.3.6, producer `623deb7da5813fa9d1185ded7688c35bb15cd43e`. Девять
полей, четыре menu actions и десять Card-композиций используют общие macros;
начальный namespace template также используется динамическим renderer. Две
динамические параллельные группы клонируют Base Card; типы, IDs, данные,
события, очередь сохранения и native FormData остаются Workflow. Settings
сохраняет CLI-каталог, copy actions и область доступности без локального Card.

Пройдены 82 scoped tests и 37 subtests, 22 полных DOM/FormData/JS-проекции
пяти шаблонов и восемь role/group сценариев настоящих dynamic renderers.
Заменённый тест проверяет неизменность целого Card template вместо удалённого
отдельного mark template. Проверки новых raw primitive copies обязательны.

Отдельная source-only IAB fixture проверяет macros/renderer/runtime в трёх темах
и четырёх ширинах: размеры 40/44 px, autosize/reset, native события, FormData,
mouse/Enter, Escape/focus. У двух console MutationObserver сообщений нет
источника; они сохранены как неатрибутированные, не объявлены исправленными.

Настоящий UI-архив, offline CLI, frozen adoption и SSR fingerprints проверены.
React/JS/CSS/types и зависимости совпадают с 0.3.5, без повторной сборки этих
артефактов. SDK/skills pins не менялись. Полный интеграционный gate, hosted CI,
установка и приёмка приложения остаются отдельными этапами.

## SSR выбор и составные части — 2026-10-27

Принят UI 0.3.8, producer `cf88f7094044a403e6bb7105cfa88b12c4208c96`.
Семь raw select заменены select_control; четыре Label, два CardTitle,
ResourceList/Row, Timeline/Item/Content, mode navigation и Prose создаёт Base.
Это 25 исходных мест; их данные, options/selected, scope и callbacks сохранены.

29 полных DOM/value/FormData-проекций и product scripts совпадают вне явно
обновлённого канонического Base choice-runtime. Пройдены 102 scoped tests и
37 subtests на финальном экспорте. В IAB найден и исправлен общий native reset:
reset восстанавливал backing value, но trigger обновлялся раньше default action.
Общий runtime теперь ждёт следующий task и проверяет cancellation/destroy.
До/после, отмена и cleanup имеют отдельные регрессионные доказательства.

IAB source fragments: 12 theme/width modes, клавиатура/mouse, одна пара
input/change, callback, refresh/reset и destroy/reinit без дублей.
Это не runtime-приёмка продукта. Одно MutationObserver console сообщение
без URL сохранено как неатрибутированное. Страничный error handler пуст.

Архив, frozen offline adoption семи consumers, SSR fingerprints и CLI
проверены. React/CSS/types не менялись; изменён standalone SSR JS runtime,
проверены checked JS, declarations, lint, 3 reset/native-composition cases
и 7 runtime cases. SDK/skills pins сохранены. Hosted CI, полный gate,
push/PR/merge и установка остаются отдельными действиями.

## Рабочая область Base — 2026-10-27

Текущий UI 0.3.9, producer `bab93d2683367117784c2f01fcbed7f80fd3ef15`.
Workbench и семь частей добавляют общий каркас рабочей области внутри PageFrame:
высота по настоящим gutter, внутренний scroll, адаптивные Aside/AsideAction и
mobileFlow для длинной формы. SSR-аналога этого React-контракта нет.
Настоящий архив из 882 файлов сверён с установленным UI; offline frozen install,
singleton React и CLI check пройдены. SDK/skills pins сохранены. Это source
adoption; приложение, backend и Storybook не пересобирались, runtime не менялся.

Штатный SSR export обновлён и --check прошёл. Изменение общего CSS добавляет
React Workbench; Workflow не получает фиктивных контейнеров или React-зависимости.
Прежние предметные шаблоны и HTTP/SSO обработчики не менялись.

## SSR-ресурсы общего UI 0.3.10 — 2026-10-27

UI producer `94f2ccd9e6f09eba9fbf67f4582a9fa7a91c44b9` закреплён независимо от SDK/skills.
Штатный export и fingerprint --check прошли; новые content_section/data_bar
получены вместе с общим CSS. Это не перенос предметных workflow, namespace,
HTTP/SSO handlers или финансовой логики в Base. React-зависимости не добавлены.
Source adoption не означает сборку backend, установку или приёмку runtime.

## Общие метки и inline-код UI 0.3.11 — 2026-10-27

Точный UI producer `755c9f9a27ba81ddd841b43c511bb372a3c93e40` принят отдельно от SDK/skills.
Штатный SSR export и --check пройдены. Получены inline_code и совместимый highlighted у resource_list_row, старый позиционный attributes сохранён. Предметные шаблоны, namespace и handlers не менялись; React-зависимости не добавлены.

Настоящий архив UI содержит 900 файлов; все production bytes сверены с
producer и шестью установленными frontend-пакетами. Offline frozen refresh,
React singleton и CLI check пройдены; runtime и зависимости backend не менялись.

IAB evidence относится к пяти изолированным композициям из настоящих owner/Base
исходников: 60 сочетаний темы/ширины, 18 branding-пресетов, три статуса Wiki,
readonly click и Enter/Space. Это не приёмка всех экранов, Auth или API продукта.
Полный интеграционный gate остаётся отдельной открытой стадией.

## Разделители редактора инструкций — 2026-10-27

Строки инструкций и панель добавления используют существующий content_section
из принятого UI 0.3.11. Native div, data-instruction-id/data-step-num, поля,
подписи и обработчики сохранены. Предметные grid/порядок/namespace остаются у
Workflow; script страницы совпадает байт в байт с исходным. Нового UI pin нет.

54 scoped tests и 37 subtests, Ruff, contract guard и полное сравнение owner
content DOM проходят. IAB: 12 сочетаний темы/ширины и девять density-сочетаний;
block inset следует общему token 4/8/12 px, кнопки и однострочные поля сохраняют
минимум 44 px на мобильном. Проверка относится к статической source-композиции:
product handlers отключены CSP, реальный API/Auth не запускался.
Один unattributed MutationObserver warning сохранён отдельно; при нуле script
элементов в композиции его источник не назначен продукту. Console clean не заявлен.

## Разделители компактного timeline — 2026-10-27

Три локальных правила border заменены существующим content_section: верх списка,
конец обычного блока и разделение фаз параллельной группы. Выбор вида остаётся
у Workflow: setPhaseView обновляет data-dividers, сохраняя тот же DOM. Порог
первого SSR-вида, phase-view-mode, URL, права, формы и callbacks не менялись.
Общий UI 0.3.11 остаётся на прежнем pin; нового компонента или runtime нет.

Отдельно исправлено прежнее перекрытие пояснения параллельной группы кнопкой
добавления: действие после группы имеет собственный промежуток, обычные строки
сохраняют своё размещение. Это предметная компоновка Workflow вокруг Button Base.
Исходное пересечение подтверждено на 04681082, исправление — отдельным geometry
сравнением и соседними обычными строками.

76 scoped tests и 37 subtests, Ruff и UI guard проходят. Двенадцать rendered
сценариев сохраняют полный native DOM после узкой проекции оформления; кроме
четырёх строк выбора стороны разделителя owner script совпадает байт в байт.
48 native-DOM transitions сохраняют узлы, focus, FormData и URL. Их входы
сверены с финальным CSS-кандидатом; свежие Python/IAB checks записаны отдельно.

IAB: финальные 48 сочетаний двух ролей/видов, трёх тем и четырёх ширин; нет
overflow и пересечений с действиями. Проверены меню, Space, focus и reload,
штатный SSR choice-runtime, снимки 375/1920/2560. Неполный первый QA-показ
с native fallback отклонён; второй сохранил найденное пересечение; принят
только третий финальный source-run. Unattributed MutationObserver warning
сохранён отдельно, clean console не заявлен. Application/API/Auth/runtime
и hosted CI этим доказательством не подменяются.

## Общая render-граница UI 0.3.12 — 2026-10-27

Точный UI producer `20633a6489dfd33e7afa782e0a06c23faea26b7a` принят отдельно от SDK/skills.
React-граница не переносится в SSR. Изменён точный UI pin; штатный export/check подтверждает прежние SSR assets. Шаблоны, scripts и API Workflow не менялись.

Настоящий UI-архив: 904 файла, offline CLI/reference и production bytes
проверены вне workspace без Storybook. Шесть frontend-пакетов сверены с архивом;
cached offline frozen refresh, React singleton и CLI check прошли.
Общий механизм и ограничения: Base docs/platform/DESIGN_SYSTEM.md,
раздел «Граница render-ошибки React». Данные, fallback, отчёт и reset identity
принадлежат владельцу. HTTP/async/event/SSR ошибки обслуживаются отдельно.

IAB evidence относится к фактическим Base/CatalogProviders source-композициям:
12 сценариев ввода/сбоя/reset и 12 длинных fallback в трёх темах и четырёх
ширинах; сохранены preview ready/error и черновик. Это не приёмка установленного
продукта или Auth/API. Интеграционный gate, hosted CI и публикация остаются
отдельными стадиями. Runtime не менялся.

## Общая responsive-подписка UI 0.3.13 — 2026-10-27

Точный UI producer `83c961379b25379e8c83ebc207eec60cfb4ebbef` принят независимо от SDK/skills.
React hook не подменяет SSR. Изменён точный UI pin; штатные SSR export/check сохранили прежние bytes. Существующий SSR drawer adapter Base остаётся владельцем своего browser behavior.

Новый hook доступен через `@pdlc/ui/lib`; query задаёт владелец. Необязательный
callback выполняется до React layout update только на browser event, сохраняя
перенос focus из исчезающего control. Mount/query changes не запускают действие.
SSR/отсутствующий matchMedia дают false. Контракт, cleanup и standalone example
доступны через `pdlc-ui show useMediaQuery` и `pdlc-ui example useMediaQuery`.

Архив 907 файлов, offline CLI, шесть frozen refresh, React singleton и сравнение
установленных production bytes прошли. Lockfiles после подготовки не менялись;
backend, SDK/skills pins и установленный runtime не изменялись.
IAB source proof: 27 Tracker viewport transitions, 30 shell/drawer checks и
12 recovery cases в трёх темах. Ширина менялась без reload; ввод, focus и journal
сохранены. Это source-композиции, не приёмка полного authenticated приложения.
Прежний IAB attachment gap закрыт новым успешным run; ошибки сохранены в истории.
Полный интеграционный gate, Rust transport vectors, hosted CI и публикация отдельно.

## Общая геометрия истории UI 0.3.14 — 2026-10-27

UI producer `f3b99e3ce15a4a447d58790f118c6be70e931a18` принят независимо от SDK/skills.
Архив содержит 910 файлов; offline CLI, шесть frozen refresh и production bytes
проверены. В Workflow штатный SSR export остался byte-identical. Это обновление
source-поставки; установленный runtime не менялся.

React-only hook не подключается к SSR. API, запросы, frontend assets и поведение
Workflow не менялись; UI pin фиксирует согласованный producer, штатные SSR
fingerprints остаются прежними. React-механизмы не копируются в SSR-адаптеры.

Base qualification: 17 hook tests, 69 primitive checks и 37 search assertions.
IAB Base/Forge source-compositions: 24 theme/width cases плюс три intent/error
cases; это не полная authenticated-приёмка продуктов. Полный интеграционный gate,
Rust search transport, hosted CI и публикация остаются отдельными стадиями.
