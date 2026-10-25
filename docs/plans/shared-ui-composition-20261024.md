# Общие композиции Workflow: иконки и SSR-брендинг

## Текущий UI кандидат: ResourceStateView — 25 октября 2026

UI producer `93303ba042832195c636302fef147901631a054d`, версия 0.3.2, reference
`c1c01d526009aa3a7240fe63c53b8053392f81090a47b472a569f6fd4e3397b5`.
Совместимое children у ResourceStateView централизует показ подтверждённого
содержимого; переход ready ↔ partial-error сохраняет ввод. Продуктовые API,
DTO, права и предметные композиции остаются у владельцев. SDK/skills pins
не меняются. Это source adoption, установка и runtime не изменялись.

## Предыдущая волна: SSR-названия ресурсов — 25 октября 2026

Dashboard и карточки фаз используют восемь call sites канонических
resource_list_title/resource_list_description Base. Удалены 13 локальных
font-size/weight/color/line-height/overflow-wrap деклараций; внешняя раскладка,
DOM-hooks, scoped URL, данные и handlers сохранены полной source-сверкой.
Составная подпись задачи остаётся экранированной через Jinja capture, без safe
на пользовательских значениях. Типографика теперь соответствует React-контракту.

42 template cases PASS, включая исходный RED, одинаковые названия с разными IDs,
экранирование и 1/2/8 фаз. Штатный SSR fingerprint актуален. IAB: шесть baseline
и 72 positive contexts, три темы, две шкалы, четыре ширины, compact/readonly/empty,
порядок focus. QA использует точные rendered fragments, не runtime приложения;
закрыт без HTTP-записей и с неизменными inputs. Неправильный reset первого private
показа исправлен в fixture; продуктовый box sizing не менялся.

Base UI producer 900b8dc531c33bfafe939623b6aa18c225f9a29d и reference b5ce47fe31e4
сохранены. Общие UI/SSR assets и все независимые pins byte-identical; новый
пакет, install, compile, backend или Storybook build не нужны. Предыдущие gates
переиспользованы по inputs, не названы свежими. Source-коммиты локальные;
hosted CI, push, merge и установленный runtime не затрагивались.

## Предыдущая волна: подтверждение действия Base — 25 октября 2026

UI producer `900b8dc531c33bfafe939623b6aa18c225f9a29d`, reference
`b5ce47fe31e4a6ee67838e825c1acc0c743b2de0ad6e3956b01f2f3916c3a468`, версия 0.3.2.
Штатный SSR export --check PASS; SSR assets и продуктовые шаблоны этой поставкой не менялись. Прежние 41 template cases переиспользуются по неизменным SSR inputs, не считаются новым прогоном.

SSR/Auth freshness проверена отдельно; React API не имитируется новым SSR macro. Совместный scoped gate: 124 product cases, 49 Base confirmation,
60 guard и 87 reference cases PASS. Настоящий UI-архив содержит новый компонент
и offline CLI; шесть cached frozen refresh сохранили locks и React singleton.
Семь UI pins согласованы; SDK/skills pins сохранены. Source guard из этого
кандидата также включает прежнее исправление conditional const className.

IAB общего компонента: 36 контекстов и восемь сценариев; отдельные точные
Tracker fragments — 13 контекстов, label click, клавиатура и disabled. Оба QA
закрыты, source hashes стабильны, HTTP-записей нет. Это source-проверка, не
приёмка authenticated/установленного продукта. Исходные ошибки test setup и
private verification helper сохранены отдельно, не считаются PASS; успешные
install не повторялись. Полный milestone и общий семантический аудит продолжаются.
Push, hosted CI, merge, runtime и production не выполнялись.

## SSR: классификация оставшейся разметки — 25 октября 2026

49 native controls в 13 собственных top-level templates классифицированы по
реальным Base CSS/runtime: 16 button DOM adapters, 11 legacy .btn adapters,
семь backing select, четыре menu items, две card selection buttons, пять input
и четыре textarea. .btn находится в Base legacy.css и использует общие tokens;
это не 11 продуктовых копий CSS. Product bootstrap вызывает штатные initChoice
и initTextareaAutosize; варианты/права/IDs и callbacks остаются у Workflow.
Макрос не заменяет callback/data contract, которого в его API нет.
Классификация подтверждает владельца presentation-кода этих controls, а не
полноту динамического DOM, CSS overrides или live-поведения. Текущие source
templates/assets не менялись. Ограниченный inventory сохранён в evidence задачи;
общий аудит композиций/SSR и интеграционный gate продолжаются.

## Предыдущий кандидат: текстовые ссылки Base — 25 октября 2026

UI producer `a27339a2efe253124770ff103a209e7212e2c11b`, reference `464b512a10dd44ec66aeeb09e791123e5a07e245346922898225f19db442fd35`, версия 0.3.2.
Предметные шаблоны, JS и штатные SSR assets не менялись; свежие export --check и 41 template regression PASS. Изменён только UI pin.

В волне 44 inline-ссылки переведены на существующий TextLink в 28 файлах;
ещё один standalone переход Admin использует Button asChild. Данные, права,
URL/namespace, target/rel и обработчики остаются у продуктов. Slot принимает
строковый className ребёнка; callback-className NavLink не поддерживается этой
композицией. Активная навигация использует SidebarItem с явным active.
Существующий source guard проверяет native/Router links и доказанные прозрачные
фасады, не угадывает shadowed bindings или неиспользуемый className.

Проверки изменённых frontend и Base: 236 runtime cases плюс 13 Admin detail,
types/lint, reference и guard regressions. Неизменные проверки переиспользованы
по inputs; они не объявлены новым прогоном. Финальный настоящий UI-архив/offline
CLI PASS; шесть cached frozen refresh и фактических CLI check подтвердили новый
fingerprint, неизменные prepared lockfiles и React singleton. AI file-URI изменён
явно. SDK/skills pins сохранены; dev guard читается из точного source Base,
он намеренно не является runtime-файлом npm-архива.
IAB shared scene: 36 контекстов, три темы/шрифта, две шкалы текста и четыре
ширины; ссылки, focus, Enter, history и overflow. Отдельный Admin fragment —
54 контекста. Оба QA закрыты, inputs стабильны, HTTP-записей нет. Это source
проверка, а не приёмка установленного или authenticated продукта.
Полный milestone gate, hosted CI, публикация и установка остаются отдельно.
Общий аудит продолжается; каноническая матрица — shared-ui-consolidation-20261021
в Base. 93 оставшихся native React candidates классифицированы как семантическое
содержимое/слоты Base, два скрытых file bridges и token swatch; это не 93 копии.

## Предыдущий кандидат: кодовые поля Base — 25 октября 2026

UI producer `7432f931cddcba29f0c6bc91ca2cf6663baa771f`, reference `9154aea77e9265a2abca532e909b5c3836678814123aeee51d3fc36703b7b4f5`, версия 0.3.2.
Штатный SSR CSS и fingerprint обновлены; macros, JS, маршруты и dirty tracking не менялись. Freshness и 41 template regression PASS.
Base исправляет приоритет font-mono у Input/InputWithAction/Textarea одним CSS-
правилом. Обычный шрифт и минимум 40/44 px сохранены; Textarea сохраняет собственную
высоту, autoSize учитывает переносы нового шрифта в пределах min/max-height.

Свежие проверки волны: 17 field, 61 CSS/primitive, 86 reference и 41 Workflow
SSR cases; types/examples, настоящий архив/offline CLI и fingerprints PASS.
IAB: 105 положительных React/SSR/standalone/density контекстов плюс ввод, focus,
action/reset и рост/сжатие autoSize; 18 исходных контекстов подтвердили дефект.
Прежние продуктовые types/unit/lint переиспользованы по неизменным JS/TS inputs,
они не названы новым прогоном или доказательством CSS. Шесть cached frozen refresh
проверили fingerprint и React singleton. AI file-URI обновлён явно; installs не
изменили подготовленные locks. SDK/skills pins сохранены.
Source QA не заменяет live-приёмку продукта. Installed-header Playwright regression
подключён к существующему manual CI gate; локально этот runner не запускался.
Полный milestone gate, hosted CI и установка остаются отдельно. Общий аудит
продолжается; детали — план Base shared-ui-consolidation-20261021.

## Предыдущий кандидат: смысловые подписи и общие действия — 25 октября 2026

UI producer `bbfec663f0cd9e3c92c75bb0e1f367b17f682f76`, reference `dea80c36822dcfc94dd3ca81970bac0c0c4868d94718708fac180b2cc510b4c0`, версия 0.3.2.
SDK/skills pins сохранены; шесть frozen offline refresh сохранили locks и React singleton.

UI pin и штатные SSR CSS/macros/fingerprints обновлены. Checkbox/radio macro получают trailing label_tone; прежние calls сохраняют default, у radio собственная подпись есть только в appearance=card. 41 SSR regression и freshness прошли; продуктовые routes/dirty tracking не менялись.

Base проверен отдельно: 17 React, 35 primitive/SSR и 85 reference cases.
Вся scoped-волна: 13 source + 27 consumer stages, 343 unique cases, архив/offline CLI,
SSR/Auth freshness. IAB: 288 публичных UI-контекстов, native events/reset, namespace
href и keyboard/focus; source QA закрыт без сетевых записей. Это не live-приёмка
продуктовых страниц. Полный milestone gate, hosted CI и installation остаются отдельно.
Подробности — план Base shared-ui-consolidation-20261021; private evidence:
control-presentation-20261025/. Общий аудит продолжается.

## Предыдущий кандидат: описание и отступы карточек — 25 октября 2026

UI producer `4f9140a66d99f32ca656e5008022d25a960d0e31`, reference `1c1f0d864adfd8a23dcf4f656be59cc746c9a915308396c29387ad0f267134d2`, версия0.3.2.
SDK/skills pins независимы и сохранены.

Обновлены UI pin, штатные SSR CSS/macros и fingerprints. Новый card_description доступен, существующих предметных callers для него не добавляли. 41 SSR shell regression и freshness прошли; routes, namespace и dirty tracking не менялись.

Общий контракт — CardDescription/default/muted и card_description SSR.
Отступы CardHeader/CardContent принадлежат density tokens; локальные padding
обнаруживает существующий guard. Полная AST-сверка восьми файлов с негативным
контролем допускает только заявленные presentation-замены, без изменения логики.
Шесть frozen offline refresh сохранили lockfiles и React singleton.

Общие доказательства:10 source +24 consumer scoped stages;279 unique cases
(8 Base React,34 primitive/SSR,84 reference,112 consumer,41 Workflow SSR).
Настоящий архив:802 файла,1120797 bytes; offline CLI, SSR/Auth freshness PASS.
IAB72 computed-style контекста и24 standalone контекста:три темы,три плотности,
standard/large и320/375/1920/2560. Прежнее оформление и отступы сохраняются;
keyboard link/focus/Back/reload проверены. Это source QA, не live-приёмка продукта.
QA закрыт, hashes стабильны, сетевых записей нет. Hosted CI, built Storybook,
real zoom200 и installed/authenticated acceptance остаются отдельными gates.
Private evidence:card-presentation-20261025/; общий план Base продолжается.

## Предыдущий кандидат: общие страницы отказа и отсутствующего ресурса — 25 октября 2026

UI producer `c2be7939e8b7622a29e1a30ff1c8b6d5ae731a59`, reference `d74c7cccb8a70fb2ca78348071037ed3af045fb5e0cbe0109327de3e4f52ffb3`, версия0.3.2.
SDK/skills pins независимы и не менялись.

Обновлены UI pin и штатные SSR CSS/fingerprint. Macro state сохраняет прежний контракт: React title/icon/headingLevel/back автоматически не сериализуются. HTTP, namespace, dirty tracking и data model не менялись.

Base владеет необязательными title/headingLevel/icon/back для терминальных
ResourceStateView. Defaults остаются h2 с прежними подписями; самостоятельная
страница может использовать h1 и типографику PageHeader. Иконка декоративна,
геометрия/цвет/отступы принадлежат общим tokens. Новый standalone пример и story
Terminal добавлены без изменения прежних IDs, schema2 и API v1.

Кандидат прошёл27 scoped stages и адресный повтор затронутых Fleet checks после
уточнения h1. Итоговые наборы:113 React cases,83 reference и41 Workflow SSR
(237 unique, без сложения повторов), types/lint/format, шесть consumer guards,
examples, настоящий архив/offline CLI и SSR/Auth freshness. Frozen offline refresh
сохранил consumer locks и React singleton; у AI Hub заменён только URI UI-снимка.

IAB:72 контекста Base/реальной Forge page,9 проверок плотности и48 контекстов
публичных состояний с точными Fleet route props; standard/large и три темы,
320/375/1920/2560 без overflow. Проверены отступы,40/44px, Namespace keyboard
return, Back/reload и однократное действие standalone примера. Fleet admission
проверена отдельно на реальных route elements с тестовым источником permissions.
Это source QA без credentials и установленного backend. Обе QA-сессии закрыты,
hashes стабильны, сетевых записей нет. Built Storybook, real zoom200, HTTP runtime
parity, hosted CI/публикация и installed/authenticated acceptance не подменяются.
Доказательства: private evidence/terminal-states-20261025/.

## Предыдущий кандидат: фокус каталога и прямой LoadingState — 25 октября 2026

UI pin `5f1271e387a1ae2dc933d7e14d5397df446092b4`, reference
`c33652802684ecea5e4dfd1fef4e14cf59daa8aa43710ebae4f02297469ac9f4`, версия0.3.2.

Штатно обновлены CSS и fingerprint. Macros/branding JS неизменны; source-only template checks не означают установку React picker в SSR Workflow.

SearchableSelect Base сохраняет точку взаимодействия при чтении страницы и retry.
Pending скрывает старые данные и удерживает focus в Dialog; после ответа выбирается
доступное направление или recovery. Поиск пользователя и закрытие имеют приоритет.
Выбор значения и callback чтения не запускаются самим восстановлением focus.
PageNavigation сохраняет native disabled; локальные focus-копии не добавляются.
AST трёх роутеров подтверждает удаление только пустых обёрток с сохранением routes;
негативный контроль проверяет полный обход AST. Семь UI pins совпадают; шесть frozen
offline refresh сохранили locks/React singleton, SDK/skills pins не менялись.

Scoped gate25 stages прошёл:78 product cases (Tracker10, Wiki27, Forge29, Admin11,
Fleet1), Base28, guard32, reference83 и Workflow41 —262 unique cases без повторов.
Шесть TypeScript/source guards, examples, coverage, архив и SSR/Auth freshness PASS.
IAB24 адаптивных contexts и6 recovery contexts подтверждают три темы, standard/large,
320/375/1920/2560,40/44px и отсутствие overflow. Отдельно проверены приоритет поиска
и закрытие pending. Это source QA. Built Storybook, HTTP parity179, полный gate,
реальный zoom200, hosted CI и authenticated/installed приёмка остаются открытыми.
Публикация/runtime не выполнялись. Доказательства: private evidence/paging-focus-20261025/.

## Предыдущий кандидат: группы полей и подробности — 25 октября 2026

UI pin `c04047590f9931fcef39ad328512a22f07149934`, reference
`11c4fc27a5087eaecbcaaad822832729e6a5c434797e835cbe832acdf44df745`, версия0.3.2.

Штатно обновлены CSS/macros и fingerprint для совместимых fieldset separated и disclosure tone/size; маршруты и обработчики Workflow не меняются.

Base владеет разделителем/плотностью Fieldset и вариантами appearance/tone/size
Disclosure. Внешняя компоновка, смысл, native children, open и действия остаются
у продукта. Удалены восемь presentation-копий; AST семи файлов подтверждает111
неизменных обработчиков и код вне перевода классов в props. Guard дополнительно
обнаружил compact-секцию Wiki; исправлена причина, правило не ослаблено.

Семь UI pins согласованы; шесть frozen offline refresh сохранили locks и React
singleton. SDK/skills pins не менялись этой волной. Scoped gate23 stages прошёл:
202 product cases (Tracker92, Wiki15, Fleet78, Forge17), шесть TypeScript/source
guards, reference82, настоящий архив и Workflow41. Отдельно Base8, SSR4 и guard32
прошли (всего369 unique cases этого среза, без сложения повторных прогонов).
IAB48 сочетаний React/SSR подтвердили три темы, плотность, standard/large и
320/375/1920/2560,40/44px, контраст и отсутствие overflow; отдельно проверены
FormData, disabled, сохранение ввода, Enter/Space и действие только по нажатию.
Это source QA. Built Storybook regression, HTTP parity177, полный gate, реальный
zoom200 и authenticated/installed приёмка остаются открытыми. Публикация и runtime
не выполнялись. Доказательства: private evidence/field-disclosure-20261025/.

## Предыдущий кандидат: разделы и выбранные строки — 25 октября 2026

UI pin `10896c8afcdd1227043f7290183f8044a0c21365`, reference
`7ba477baa2eda2f0e93bf58d14687717f64a9b72b7a955e4d9b1f390b9c9f14d`, версия0.3.2.

Штатно обновлены CSS/macros, branding runtime/bootstrap и fingerprints; маршруты, данные и handlers Workflow не меняются.

Общий Base оформляет разделители, технические блоки и выбранную строку.
Нативная семантика, выбранный ID, действия и внешняя компоновка остаются у продукта.
AST пяти изменённых файлов подтверждает63 неизменных обработчика. Расчёт брендинга
учитывает текст и статусы на поверхности выделения: исходный документ не меняется.
Семь UI pins согласованы; шесть frozen offline refresh сохранили locks и React singleton.
SDK/skills pins не менялись этой UI-волной; прежние upstream revisions сохраняются.

На итоговом кандидате прошли69 product cases (Admin8, Wiki15, Fleet46),22 branding
React,11 Node runtime/bootstrap и41 Workflow template cases; checked JS, examples,
reference/coverage, настоящий архив и SSR/Auth freshness. Шесть TypeScript и source
guards прошли на02ff0f78; публичные TS-контракты после него не менялись. IAB36
сочетаний трёх тем, трёх акцентов и320/375/1920/2560 подтвердили текстовый контраст
от4,51:1, marker, native row и отсутствие overflow; keyboard/pointer сохраняют focus.
Это source QA общей реализации. Built Storybook, HTTP parity173, полный gate,
реальный zoom200 и authenticated/installed приёмка остаются открытыми. Публикация
и runtime не выполнялись. Доказательства: private evidence/section-table-presentation-20261025/.

## Предыдущий кандидат: общий разделитель пагинации — 25 октября 2026

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
