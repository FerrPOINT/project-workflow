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
   pytest -q -m integration tests/test_postgres_integration.py --timeout=120
   ```
   Ожидается 0 падений и 0 ошибок. Набор включает реальный путь CLI subprocess →
   PostgreSQL → тестовый OpenAI-compatible HTTP endpoint. Два multi-process E2E
   теста имеют собственный timeout 240 секунд.

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

Перед изменением SSR UI читать [маршрут разработки со справочником Base](https://github.com/FerrPOINT/services-base/blob/ae2b41291eee5af752daff89f760fba5aff41783/base-modules/ui/reference/guides/agent.md),
включая раздел для Workflow без Node frontend. Прочитать `.base-ui-revision`;
подготовить отдельный checkout этого SHA без переключения соседней рабочей ветки.
Запуск из него: `node base-modules/ui/tools/ui-reference/cli.mjs check`, затем
`search "задача"`, адресный `show` и один `example`. Node 22 достаточен;
npm install, frontend-пакет, работающие API/Storybook и доступ к стенду не нужны.
Для SSR использовать macro из карточки, штатный exporter и fingerprints;
React-пример не подменяет серверный контракт. Полный каталог не загружать;
новые возможности Base не считать принятыми без отдельного изменения UI pin.

Button, Input, Textarea, Checkbox, RadioGroup/Radio, Switch, меню, Card, Table, Disclosure,
Dialog и Toaster/toast использовать из публичного @pdlc/ui. Общий дефект
исправлять в Base; продукт сохраняет данные, права и сохранение. Прямой Sonner,
копии примитивов и продуктовые определения общих tokens не добавлять.
Брендинг применяется общим runtime; draft preview изолируется BrandingScope.
Канонический контракт — Base docs/platform/DESIGN_SYSTEM.md и docs/BRANDING.md.
UI/SDK/skills pins независимы; source-изменения не означают установку.

SSR-каркас и page-frame/page-wide/page-readable/page-split принадлежат CSS Base.
Не дублировать их геометрию в base.html и не возвращать retired local styles
старой шапки/вкладок/переключателей. Таймлайн, статус исполнения и предметная
компоновка сохраняют собственный контракт. Проверять реальные macros/assets,
а не наличие прежнего CSS-текста в шаблоне продукта.
Заголовок страницы использует base-page-title, раздел — section_header с прежним
heading_id. Native home link использует button(href=..., variant=ghost, size=icon),
ссылки действий — text_link, подтверждённая пустота — state. URL и namespace
остаются у Workflow. Не добавлять локальный skin или второй leave/history runtime.
Для частичной навигации использовать общий app_main и lifecycle Base; продукт
владеет загрузкой своего HTML и очисткой страничных обработчиков (docs/ui-shell.md).

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
