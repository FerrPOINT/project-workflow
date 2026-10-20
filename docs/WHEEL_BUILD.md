# Раздельные wheel-слои Workflow

Общие правила задаёт [стандарт Base](https://github.com/FerrPOINT/services-base/blob/a36cd64f04f483f675bb3b991d9871c7be27bff0/docs/BUILD_PERFORMANCE.md).
В source workspace использовать его из принятого `qualityTooling.path` в
`source-workspace.json`; независимые SDK/UI/skills/operator pins не менять.

Это source-кандидат поверх закреплённых UI/crypto runtime dependencies.
Он сохраняет продуктовый код, AI Hub dialect, существующий image caller и
catalog variants. Native installer/image parity, cache hits, время и CPU/RAM
этой версии ещё не квалифицированы. Изменение Dockerfile не обновляет runtime.

## Входы и стадии

`dependency-wheels.json` содержит проверенный metadata graph для
`cpython-311-bookworm-amd64`: 37 runtime/UI wheels и 6 build wheels.
Версии принадлежат `constraints.txt`; helper проверяет selected pins, roots,
backend, dependency edges и digest всего reviewed contract. Он выпускает
раздельные requirement files с exact wheel hashes, не вызывая resolver.
Изменение dev-only pin не меняет runtime/build install inputs. Изменение
selected pin, root или backend требует нового metadata proof и review.

`runtime-dependencies` устанавливает runtime wheels в `/opt/venv`.
`build-tools` отдельно готовит Hatchling в `/opt/build-venv`; `wheel-inputs`
содержит pyproject, README, LICENSE и весь `project_workflow/`, включая миграции.
Текущий backend использует default package selection без hooks/dynamic metadata;
изменение этих правил требует новой квалификации входов.

`application-inputs` добавляет scripts, alembic и полные constraints.
`verified-inputs` проверяет immutable manifest до wheel producer и передаёт
ему bind witness. `builder` выпускает wheel без повторной установки backend.
`installed` получает этот wheel и runtime venv, выполняет pip check и удаляет
pip/setuptools/wheel. Поздний `runtime-inputs` добавляет проверенный `/app` и
выполняет installed compatibility. Финальный образ сохраняет прежние шесть
runtime payload paths, source/archive/bundle labels и catalog variant.
Build venv в него не копируется. Venv нельзя накладывать на неочищенный parent:
directory merge восстановит удалённые tools.

Другие архитектуры явно сохраняют полный constraints и прежнюю подготовку
native build dependencies. Это поддерживаемый legacy путь, а не qualified
fast path. Повреждённый contract отклоняется до установки. Общие cache IDs и
RUN mutex сохраняют согласование с Base; ресурсный caller квалифицируется отдельно.

## Точечная source-проверка

В существующем совместимом Python 3.11+ окружении с pytest, из корня продукта:

```bash
python -B -m pytest --noconftest -o addopts= -m unit tests/test_dependency_locks.py tests/test_dependency_stages.py -q
```

Это только pure source tests: `--noconftest` исключает legacy DB autouse fixtures
для этих двух файлов. На DB, integration или release suite этот обход не переносить.
Прежний Docker/venv shape guard перенесён из смешанного runtime cleanup suite
в pure lock/stage guards. Compatibility test ссылается на новую финальную стадию;
его предметное поведение сохраняется.

Остаются отдельные gates: физическое разделение unit/manual fixtures и lanes,
Make/CI/PowerShell routing, общий resource admission/caller и prepared contexts,
native wheel/installed inventory, warmed cache invalidation и отказ на неверном
manifest/compatibility, измерения и exact adoption. Старые команды этого checkout
ещё не реализуют новый unit/manual процесс. Полный coverage baseline 94%,
PostgreSQL, security/data/compatibility/live acceptance сохраняются и не объявляются
пройденными по результату этих source tests.
