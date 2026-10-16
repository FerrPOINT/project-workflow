# Текущая Single-Task Семья: PostgreSQL

16 октября 2026 выполнен реальный локальный PostgreSQL-тест исходника
`dfb5682dc9b6fd2ae443be621e108f7fd884d9bd`, tree
`7ff81e9498ae0b47c3399300cc98667c98400d8a`.

Selector:
`tests/test_postgres_integration.py::test_current_single_task_family_preserves_legacy_rows_and_history_on_postgres`.
Результат: **1 passed, 0 failed/errors/skipped**, 10.14 секунды.
Существующее AnyIO deprecation warning не является новым отказом.

Тест выполняет настоящие миграции и side-by-side installation. Он проверяет
сохранение legacy rows/history, actual hashes из generator, уникальные семь
namespace/workflow bindings, восемь modes, 24 phases, идемпотентный повтор
установки и persisted readback в новой транзакции.

Текущие UTF-8/LF hashes:

```text
catalog:  86e6c983b7aa6a2c99da11d1d4b1f1b4563ff913262236903a19bc86bdec2d67
manifest: 652a38c0f7bdb48a569aa3fcd5c2e81e153db6e22b5201cfb6ce15c988dd57f3
```

Python3.11.16/uv0.10.10 готовят frozen environment. Dependency proxy остановлен
и удалён перед тестом. PostgreSQL не публикует host port. Base ComposeHelper v2
подтвердил finally cleanup; собственных контейнеров и volumes не осталось.
Accepted database, runtime, credentials и каталоги не изменялись.

SHA256 result.json:
`92bdc1a9d02906e265a623da9da7d4e189734a3c7ce7068c03cc6ed08e2eb942`.
SHA256 JUnit:
`40a2af45d692800aba2248b55441707e29949d45d6c76aa37168bd95e4585609`.

Это не новый полный96-PG gate и не live acceptance. Исторические96 результатов
сохраняют свою версию исходника. Focused133 и producer31 проверки учитываются
отдельно. Full non-PG/coverage, новый image, protected installation, CLI packaging
и seven-role deployment acceptance остаются отдельными незавершёнными gates.

Установка описана в [single-task-installation](single-task-installation.md).
Исходное состояние стенда остаётся [legacy predecessor](workflow-installed-predecessor-20261016.md).
