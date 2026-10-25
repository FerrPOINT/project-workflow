# Общие композиции Workflow: иконки и SSR-брендинг

## Текущий кандидат: общий разделитель пагинации — 25 октября 2026

UI pin `7cef16712c453885952d16319439f0190f145747`, reference
`c6b48bda376ae0cc42303cf8d804036b6fd506dbfcff6eec51ab3f36bbb18a47`.

Обновлены штатные SSR CSS/fingerprint; маршруты, namespace и handlers не менялись.

Base владеет разделителем и отступом из density tokens:4/8/12px. Обычный режим
остаётся без разделителя. Сверка AST пяти product files сохраняет128 handlers
и весь код вне className/separated. Новый общий guard обнаруживает aliases и
динамические className; внешняя компоновка остаётся разрешённой. Семь UI pins
согласованы; шесть frozen offline refresh сохранили lockfiles/React singleton.
SDK/skills pins неизменны. Scoped21 stages:90 product cases, шесть TypeScript,
source guards, reference81, настоящий архив, SSR/Auth/freshness прошли; Base28
и guard30 проверены отдельно (всего229 unique cases, без повторного сложения).
IAB48 contexts подтверждают темы, плотность, размеры320/375/1920/2560, крупный
текст, обычный соседний режим, pending и callback один раз при явном переходе.
Это source QA общей реализации; authenticated страницы продукта, built assets,
HTTP parity169, полный интегрированный gate и реальный zoom200 пока открыты.
Доказательства: private evidence/pagination-separator-20261025/. Новый standalone
пример: pdlc-ui example PageNavigation --case separated. Runtime не менялся.

## Предыдущий кандидат: выбор ресурсов Base — 25 октября 2026

UI pin `c3a7c578a1c1b21dd5759c0bd5c0f917e9b584b9`, reference
`a5638c1ff93a91b89a1b3f9849c1edced20a54a7fa38dc5874794f9414da3772`.

Принят UI-кандидат и штатный SSR CSS/fingerprint. Общий отступ пунктов не меняет
маршруты и namespace-логику; icon-grid сохраняет центрирование и padding8.

Семь consumers используют один UI SHA; шесть frozen offline refresh сохраняют
lockfiles и React singleton. SDK/skills pins не менялись. Scoped gate830e41ea
прошёл24 стадии:156 product и36 Base cases, шесть TypeScript/source guards.
Для итогового CSS inputs повторены reference/archive/freshness и SSR/Auth;
JS test inputs подтверждённо неизменны. Повторные прогоны не суммируются.
IAB source QA:24 сочетания light/dark/gray × standard/large ×320/375/1920/2560;
40/44px, зазор8px, Escape/focus, URL/Back/Forward/reload, ошибки и выбранный ресурс
вне страницы. Синтетические GET-only данные; runtime/credentials не используются.
Это не authenticated приёмка продукта. Built Storybook regression, полный gate
новой волны, HTTP parity167 и реальный zoom200 остаются открытыми.
Доказательства: private evidence/search-filters-20261025/. Общий остаток — в Base
`docs/plans/shared-ui-consolidation-20261021.md`; публикация и установка отдельно.

## Предыдущий кандидат: общие части меню — 25 октября 2026

UI pin `1500913e136476d84aee90fbe38017b518f39d95`, reference
`cac88571998322babd4e11e42e7ce0614c673c6925fb23421b92ec3322926544`.

Штатный CSS export/fingerprint обновлён; продуктовые templates, macros, JS adapters, данные и routing не менялись.

Base владеет подписями, разделителем, метриками пунктов и Button size=icon.
Product callbacks, URLs, ACL и запросы остаются у владельца. Шесть frozen offline
refresh сохранили React singleton/версии и locks; SDK/skills pins независимы.
Scoped qualification: 128 product + 15 Base + 29 guard + 81 reference cases,
шесть TypeScript, examples/types, настоящий архив и SSR/Auth freshness прошли.
IAB общего меню: 24 сочетания темы/плотности/ширины; callback один, focus/40–44 px
и границы проверены. Это source QA, не authenticated или установленная приёмка.
Новый built Storybook, production assets, HTTP parity164, hosted CI и публикация
остаются открытыми. Доказательства: private evidence/menu-parts-20261025/;
общий оставшийся scope — в плане Base.

Предыдущая Button/Autocomplete волна отдельно завершила полный gate31/4290 и
HTTP parity160 на прежних exact heads; она не является новым полным прогоном
текущих menu inputs. Runtime/данные/credentials этим source-этапом не менялись.

## Предыдущий кандидат: компоновка Button — 25 октября 2026

UI pin `5338d65de4fb300df4b759f5865b2ee2fc92d1ce`, reference
`d7158acef7806c90d9d2a2967d22f795dde8b01826874b8073b0ca96df9967f6`.

Обновлён штатный CSS export/fingerprint; macros, routing и JS adapters не менялись.

Base устранил перекрытие responsive hidden/display и выравнивания общим CSS.
Цвета, padding, радиусы и минимум 40/44 px принадлежат Base. Шесть изменённых
product AST сохраняют все данные/handlers вне className. Guard: 39 cases и
шесть source contracts; IAB: 168 пар общего Button. Это не приёмка backend.
Итоговый frontend/reference gate и built browser test пока открыты. SDK/skills,
runtime, данные и credentials не менялись. Прежняя квалификация имеет свой scope.

## Предыдущая волна: фирменные подсказки — 25 октября 2026

UI pin `56cf8a2f63b2b853103c164bbf1f7758a90e8db0`, версия 0.3.2; reference
`3d88aadb70081f614a1ef51481c32724c53bcd7c6135045d96bc7be2a1dfd1d4`.

Нового SSR-контрола автодополнения нет и вымышленный аналог не заявляется. Общая CSS и
fingerprint получены штатным экспортом Base; маршруты, macros и JS adapters не менялись.

Новый контрол и его popup принадлежат Base. IAB проверяет общую реализацию,
а не authenticated страницы продукта; прежние результаты сохраняют свой scope.
Scoped source/static прошёл: шесть strict TypeScript/CLI/choice consumers,
Base types, examples, reference/coverage, настоящий offline UI-архив, SSR/Auth.
Данные Radix подтверждают один layer stack у шести потребителей. Отдельно
прошли 26 Base, 104 product cases и 8 Forge preview cases. Полный frontend
gate и hosted CI этой волны ещё открыты; прежний полный PASS не подменяет их.
SDK/skills pins, установленный runtime и пользовательские данные не менялись.
Девять owner AGENTS уточняют выбор AutocompleteInput/Select/SearchableSelect.
Общий остаток ведётся в Base `docs/plans/shared-ui-consolidation-20261021.md`.

Статус: source-изменения и адресная локальная проверка; публикация и установка
не выполнены. UI producer — `9eaa68c8bf25114ceee6fb31ffe6b7280185fab2`,
reference — `3636f1705d5820b8f9f4f05e8ec0891ac20b2ce0eecf951a239b3acc5741b5d7`.
SDK и skills pins не меняются.

## Реализация

Namespace-карточки и переключатель профессии используют IconMark из штатного
SSR-экспорта Base. Локальное оформление знаков и неиспользуемый Python-расчёт
контраста удалены. Идентификаторы, подписи, SVG-данные, предметные цвета,
навигация и обработчики сохранены; новые запросы и записи не добавлены.

В raw-text CSS исправлено преобразование URL шрифтов: Jinja больше не вставляет
HTML entities вместо кавычек. Пустой и `/workflow` deployment prefixes проверяются
через настоящий HTTP-ответ страницы и точные bytes опубликованных font assets.

При authenticated IAB-проверке обнаружена ошибка общего classic SSR bootstrap:
экспорт Base терял локальное имя импортированного валидатора цвета. Причина
исправлена у владельца, Workflow получает результат штатного экспорта. Продукт
не создаёт отдельную реализацию branding runtime.

## Проверка

Финальные 50 адресных Python cases, Ruff изменённых Python-файлов, SSR fingerprint
check и diff check прошли. Прежние полные Python/PostgreSQL/coverage результаты
сохраняют свой исходный scope; новый полный gate этим прогоном не заявляется.

В собственном временном QA-контуре проверены обычный вход через совместимый Auth
fixture и фактическая отрисовка Inter и Noto Sans в Workflow. IAB CSS platform-font
inspection подтвердил custom fonts, а не только наличие CSS-переменной. Смена
подтверждённого font preset применилась в открытой странице без reload.

Проверены 24 сочетания двух шрифтов, трёх тем и ширин 320/375/1920/2560;
отсутствие горизонтального overflow, высоты контролов 40/44 px и общие знаки.
В открытом выборе иконок видны 36 SVG-вариантов; Escape возвращает focus на trigger
без изменения значения. Использованная версия Auth fixture не подтверждает
новую сборку Base Auth. Установленные runtime и credentials не использовались.

Собственные процессы и точная временная Compose operation `807486fb1b33` закрыты
через канонический ownership helper; отсутствие принадлежащих ей ресурсов и
неизменность source inputs подтверждены. Полная route-матрица, настоящий zoom
200%, интегрированный gate, hosted CI и установленная платформа остаются открытыми.

## Сведение с upstream

Итоговый UI pin — d6c0914ae7bab37fc91b5f10602ad05543551ec0, fingerprint
`5f4ff5f4ada180236c2d6e014b52e78ad60586824980c7b45316eb20b44a69a8`.
Base включил свежий main 17973ae4 и сохранил его минимальное исправление
classic alias вместо второй реализации преобразования импортов. Штатный export
обновил bootstrap и fingerprint Workflow; check прошёл. Свежие 21 Base regression
cases проверяют фактическое исполнение runtime, defaults, неверные цвета и font
tokens. Предыдущая font-IAB приёмка относится к точным assets producer 9eaa68c8;
она не объявляется fresh browser-проверкой изменившегося bootstrap. Новый полный
gate и source publication остаются открытыми; SDK/skills pins неизменны.

## Поставка справочника и source guard

UI pin — eb3ceceeb1b1c5029ccaaa9b863d6646b35b1a46; reference
`5a702cb74a6eff5ec0e298ebdee609e70703e4fb01eda9e101cf7be84f019d36`.
Этот срез добавляет пример Notice и source guard React-потребителей. Штатный SSR
check совпадает с имеющимися assets; повторный export и компиляция не требуются.
Workflow templates/handlers и независимые SDK/skills pins не меняются. Прежний
font/SSR протокол сохраняет свои inputs; новая authenticated-проверка точного
bootstrap и интегрированный gate остаются открытыми. Установка не выполняется.


## Списки и пагинация — 24 октября 2026

UI pin обновлён согласованно. Изменение относится к React PageNavigation; канонические SSR/Auth fingerprints совпадают, повторный export и Python/backend compile не выполнялись.

UI producer `ff303ac5a273dc6b265292465b8b9db9a9476f9f`, fingerprint `206bf4889e50889e8c7bfab9aec36ef52df2e1e76dfcaa94a3ac756a7b80e2bf`.
Проверки относятся к исходникам собственных checkout; установка, hosted CI и общий
интеграционный gate сохраняют отдельный статус. SDK/skills pins не изменены.


## Сообщения, статусы и семантическая пустота — 24 октября 2026

Изменены только точный UI pin, штатный base-ui.css (+6 строк для EmptyState heading) и fingerprint. JS, macros, Python, API и данные не менялись. Auth export не имеет Git byte-diff. SSR/Auth freshness проверяется отдельно; новая native/PostgreSQL квалификация для этой CSS-only дельты не заявляется.

UI producer `56f27ee55bb0481ecc4733a0bb58144ae3cfed60`, reference `ba456575dd41f6237911ee97d0cec9de7c5f39941965714d3e4d86d09b0d8a2d`. Семь UI pins согласованы; шесть frozen offline refresh без downloads сохранили React singleton. SDK/skills pins не менялись.

Доказательства сохранены в private evidence/shared-message-audit-20261024/. Общий интеграционный gate, hosted CI, source publication и установленная приёмка остаются отдельными открытыми этапами.


## Общие заголовки и видимый фокус — 25 октября 2026

Обновлены точный UI pin, штатный CSS (+4 строки общего focus-visible PageHeader) и fingerprint. JS, macros, Python, DTO, обработчики и БД не менялись. SSR freshness прошёл; новая native/PostgreSQL квалификация для этой CSS-only дельты не выполнялась.

UI producer `88e4ed54546181c6ffa46a38651b6553cd4e3aff`, reference `9d8689e5c5e52fd6bc3dd3d2b4b030bc992af26cfa22d626c15268765bb06316`. Семь UI pins согласованы, шесть frozen offline refresh без downloads и сторонних upgrades сохранили React singleton. SDK/skills pins неизменны. Настоящий UI-архив и offline CLI проверены вне workspace. Общий интеграционный gate, hosted CI, публикация веток и установленная приёмка остаются открытыми.


## Общий возврат фокуса и presentation — 25 октября 2026

Только обновлены UI pin, штатный CSS (+4 строки focus-visible Table) и fingerprint. JS, macros, Python, API и данные не менялись. SSR freshness прошёл. Новая native/PostgreSQL и authenticated-квалификация этой CSS-only дельтой не заявляется.

UI producer `ed8edd288f3980b521258bcac9082bfb88856b69`, reference `1424252c8cf384eb42385d5692daa148d0df30796f2a79cf100dd87e56e54743`. Семь UI pins согласованы; шесть frozen
offline refresh без downloads и сторонних upgrades сохранили React singleton.
SDK/skills pins неизменны. Настоящий архив UI содержит 780 файлов; offline CLI,
новые карточки и самостоятельные примеры проверены вне workspace без Storybook.

Общий IAB срез: 144 уникальных сочетания шести source-композиций, трёх тем,
двух type_scale и ширин 320/375/1920/2560. Из-за пропущенной утилиты временной
QA-страницы Table 24 сочетания перепроверены; 120 остальных сохранены после
доказанного сравнения CSS. Дополнительно 18 уникальных открытых Portal-сцен,
native Tab/ArrowRight таблицы и URL-навигация Forge. Продуктовые записи отключены
синтетическими adapters; это не backend или установленная приёмка. Снимок
ревизии Wiki и context drawer Fleet имеют unit, но не отдельный IAB proof этой волны.

Доказательства: private evidence/dialog-compositions-20261025/. Временные
процессы и IAB-вкладка закрыты, source inputs сохранены, API-запросов нет.
Общий интеграционный gate, HTTP parity, настоящий zoom 200%, публикация,
hosted CI и установленная приёмка остаются открытыми. Runtime не изменён.

## Общая типографика строк ресурсов — 25 октября 2026

Получены штатные resource_list_title/resource_list_description macros, CSS и fingerprint. Python, маршруты, данные и обработчики не менялись. SSR freshness прошёл; новая native/PostgreSQL/authenticated-квалификация остаётся в общем gate.

UI producer `1848c08d68f8a60f7dc179751984e8c821647373`, reference `250d3c802e3a22b4095efb70defe6b0baff379fd6b1c1f7bbcf9c10d2e30b983`. SDK/skills pins этой UI-волной не менялись; принятые upstream SDK-переходы сохранены. Семь UI pins согласованы. Frozen offline refresh шести React-потребителей сохранил locks и React singleton. Workflow получил штатный SSR export, Auth export не изменился.

IAB: 168 уникальных сочетаний Base и шести реальных source-композиций, трёх тем, двух type_scale и ширин 320/375/1920/2560 без overflow; семь снимков просмотрены. Изменённый Fleet проверен повторно вместо прежних 24 результатов. Данные синтетические, записи отключены; backend/установленная приёмка не заявляется. Собственные временные процессы и вкладка закрыты.

Доказательства: private evidence/remaining-ui-20261025/. Общий integrated gate, HTTP parity, zoom 200%, source publication, hosted CI и установленная приёмка остаются открытыми. Продолжается классификация других локальных компонентов и SSR/dev-preview.

## Общая offset-навигация — 25 октября 2026

В этой волне изменён только UI pin; runtime sources и backend не менялись. UI producer `97399e00e275c953c28a77d1b178a22a79ca2a93`, reference `48721f30d2841d0c76e086876340f5b5367953df4519118c9d92956b08c9f4cb`. Семь pins согласованы; frozen offline refresh сохранил locks и React singleton. SDK/skills pins неизменны. SSR/Auth assets проверены без byte-diff и повторного экспорта.

Base: 17 scoped cases; IAB Base/Admin — 120 уникальных сочетаний, пять просмотренных снимков, keyboard/URL transitions без записи. Архив и offline CLI проверены вне workspace. Это source proof с синтетическими GET-only данными; интеграционный gate, публикация, hosted CI и установленная приёмка остаются открытыми. Доказательства: private evidence/offset-navigation-20261025/.
