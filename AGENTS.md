# AGENTS.md

## Docker и Kubernetes

Поддерживаются обычный Docker/Compose без Kubernetes и Kubernetes. Общие API,
данные, настройки и правила исполнения сохраняют одинаковый смысл в обоих
режимах; особенности оркестратора принадлежат deployment-адаптерам.
Перед изменением runtime/config/storage/runner читать [стандарт Base](https://github.com/FerrPOINT/services-base/blob/29a709834fba54a823873b82050731333d7e3d97/docs/REPO_STANDARDS.md#поддержка-docker-и-kubernetes).
Затронутый сценарий проверять отдельно в обоих режимах на точном кандидате;
непроверенный режим оставлять открытым gate. Docs-only правки не требуют deploy
или пересборки. Ссылка фиксирует решение Base, не меняя SDK/UI/skills pins.

## Правила репозитория

1. После завершения задачи нельзя оставлять готовую работу в незакоммиченном состоянии.
   - Сначала прогнать релевантные проверки.
   - Для UI-изменений обязательно сделать браузерную проверку и скриншот.
   - Затем сразу сделать git commit по выполненной задаче.

2. Не считать задачу завершённой, если рабочее дерево осталось dirty по её изменениям.

3. Merge и deploy запрещены без явной команды пользователя.

## Обязательные проверки

Канонический локальный gate и expected output описаны в
`docs/quality-gate.md`; цели `Makefile` и `scripts/quality.ps1` повторяют эти
команды через `uv`, `constraints.txt` и текущий marker contract.

После любого изменения SQLAlchemy-слоя, application services, состояния UI или
Supervisor Engine перед commit выполнить следующие проверки:

1. **Tests**
   ```bash
   pytest -q --timeout=60
   ```
   Ожидается 0 падений и 0 ошибок. PostgreSQL integration tests здесь намеренно
   исключены и запускаются отдельно.

2. **PostgreSQL integration**
   ```bash
   pytest -q -m integration --timeout=120
   ```
   Ожидается 0 падений и 0 ошибок. Набор включает реальный путь CLI subprocess →
   PostgreSQL → тестовый OpenAI-compatible HTTP endpoint. Два multi-process E2E
   теста имеют собственный timeout 240 секунд.
   Маркер охватывает также admission/COMMIT regressions. Для application-clock
   case нужна отдельная пустая QA-база `request_clock_fixture` через
   `WORKFLOW_APPLICATION_CLOCK_TEST_URL`; без неё skip не подтверждает этот gate.

3. **Coverage**
   ```bash
   pytest --cov=project_workflow --cov-report=term --timeout=60
   ```
   Ожидается общее покрытие не ниже текущего локального baseline 94%.

4. **Lint**
   ```bash
   ruff check .
   ```
   Ожидается `All checks passed!`.

5. **Type check**
   ```bash
   mypy project_workflow scripts
   ```
   Ожидается `Success: no issues found`.

6. **Readiness локального Compose**
   ```bash
   docker compose up --build -d --wait
   curl --fail http://127.0.0.1:8812/health
   ```
   Ожидается HTTP `200` и `database=ok`, `schema=ok`.

7. **Браузерная проверка** для изменений UI
   - Открыть `http://127.0.0.1:8812/` и `http://127.0.0.1:8812/phases`.
   - Сохранить скриншот.

## Примечания

- Для стандартного полного набора использовать `pytest -q --timeout=60`.
  `--forked` не требуется; при нём отчёт coverage некорректен.
- `DATABASE_URL` обязателен в runtime. SQLite используется только в изолированных тестах.
- `project-workflow` хранит имена skills. Действующий legacy-каталог сохраняет
  свой source; отдельный [Base candidate](docs/base-sdlc-candidate.md) закрепляет
  commit пакета `services-base/agent-skills`. Candidate не установлен: не менять
  default path, bootstrap, migrations и pinned history при подготовке документов.
- Профессия не задаёт общий профиль запуска и не показывает его в своей форме.
  При необходимости профиль относится к конкретному workflow в рамках профессии.
  `projects.launch_profile` пока сохраняется как legacy-контракт API/admission;
  не очищать его при обычном редактировании и не считать перенос исполнения
  реализованным без согласованной миграции. Идентификатор профессии — `code`;
  роль задачи задаётся назначением и режимом. Фазы не назначают отдельных агентов.
- Воспроизводимый CLI acceptance описан в `LIVE_TEST_PLAN.md`.

## Приёмка работы агента и advisor

Прямой тест Workflow выполнять по [DIRECT_CLI.md](manual/file-sandbox/DIRECT_CLI.md):
Codex сам работает через штатный CLI, Fleet не исполняет задание. Подготовленные
назначение и confirmation явно отмечать как входные тестовые фикстуры, не как
проверенное решение пользователя. Полный сценарий с первого сообщения — отдельная
граница; не подменять им прямой тест без поручения. Один завершённый режим не
означает приёмку остальных профессий.

Перед такой проверкой читать [регламент CLI-приёмки](manual/file-sandbox/README.md).
Оператор заранее готовит тестовые задания, доступ и назначения через настоящие
Auth и Tracker выбранной установки. Агент получает инструкции командой
`project-workflow --json step`, выполняет работу и отправляет отчёт той же
командой с `--report -`, стабильным ключом и возвращённой версией. Следующее
действие определяется фактическим ответом CLI; историю читать командой `history`.

Прямой вызов `SupervisorEngine`, application services, тестового HTTP-обработчика
или запись фаз/оценок в БД не заменяют эту приёмку. Unit-тесты и диагностику
движка отмечать отдельно. Для живой приёмки не подменять Auth, Tracker, advisor
или ответы CLI. Сохранять команды, stdin отчётов, stdout/stderr, версии,
ключи операций и CLI-историю; секреты не публиковать. Тестовые критерии фиксировать
до запуска. Не исправлять проверяющий код или сохранённые решения ради PASS.
Завершение подтверждать CLI-историей и независимой проверкой фактического результата.

## Осознанно исключённые возможности

Исторический standalone-профиль — внутренняя агентская утилита. В составе
многопользовательского PDLC условия изменились: публичные проектные данные
требуют central identity, общего admission и прежних write/admin ролей по
[плану единого пространства](docs/plans/unified-spaces-20261019.md).
Ни private network, ни отсутствие ProjectRef не открывают данные.
Приведённые ниже ограничения не отменяют эти правила доступа:

| Возможность | Решение | Причина |
|---|---|---|
| CI/CD pipeline (GitHub) | **Использовать** | Quality, coverage, PostgreSQL integration и Compose smoke воспроизводят обязательный локальный gate. |
| CORS, CSP, HTTPS redirect, rate limits | **По границам deployment** | Не добавлять общий framework ради задачи; public ingress и аутентификация/admission обязательны для PDLC. |
| Локальные credentials в `docker-compose.yml` | **Допустимо только локально** | Compose публикуется только на loopback; внешний runtime обязан передавать собственный `DATABASE_URL`. |
| Observability / metrics / structured JSON logs | **Не добавлять** | Request logging и `/health` достаточны для внутренней утилиты. |
| Дополнительный слой sanitization | **Не добавлять** | API использует строгие Pydantic-схемы, SQLAlchemy ORM и параметризованный SQL. |
| Connection draining сверх lifespan dispose | **Не добавлять** | Для внутренней утилиты допустим краткий разрыв соединения при перезапуске. |
| Bandit/safety/pre-commit hooks | **Не добавлять** | Принятый quality bar: `ruff`, `mypy`, `pytest` и coverage. |

Если изменятся исходные условия, например появятся внешний доступ,
многопользовательский режим или клиентские данные, этот раздел нужно пересмотреть
до расширения scope.

## Термины PDLC и общие компоненты

Перед изменением платформенных имён прочитайте [интеграцию с Base](docs/PDLC_BASE_INTEGRATION.md) и канонические TERMS/BRANDING.
Работа с SSR UI описана в разделе «Разработка UI со справочником Base» ниже.
Не переносите продуктовые запросы, DTO и права в общий UI. SDK/UI/skills pins независимы; новое имя платформы не меняет SDLC IDs/scopes или закреплённые внешние runtime-источники.

## Общие поля выбора Base

AutocompleteInput в React Base предназначен для свободной строки с подсказками; он не является
SSR select_control. У текущего SSR-контракта нет этого аналога: не подменять произвольный ввод
закрытым списком и не копировать локальный popup. При новой потребности сначала расширить Base
вместе с примером и штатным экспортом.

Сначала искать общий UI в Base: search → show → example. Общие исправления
вносить в Base; продукт передаёт данные, права, преобразования и сохранение.
Для закрытого списка с одним значением — Select; для нескольких — MultiSelect.
Одно значение из всех видимых вариантов — RadioGroup, взаимноисключающие режимы — appearance="segmented".
Вкладки с панелями используют Tabs. Каталог с поиском/пагинацией — SearchableSelect.
Использовать публичный @pdlc/ui и сверять наличие API по точному UI pin.
Контракт Select/MultiSelect: options, value/defaultValue, onValueChange;
HTML children/option/onChange/multiple/size больше не являются их API.
Видимые raw select и локальные копии оформления не добавлять. Технический form
bridge принадлежит только Base; SSR использует штатный macro и choice-runtime,
явный refresh после программных value/options и native fallback до успешного init.
Правила выбора и подключения: Base docs/platform/CHOICE_CONTROLS.md.
UI/SDK/skills pins независимы; установка и production — отдельные операции.

## Разработка UI со справочником Base

Открытая страница справочника может быть новее зависимости продукта: сверять
контракт по принятому UI pin. Если поиск пуст, уточнить запрос/фильтры и
проверить рецепты; отсутствие API проверить отдельно в актуальном Base.
Общий контракт добавлять в Base вместе с metadata и примером, затем явно
обновлять UI pin потребителя. Локальная копия не заменяет эту интеграцию.

Перед изменением SSR UI читать [маршрут разработки со справочником Base](https://github.com/FerrPOINT/services-base/blob/f7998b33d87e9ade59bbd6907a8145a70b0b8c00/base-modules/ui/reference/guides/agent.md),

Для компоновки и ревью web UI применять [рабочий маршрут Base](https://github.com/FerrPOINT/services-base/blob/f7998b33d87e9ade59bbd6907a8145a70b0b8c00/docs/platform/DESIGN_SYSTEM.md#рабочий-маршрут-изменения-ui):
задача → контракт → группы полей → применимые состояния → доказательство.
Source guard, unit и browser-приёмка различаются; ссылка на правила не обновляет UI/SDK/skills pins.

включая раздел для Workflow без Node frontend. Прочитать `.base-ui-revision`;
подготовить отдельный checkout этого SHA без переключения соседней рабочей ветки.
Запуск из него: `node base-modules/ui/tools/ui-reference/cli.mjs check`, затем
`search "задача"`, адресный `show` и один `example`. Node 22 достаточен;
npm install, frontend-пакет, работающие API/Storybook и доступ к стенду не нужны.
Для SSR использовать macro из карточки, штатный exporter и fingerprints;
React-пример не подменяет серверный контракт. Полный каталог не загружать;
новые возможности Base не считать принятыми без отдельного изменения UI pin.

Button, Input, Textarea, Checkbox, RadioGroup/Radio, Switch, меню, Card, Table, Disclosure,
Dialog, ActionGroup и Toaster/toast использовать из публичного @pdlc/ui. Общий дефект
исправлять в Base; продукт сохраняет данные, права и сохранение. Прямой Sonner,
копии примитивов и продуктовые определения общих tokens не добавлять.
Брендинг применяется общим runtime; draft preview изолируется BrandingScope.
Строки явных действий используют ActionGroup (SSR — action_group): перенос и gap
принадлежат Base, внешние margin/width/grid — экрану. Выбор значения использует
RadioGroup/Select; контекст ресурса не превращается в фиктивную строку действий.
Канонический контракт — Base docs/platform/DESIGN_SYSTEM.md и docs/BRANDING.md.
UI/SDK/skills pins независимы; source-изменения не означают установку.

SSR-каркас и page-frame/page-wide/page-readable/page-split принадлежат CSS Base.
Не дублировать их геометрию в base.html и не возвращать retired local styles
старой шапки/вкладок/переключателей. Порядок этапов, статус исполнения и предметная
компоновка сохраняют собственный контракт; оформление history rails принадлежит Base. Проверять реальные macros/assets,
а не наличие прежнего CSS-текста в шаблоне продукта.
Заголовок страницы использует base-page-title, раздел — section_header с прежним
heading_id. Native home link использует button(href=..., variant=ghost, size=icon),
ссылки действий — text_link, подтверждённая пустота — state. URL и namespace
остаются у Workflow. Не добавлять локальный skin или второй leave/history runtime.
Для частичной навигации использовать общий app_main и lifecycle Base; продукт
владеет загрузкой своего HTML и очисткой страничных обработчиков (docs/ui-shell.md).
Неизменяемые контроллеры находятся в templates/controllers и раздаются по хешу;
персональные данные остаются в private no-store HTML. Правила загрузки и
совместимости открытых вкладок — в docs/ui-shell.md.
После подтверждения ухода сразу менять URL, выделение раздела, заголовок и
рабочую область на Base loading; данные загружать асинхронно. Прежние данные
не сохранять под новым адресом. Ошибка чтения остаётся в целевом разделе с
Base error/retry; отмена ухода сохраняет исходную форму и адрес.

## Единое пространство PDLC

[Согласованный план](docs/plans/unified-spaces-20261019.md) вводит M:N и общий read admission. До полного
совместимого cohort это цель, не установленное поведение. Строгие V1/V2 и
applied migrations сохранять; ProjectRef/SpaceRef/V3 отдельны. Полный gate на
интегрированной вехе, в ходе реализации scoped checks. Runtime не активировать
по готовности одного продукта; не выбирать первый Project/Space неявно.

## Общие показатели

Dashboard metrics используют штатный Base macro metric со стабильными id.
Не возвращать локальные metric-* paint rules: геометрия, шрифт и состояния
принадлежат Base. Подсчёт, verdict → tone и внешняя dashboard-grid остаются
Workflow. Новый SSR API требует соответствующего UI pin и штатного export;
SDK/skills pins не изменять вслед за UI. Source-проверка не означает установку.

## Подписи и карточки вариантов выбора

После проверки API в принятом UI pin используйте label или children Checkbox/Radio
для обычной подписи, appearance="card" — для варианта с рамкой и описанием.
Не копируйте label с border/rounded/padding и не оборачивайте такой выбор в
Card asChild. Base владеет hit target, focus, checked/disabled и нативной формой;
продукт — данными, правами и обработчиком. Внешняя grid/flex-компоновка допустима.
SSR использует checkbox_control/radio_control с appearance='card'; отдельный
click-handler или повторное input/change для оформления не нужен.
Контракт и пример: Base docs/platform/CHOICE_CONTROLS.md, pdlc-ui example Checkbox --case cards.

Знак профессии использует IconMark / SSR icon_mark Base. Передавайте свой SVG
и нормализованный theme_color; размеры, фон, рамка и радиусы не копировать.
Для динамического рендеринга клонируйте inert template, созданный штатным
macro Base; не собирайте заново class/size/ARIA примитива в продуктовых JS.
Предметный SVG, цвет, подпись и badge count задаются после независимого clone.
Выбор иконки также использует IconMark: цвет тонирует подложку, не текст SVG.
Каталог значков, ID, сохранение и выбор workflow остаются у продукта.


Видимый выбор файла использует `Input type="file"` Base: кнопка выбора,
focus и disabled следуют теме и branding. Native файловый диалог остаётся у ОС;
чтение, проверка содержимого/размера и отправка — у продукта. Скрытый технический
file input за Button допустим; видимый raw input не добавлять. Для обновления
оформления сверять UI pin; CLI/Telegram без web UI не получают новых зависимостей.

Подписи web-полей оформлять публичным Label; подпись/подсказку/ошибку одного
поля — FormField Base. Продукт сохраняет текст, htmlFor/id, required, данные
и обработчики; не копировать типографику подписи и фон/рамку/радиусы/padding
Input/Textarea. Внешняя компоновка, высота Textarea и моноширинный код допустимы.
SSR использует field/label_control штатного экспорта принятого UI pin.

Названия и описания строк ресурсов используют resource_list_title и
resource_list_description Base. Внешние контейнеры, flex/grid, отступы и классы
для product handlers сохраняются; локальные font-size/weight/color не копировать.
Составную подпись передавать через Jinja capture при включённом autoescape,
без safe для пользовательских строк. Значения и построение URL остаются Workflow.

## Общая история событий

История событий и этапов использует Timeline/TimelineItem/TimelineMarker/TimelineContent
из Base, SSR — штатные timeline macros/classes. Порядок, статус → tone, данные,
параллельные группы и действия остаются у продукта. Маркеры декоративные;
состояние должно быть видно текстом. Не копировать rail/node CSS и не заменять
историю percentage Progress. Сначала проверить наличие контракта в принятом UI pin.


Обычные SSR actions рендерятся штатным button Base с label либо caller.
После проверки UI pin attributes передаёт owner handlers/data/hidden/form;
Base сохраняет приоритет type/id/variant/size и disabled/pending/ARIA.
Не копировать base-control/base-button или btn в product markup. Card и формы
используют card(tag=..., padded=true); пункты action_menu — action_menu_item.
Input/Textarea — штатные macros с attributes и optional id/name, без фиктивных
FormData keys. Один product template используется для initial/hydrated карточек.
Новые параметры требуют штатного SSR export; runtime этим не обновляется.


Все backing select создаёт select_control Base, включая profession_selector;
не возвращать raw select с data-base-choice. Названия/IDs/options, icon data и
input/change handlers сохраняются Workflow. Dynamic options требуют refreshChoice.
Для resource_list/row, timeline/item/content и section_navigation_item применять
штатные macros с owner attributes. Нативный ul/li/div и прежние IDs сохранять;
card_title(tag='div') и label_control сохраняют подписи формы без product skin.

## Общий inline-код и выделение записи

После проверки UI pin используйте InlineCode для оформленного одиночного кода,
Prose для prepared текста, CodeBlock для многострочного блока и
ResourceListDescription technical для подписи без поверхности. Не копируйте
фон/padding/radius native code. ResourceListRow highlighted задаёт только
оформление: текущий ID, aria-current, ref/tabIndex и действия остаются у продукта.
SSR: inline_code и resource_list_row из штатного экспорта Base.
Каноническое руководство — Base docs/platform/DESIGN_SYSTEM.md и pdlc-ui.


## Карточки фаз и инструкций

Одинаковые действия выводить общим `workflow-cards.html` на публичных кнопках Base;
не создавать отдельные наборы иконок/вариантов. Параллельная группа сохраняет
оранжевую рамку в списке, схеме и после изменения порядка. Точный owner-контракт,
общий frame template и проверки описаны в `docs/ui-shell.md`.


## Исполнение фаз

Непрерывный ряд parallel-фаз образует одну группу до первой sync-фазы.
UI и Supervisor используют domain/phase_grouping.py. Исторические связи и цели
возврата не разделяют группу и не управляют исполнением. Автоматического возврата
задания нет; старые команды с этими полями отклоняются. SQL-колонки, применённые
миграции и история сохраняются. Контракт и проверки — в docs/phase-execution.md.

## Проверка Git-гигиены

Перед коммитом: `python3 -B scripts/check_repository_hygiene.py --index`.
Перед публикацией проверять точный кандидат через `--ref <commit>`. Установка
hooks и допустимые артефакты: [правила](docs/REPOSITORY_HYGIENE.md).
Копии проверки принадлежат Base; SDK/UI pins не меняются.
