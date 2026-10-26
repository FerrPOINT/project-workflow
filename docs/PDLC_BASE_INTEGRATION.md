# PDLC и интеграция с Base

## Текущий source-кандидат UI

Точный UI SHA: `675565b5923455c771c22589979a23520cc5d041` ([pin](../.base-ui-revision)).
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
