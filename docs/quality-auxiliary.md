# Подготовка окружения и HTML coverage

Make и PowerShell используют тот же `scripts/quality.py`, что и основные проверки.

| Команда | Работа |
| --- | --- |
| `python scripts/quality.py install-dev` | Подготовить frozen quality environment Python 3.11.15 с all-extras; без pytest, lint и сборки приложения |
| `python scripts/quality.py coverage-html` | Построить HTML из существующего coverage data; без pytest, sync окружения и скачивания Python |
| `python scripts/quality.py --html-report coverage` | Явный ручной non-PostgreSQL pytest: term, XML и HTML за один прогон |
| `python scripts/quality.py --html-report release` | Тот же единый coverage с HTML, затем PostgreSQL, lint/types и diff check |

Make: `make install-dev`, `make coverage-html`. PowerShell:
`./scripts/quality.ps1 -Target install-dev` или `-Target coverage-html`.
Подготовка использует существующий `WORKFLOW_QUALITY_ENVIRONMENT` либо
`.local/quality-python/<OS>/3.11.15`; не устанавливает пакеты в Python оболочки.
`uv.lock`, constraints и extras прежние. Совместимое окружение остаётся прогретым.

`coverage-html` требует готового окружения и сохранённых данных (по умолчанию
`.coverage`; стандартный `COVERAGE_FILE` сохраняется). Отсутствие инструмента или
данных возвращает ошибку; coverage ниже 94% возвращает отказ. Команда не запускает
тесты или install для восстановления. Перед новым test/build по-прежнему
проверяются frozen inputs. Custom `WORKFLOW_QUALITY_UV` остаётся явным override:
автоматически добавлять uv-specific flags к чужой команде нельзя.

Объединение целей Make переиспользует существующего report owner. Порядок
`make release coverage-html` или `make coverage-html release` выбирает один
release с HTML. `make coverage coverage-html` выбирает один coverage с HTML.
`--html-report` разрешён только перед target `coverage` или `release`.
PostgreSQL, исходные failure codes, strict warnings и два coverage workers сохранены.

HTML показывает сохранённые данные и не подтверждает новый commit или готовность
релиза. Integration/slow/release остаются отдельной ручной вехой. Текущий GNU Make
protocol fixture — `tests/test_quality_make_dispatch.py` (integration); он
исполняет временный recorder, а не приложение. Повторная native qualification
изменённого Make маршрута остаётся на согласованной финальной вехе.
