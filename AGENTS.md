# AGENTS.md

## Правила репозитория

1. После завершения задачи нельзя оставлять готовую работу в незакоммиченном состоянии.
   - Сначала прогнать релевантные проверки.
   - Для UI-изменений обязательно сделать браузерную проверку и скриншот.
   - Затем сразу сделать git commit по выполненной задаче.

2. Не считать задачу завершённой, если рабочее дерево осталось dirty по её изменениям.

3. Merge и deploy запрещены без явной команды пользователя.

## Обязательные проверки

Политика и команды: [TESTING](docs/TESTING.md), [quality gate](docs/quality-gate.md).
Обычная сборка/разработка: `python scripts/quality.py quality` — unit + lint/types.
Scoped unit: `python scripts/quality.py test -- <unit-test-path>`.
Integration/slow/full coverage и PostgreSQL запускаются вручную при подготовке
релиза через `python scripts/quality.py release` либо release.yml на exact ref.
Coverage baseline 94%, data/security/live gates сохранены. Невыполненная
релизная проверка остаётся NOT RUN; не запускать её автоматически после правки.
Compose/browser acceptance выполняется отдельно для затронутого релиза
на разрешённом тестовом target, без изменения принятого runtime.

## Примечания

- Для ручного полного release gate использовать `python scripts/quality.py release`;
  scoped проверки — `python scripts/quality.py test -- <test-path>`.
  `--forked` не требуется; при нём отчёт coverage некорректен.
- `DATABASE_URL` обязателен в runtime. SQLite используется только в изолированных тестах.
- `project-workflow` хранит имена skills. Действующий legacy-каталог сохраняет
  свой source; отдельный [Base candidate](docs/base-sdlc-candidate.md) закрепляет
  commit пакета `services-base/agent-skills`. Candidate не установлен: не менять
  default path, bootstrap, migrations и pinned history при подготовке документов.
- Профессия хранит только `launch_profile` как настройку выполнения. Её
  идентификатор — существующий `code`; роль задачи задаётся назначением и режимом.
  Фазы не назначают отдельных агентов. Профилем запуска
  владеет внешний исполнитель; несколько профессий могут использовать один профиль.
- Воспроизводимый CLI acceptance описан в `LIVE_TEST_PLAN.md`.

## Осознанно исключённые возможности

Это внутренняя лёгкая агентская утилита, а не клиентский production-сервис.
Следующие возможности оценены и исключены из текущего scope:

| Возможность | Решение | Причина |
|---|---|---|
| CI/CD pipeline (GitHub) | **Использовать** | Автоматически unit + lint/types затронутых компонентов; coverage, PostgreSQL integration и Compose smoke — отдельный ручной release gate на exact ref. |
| Security middleware (CORS, CSP, HTTPS redirect, rate limits) | **Не добавлять** | UI доступен только на loopback либо в защищённом private/VPN-контуре. |
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
Для UI: CLI `pdlc-ui` из закреплённого UI-пакета Base, затем карточка и один пример. SSR-ресурсы получать штатным exporter Base; fingerprint проверять отдельно.
Не переносите продуктовые запросы, DTO и права в общий UI. SDK/UI/skills pins независимы; новое имя платформы не меняет SDLC IDs/scopes или закреплённые внешние runtime-источники.

## Быстрые проверки и сборка

Перед тестами, build и CI читать обязательный [стандарт Base](https://github.com/FerrPOINT/services-base/blob/197ead9d9b6cf6901e8f9dd31f43f719885502c3/docs/BUILD_PERFORMANCE.md).
При разработке и сборке unit/static. Integration/slow/full coverage —
ручной gate при подготовке релиза по docs/TESTING.md.
Сохранять полезный cache, не переустанавливать неизменные dependencies и не
пересобирать приложение из-за test-only. До повторного тяжёлого запуска назвать
изменившиеся inputs/недостающее evidence; передавать один artifact между этапами.
Required security/data/compatibility/live checks и product toolchains сохраняются.
Компоненты и команды: `.quality-gate.json`; общие правила не копировать.

Уровни и команды: [TESTING](docs/TESTING.md). Полный `.github/workflows/release.yml`
запускается вручную на exact ref; зелёный unit build не означает release acceptance.

## Выбор сборки и повторное использование

Перед build/test/install определить нужные компоненты и изменившиеся реальные
inputs; проверить готовый artifact, environment и cache. Неизменные inputs и
проверенный artifact означают отсутствие повторных install/compile/source export.
Docs/test-only не пересобирают приложение без изменения его build inputs.
Во время работы выполнять scoped unit/static; полный gate — на согласованной
вехе. Integration/slow/full coverage — вручную перед релизом; необходимые
security/data/compatibility/live gates сохраняются. Полные команды в этом
документе — каталог проверок, а не требование выполнять всё после каждой правки.
Перед повторным heavy назвать changed inputs или missing proof; REUSED не
выдавать за новый тест. Полезный прогретый cache сохранять в его бюджете.
В source workspace читать `docs/BUILD_PERFORMANCE.md` из `qualityTooling.path`
в `../source-workspace.json` и правила workspace в `../AGENTS.md`.
В standalone checkout использовать стандарт принятой версии Base.
