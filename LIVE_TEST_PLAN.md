# Приёмка CLI и проверки

В проекте есть два разных уровня проверки. Их нельзя называть одинаково.

## 1. Детерминированный runtime integration test

Проверяет продуктовый dataflow без реального исполнителя:

```text
CLI subprocess -> PostgreSQL -> тестовый OpenAI-compatible HTTP -> проверка -> PostgreSQL
```

`test_full_supervisor_runtime_through_cli_postgres_and_http` поднимает stdlib HTTP-сервер
с настоящими `/v1/models` и `/v1/chat/completions`, запускает CLI отдельными
процессами и проверяет:

- packaged-каталог `sdlc-business-tech-v1` из 19 фаз, включая serial- и
  parallel-группы;
- полный успешный путь без точной привязки документа к изменяемому числу
  evaluator-вызовов;
- fingerprints, audit snapshot, replay, post-done и переходы;
- subprocess CLI, PostgreSQL и HTTP-контракт без monkeypatch проверяющего LLM-клиента.

Отчёты и ответы provider в этом тесте синтетические. Он не доказывает, что агент
выполнял выданные задания, и не является полным бизнес-E2E.

```bash
pytest -q --timeout=60
pytest -q -m integration tests/test_postgres_integration.py --timeout=60
pytest --cov=project_workflow --cov-report=term --timeout=60
ruff check .
mypy project_workflow scripts
git diff --check
python -m project_workflow.interfaces.cli --help
```

Обычный `pytest` намеренно исключает marker `integration`, поэтому PostgreSQL-тесты
показываются как `deselected` и обязательно запускаются второй командой.
Два составных subprocess E2E имеют локальный marker `timeout(120)`; остальные
integration-тесты сохраняют общий 60-секундный предел.

## 1.1 Browser Auth Acceptance

Проверка Central Auth не заменяет standalone gate и выполняется только при
изменении SSO boundary или deployment env. Для общего локального стенда поднять
Central Auth с client `project-workflow` и redirect URI
`http://localhost:8812/sso/callback` командой из корня workspace:

```powershell
pwsh -File services-base/deploy/start-workspace.ps1
```

Версионируемый `services-base/deploy/project-workflow.local.override.yml`
подключает API к сети `sdlc-ux_platform` и задаёт
`AUTH_INTERNAL_BASE_URL=http://auth:7701`. Перед browser E2E проверить
`http://auth:7701/health` из контейнера API; публичный `AUTH_ISSUER` остаётся
`http://localhost:7701`. Для отдельного Compose с Auth на хосте
`host.docker.internal:7701` допустим только после такого же preflight из
контейнера: если адрес недоступен, callback завершится `503` и этот режим
нельзя считать проверенным.

Из корня workspace preflight для общего стенда:

```powershell
docker compose --env-file .local/local.env --project-directory project-workflow -p project-workflow-local -f project-workflow/docker-compose.yml -f services-base/deploy/project-workflow.local.override.yml exec -T api python -c "import urllib.request; urllib.request.urlopen('http://auth:7701/health', timeout=3)"
```

E2E evidence обязано подтвердить: anonymous `/` редиректит на `/login`, login
в Central Auth возвращает на исходную страницу, cookie-сессия открывает UI,
anonymous `/api/*` получает `401`, а `/logout` очищает сессию. Для HTTPS
установить `AUTH_COOKIE_SECURE=true`. Standalone `/health` + browser smoke
повторить в отдельном Compose-проекте без интеграционного override и без
`AUTH_ISSUER`; не переиспользовать для этого рабочие контейнеры и volumes.
No-auth режим не должен требовать Central Auth.

## 2. Executor-driven business E2E

Проверяет полный цикл с реальными действиями внешнего исполнителя:

```text
Проверяющий модуль выдал задание
-> исполнитель выполнил команды
-> recorder сохранил команды и результаты
-> исполнитель отправил отчёт со ссылками на ACTION
-> реальный внешний OpenAI-compatible provider оценил отчёт
-> проверяющий модуль сохранил audit и выдал следующий шаг
```

Проверяющий модуль остаётся evaluator и маршрутизатором. Recorder не исполняет фазы за него,
не меняет БД напрямую и не добавляет продуктовых CLI-команд.

### Артефакты

Каждый запуск хранится только локально в ignored-каталоге:

```text
.artifacts/live-e2e/<task>/<timestamp>/
├── transcript.jsonl
├── dialog.md
├── summary.json
└── command-logs/
```

Для каждого обращения к evaluator последовательность обязана содержать:

1. `ASSIGNMENT` — точные `phase_contract` и prompt, полученные от wrapper-команды с `--json step`;
2. один или несколько `ACTION` — рабочая директория, команда, exit code и безопасный результат;
3. `REPORT` — точный текст отчёта и `Evidence-Refs` текущих ACTION;
4. `EVALUATOR` — полный JSON-ответ evaluator;
5. `TRANSITION` — фактическая исходная и следующая фаза.

Для parallel-фаз сохраняется один общий assignment и отдельные ACTION по каждому
участнику. Отчёт без ACTION, ссылка на действие старой/чужой фазы и незавершённая
последовательность отклоняются до отправки evaluator.

`ACTION` считается доказательством только в формате, который создаёт команда
`action`: непустой список аргументов команды, абсолютный `cwd`, числовой exit code,
`output_excerpt` и точная ссылка `command-logs/A-xxx.log`. При `finalize` recorder
проверяет наличие каждого такого лога и совпадение его начала с `output_excerpt`.
Ручное добавление упрощённых ACTION в JSONL не является допустимым bootstrap-путём.

### Запуск recorder

Перед запуском явно настройте локальный `DATABASE_URL` и OpenAI-compatible provider.
DSN обязан указывать на `localhost`/`127.0.0.1`, а не на Relevanter Dev.

```bash
python scripts/live_e2e_recorder.py --root <session-dir> --task TASK-123 init --metadata '{"head":"<sha>"}'
python scripts/live_e2e_recorder.py --root <session-dir> --task TASK-123 assignment
python scripts/live_e2e_recorder.py --root <session-dir> --task TASK-123 action \
  --phase -1 --summary "Проверен контекст" --cwd . -- git status --short
python scripts/live_e2e_recorder.py --root <session-dir> --task TASK-123 submit \
  --phase -1 --report-file <report.md>
python scripts/live_e2e_recorder.py --root <session-dir> --task TASK-123 finalize \
  --expected-cycles <actual-cycle-count>
```

В отчёте обязательна отдельная строка, например `Evidence-Refs: A-001, A-002`.
Recorder выполняет redaction ключей, DSN-паролей, e-mail и пользовательской части
Windows-пути до записи командных логов.

### Правила честного прогона

- Нельзя использовать старые записи `task_step_history`, прежние отчёты, шаблоны PASS или
  заранее подготовленные ответы provider.
- Нельзя вручную дописывать `ACTION` в transcript или подменять соответствующий
  файл в `command-logs`. `finalize` выявляет упрощённые и несогласованные правки;
  криптографическая защита локальных файлов от намеренной синхронной подмены не
  входит в задачу recorder.
- Отчёт формируется только после фактических ACTION текущего assignment.
- Рекомендованные skills загружаются исполнителем из зафиксированного SHA
  `relevanter/agent-skills`; Supervisor передаёт только их имена.
- Каждая фаза содержит `delegate_agent`, профиль запуска и `skills`; parallel
  assignment дополнительно содержит `group_phases` и отдельные `group_details`.
- Executor запускает выбранный профиль штатным внешним entrypoint. Проверяющий
  модуль не подменяет профиль и не читает его содержимое.
- Фаза `9.PR` создаёт Pull Request. Фаза `12.RELEASE_GATE` останавливает прогон
  перед merge; merge выполняет Maintainer. Фаза `13.DELIVERY` проверяет merged
  SHA и результат сборки.
- Любой `PARTIAL`, `BLOCKED`, provider error или неверный переход останавливает
  продвижение. Замечание исправляется новым действием и новым отчётом; audit не
  переписывается и принудительный переход запрещён.
- Если evaluator вернул реальный `PARTIAL/BLOCKED`, дополнительные циклы
  сохраняются в transcript и audit, а не маскируются корректировкой ожидаемого
  результата.
- Реальная смена состояния (`open` -> `merged`) допустима в отчёте только с явной
  хронологией, временными метками и action evidence.
- После завершения сверяются задача `status=done`, её фактическая конечная фаза,
  `task_phase_events`, все записи `task_step_history`, fingerprints, prompt version,
  raw evaluator, replay и post-done.
- Успешную основную задачу и её audit оставляют в локальной PostgreSQL. Временную
  negative-probe задачу удаляют точечно после сохранения обезличенного лога.

Канонический live-прогон выполняется в изолированном окружении CLI runtime
с настроенным provider и тестовыми ресурсами Relevanter Business/Tech. Product
containers Relevanter этим прогоном не изменяются.
