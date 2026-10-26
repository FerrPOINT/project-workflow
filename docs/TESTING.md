# Уровни проверок Workflow

Общий стандарт: [Base BUILD_PERFORMANCE](https://github.com/FerrPOINT/services-base/blob/7e113c5e7eb6af0d4a3b55fc0e9f40e8f84392b8/docs/BUILD_PERFORMANCE.md)
и [Base TESTING](https://github.com/FerrPOINT/services-base/blob/7e113c5e7eb6af0d4a3b55fc0e9f40e8f84392b8/docs/TESTING.md).
Продуктовые команды и выбор компонентов принадлежат `.quality-gate.json`.
SDK/UI/skills и независимый quality selector имеют отдельные pins.

## Повседневная работа

Из корня продукта:

```bash
python scripts/quality.py unit
python scripts/quality.py unit -- tests/test_phase_graph.py
python scripts/quality.py quality
```

`quality` выполняет один unit-прогон, Ruff, mypy и `git diff --check`.
Make и PowerShell делегируют этому же runner. Frozen Python 3.11.15 environment
готовится одним вызовом uv на операцию; инструменты затем используют этот
interpreter без повторной установки. Совпадение `constraints.txt` и `uv.lock`
проверяется до подготовки. Кэш uv и совместимое окружение сохраняются.

`tests/lanes.json` содержит явный reviewed список unit-файлов. Он передаётся
pytest до collection; маркер сам по себе не оправдывает импорт всего набора.
Flags-only scoped вызов сохраняет этот список через `testpaths`, а явные paths
и node IDs разбирает pytest. Пустой или неверный список приводит к ошибке.

Unit fixture не импортирует и не создаёт SQLite/UI runtime. У нынешнего checkout
`test_schema.py` и UI schema imports входят в integration: прежний `unit` marker
не делает database/bootstrap или eager UI import чистым unit. Эти проверки
сохраняются в ручном наборе. Новые неизвестные файлы по умолчанию — integration;
для включения в unit нужен review их реальных зависимостей.

## Ручная веха

```bash
python scripts/quality.py integration
python scripts/quality.py slow
python scripts/quality.py test-integration
python scripts/quality.py release
```

`release` выполняет один полный non-PostgreSQL pytest с coverage не ниже 94%,
строгими warnings, XML и двумя workers; затем отдельный последовательный
PostgreSQL набор и static checks. Порог покрытия и существующие assertions
не меняются. В рамках этой операции полный pytest ради coverage не повторяется.
PostgreSQL требует изолированной тестовой БД и прежних `PG*` настроек.

Automatic CI использует Base selector и запускает только затронутый Python
или navigation lane. Docs-only проходит stdlib README validator без uv.
SDK namespace compatibility gate сохранён в backend lane. Полный coverage,
PostgreSQL и disposable Compose находятся в ручном `release.yml`.
Source/unit PASS не означает, что release, Compose, browser или live acceptance
выполнены. Для UI остаётся отдельная приёмка по `docs/quality-gate.md`.

## Повторное использование

Окружение и dependency cache сохраняются между операциями; runtime приложения
из-за test/docs изменения не пересобирается. Root `-Repository project-workflow`
использует manifest текущего checkout. Python и navigation unit runners пока выполняют
свежие тесты: сам факт наличия frozen environment не сертифицирует test receipt.
Перенос selector или runner не разрешает смену SDK/UI/skills/operator pins.
