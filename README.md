# project-workflow

Внутренняя loopback/private утилита для пофазного ведения задач. Агент
отчитывается через CLI, обязательный LLM Supervisor оценивает отчёт и переводит
задачу по workflow. Runtime-источник данных - PostgreSQL.

## Что умеет

- Вести задачу по шаблону фаз с инструкциями, checks, evidence и audit history.
- Запускать несколько неймспейсов параллельно: у каждого свои workflow, задачи,
  стиль UI, префиксы ключей и CLI-команда.
- Держать append-only историю фаз и `step`-проверок.
- Управлять workflow, фазами, неймспейсами, агентами и задачами через Web UI.
- Оставлять базовый CLI минимальным: только `step` и `history`.

## Быстрый запуск

```bash
cp .env.example .env
docker compose up --build -d --wait
curl --fail http://127.0.0.1:8812/health
```

UI доступен на `http://127.0.0.1:8812`.

Compose публикует PostgreSQL и API только на `127.0.0.1`. Перед запуском новой
baseline-схемы старый dev volume нужно пересоздать по
[docs/database-reset.md](docs/database-reset.md).

## Неймспейсы

Неймспейс - это отдельная рабочая среда. Он хранит:

- название и описание;
- привязанный workflow;
- иконку и цвет темы UI;
- префиксы задач;
- пользовательскую CLI-команду.

Верхний selector UI полностью переключает рабочую среду: logo/name, accent
color, dashboard, список задач, detail страниц и `/phases`. Выбор хранится в
cookie `workflow_namespace_id`; `?namespace_id=` имеет приоритет над cookie.

Канонический API: `/api/namespaces`. Старые alias routes оставлены только для
совместимости.

## CLI

Базовый CLI не расширяется:

```bash
project-workflow step --task RUN-123 --report "Сделал X, проверил Y"
project-workflow history --task RUN-123 --n 10
```

Для удобной работы с несколькими неймспейсами создаются wrapper-команды:

```bash
python scripts/install_namespace_clis.py --bin-dir ./.bin
```

Скрипт читает неймспейсы из PostgreSQL, создаёт команды из `cli_command`,
выставляет внутренний `PROJECT_WORKFLOW_NAMESPACE_ID=<id>` и вызывает
`project-workflow step/history`.

Пример пользовательского вызова:

```bash
workflow-qa step --task RUN-42 --report "Проверил сценарии"
workflow-dev history --task RUN-42
```

Так одна внешняя задача может существовать в нескольких неймспейсах независимо,
а executor получает в `phase_contract.cli_actor.entrypoint` именно configured
CLI-команду нужной рабочей среды.

## Разработка

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --constraint constraints.txt -e ".[dev,ui]"
```

`constraints.txt` фиксирует проверяемый набор зависимостей. Docker-сборка
использует тот же файл.

## Документы

- [docs/architecture.md](docs/architecture.md) - границы CLI/UI/Supervisor,
  state/audit model, replay/fingerprint и runtime scope.
- [docs/quality-gate.md](docs/quality-gate.md) - локальный gate, PostgreSQL
  integration, ResourceWarning, Compose readiness и browser smoke.
- [LIVE_TEST_PLAN.md](LIVE_TEST_PLAN.md) - executor-driven E2E acceptance.

## Проверки

```bash
make quality
make warnings
make compose-ready
```

На Windows без `make`:

```powershell
pwsh -File scripts/quality.ps1 quality
pwsh -File scripts/quality.ps1 warnings
pwsh -File scripts/quality.ps1 compose-ready
```

## Лицензия

MIT
