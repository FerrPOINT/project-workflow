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
отдельно. Full non-PG/coverage, protected installation, CLI packaging
и seven-role deployment acceptance остаются отдельными незавершёнными gates.

## Отдельно Собранный Кандидат

Штатный Base Build собрал backend из immutable Git snapshot
`8d8dfe995f78999b53318f49ffb52e6873155c44`. Это docs-only successor проверенного
`dfb5682`; новый catalog и requirements hashes не изменились. Runtime provenance
probe подтвердил revision, source archive и runtime bundle образа:

```text
image:          sha256:47455ca3e40bf5aedb4120b080459a1313a7bc87f3017ec11b5d5f6463662fc6
source archive: 10ce42f83e36263c66177d4743a6946755e98bb1aa3b9c173b02fbcfd799fb68
runtime bundle: 53e52bb6a6d4ff5c6167d16835618b8b8ee2066f67045bc8d80697682cc510e9
build receipt:  12a3e11d44e8bd9c7d2fc5f81a9ca6da26137a3d806cab89bc13f97564f2eebe
```

`workflow_build.status=passed`, profile `base-v3`; `complete=false` относится
к неполной сборке всего workspace, а не к отказу этого единственного сервиса.
Временный provenance project удалён; отдельный Docker readback не обнаружил
его контейнеров или volumes. Образ не установлен: accepted runtime, база,
secrets и legacy catalog не менялись. Build/provenance не заменяют full test
gate, установку single-task семьи или live SDLC acceptance.

Установка описана в [single-task-installation](single-task-installation.md).
Исходное состояние стенда остаётся [legacy predecessor](workflow-installed-predecessor-20261016.md).
