# Аудит состава упрощения Workflow

Статус: исходники в работе; общий PostgreSQL/CLI/Hermes gate и merge не завершены.
Этот документ фиксирует проверенный срез исходников, а не актуальность установленного
приложения. Контракт: [Configured CLI V1](../configured-cli-v1.md).

## Срез веток

| Репозиторий / PR | Проверенная голова PR при начале переноса |
| --- | --- |
| Base #341 | `eb72ba652f0d16c97933bb7c4ca590b5ff920002` |
| Workflow #148 | `81a471220eb5f8e9e929a18db2daf43f525d0c7b` |
| Tracker #188 | `da82a16a8545fcc2a86df27e9570e0e5823271f2` |
| Fleet #137 | `93b4c163151041d1b7b07448e017d4d63d5c101e` |

Перед публикацией/merge головы и обязательные проверки необходимо обновить.
Работа над производительностью в исходных checkout не изменяется этим переносом.

## Локальные коммиты Workflow

Между головой #148 и сохранённым `ade94c6b59dad2c6fba1557b7e41a5f76cab6624`
найдено **42**, а не 30 коммитов. Проверены их списки файлов и совокупный runtime diff.
Только два runtime-модуля затронуты этим диапазоном:

- `infrastructure/base_package.py`: изоляция Git environment при чтении закреплённого
  пакета, без изменения фазы, назначения, оценки или истории.
- `interfaces/ui/__init__.py`: отложенный импорт UI с сохранением экспортов,
  без изменения бизнес-правил Workflow.

Остальной диапазон меняет сборку, locks/wheels, quality/test selection, изоляцию
фикстур и документацию. Он не содержит недостающей реализации общего CLI.
В функциональную ветку этот диапазон не перенесён. Полезные изменения сохранены
в исходной ветке; их build/performance публикация отделяется от этого PR.
Если выбранный кандидат потребует конкретного нового producer/helper, такой SHA
становится отдельной явной зависимостью и входит в его квалификацию. SDK/UI/skills
pins не повышаются ради чтения новых инструкций сборки.

| Commit | Изменение | Файлов |
| --- | --- | --- |
| `16abec8810` | perf: reuse Python environments and run coverage once | 15 |
| `e516955324` | perf: reuse Python environments and run coverage once | 3 |
| `1f1edc2122` | perf: reuse Python environments and run coverage once | 1 |
| `63c8a85c79` | perf: clone isolated SQLite fixture from session-owned snapshot | 3 |
| `ce39c791ad` | perf: reuse Python environments and run coverage once | 1 |
| `0941992740` | docs: pin qualified Base build performance standard | 2 |
| `90f8012c5d` | perf: run coverage once with two bounded isolated pytest workers | 9 |
| `da21ec1019` | perf: reuse Python environments and run coverage once | 2 |
| `dde6ad785b` | docs: pin qualified Base build performance standard | 2 |
| `e3dc63e1b3` | test: separate automatic unit checks from manual release gates | 18 |
| `29dd4365eb` | test: enforce manual release workflows with exact Base policy | 7 |
| `2f4bd96acc` | perf: collect only reviewed unit test files by default | 3 |
| `353b0a2277` | perf: prepare quality environment once per operation | 4 |
| `f1ba4375e1` | docs: pin the qualified Base build performance standard | 2 |
| `656db2ba7c` | docs: align CI instructions with manual release profile | 1 |
| `a95cc1d480` | build: isolate Workflow runtime dependency inputs and retain pip downloads | 6 |
| `0b0bf421a9` | build: verify Workflow provenance independently of package installation | 2 |
| `9d87686e82` | Serialize Docker RUN stages with the qualified shared build profile | 4 |
| `3950df8efd` | docs(build): require scoped artifact reuse before rebuilding | 1 |
| `5d5b1f7e56` | perf(ci): run Workflow quality tests once and keep docs lightweight | 4 |
| `41d260811a` | perf(tests): defer Workflow integration fixtures until requested | 4 |
| `fce5b583ef` | perf(ui): defer Workflow app graph while preserving legacy exports | 4 |
| `b80103c264` | docs: distinguish PDLC production from Firebat2 development | 1 |
| `384aa4ce9c` | perf(build): isolate Workflow wheel inputs from runtime tooling | 5 |
| `e7edf8fd0b` | perf: bind navigation unit receipts to closed inputs and Node context | 5 |
| `e2a8aeba7b` | fix(build): pin Workflow UI runtime dependency closure | 2 |
| `f880eb5c55` | perf(build): lock runtime wheels and isolate reusable wheel production | 10 |
| `5a3464a274` | fix(build): preserve bytecode-free provenance verification | 2 |
| `ad3369e8a7` | perf(tests): adopt reviewed Workflow unit collection in PDLC1 | 7 |
| `4cba9b47b8` | perf(tests): select Workflow Python and Node checks independently | 3 |
| `a9626da3a5` | perf(quality): use one frozen Workflow dependency environment | 6 |
| `ec8eb5d5d8` | perf(tests): keep Workflow subprocess controls in manual integration | 3 |
| `2ee6a464c9` | fix(quality): adopt Base prerequisite ordering in standalone selector | 5 |
| `3940ba08c5` | build: opt in to one locked UI producer environment | 3 |
| `318f42b03d` | build: use core dependencies for the host image producer | 4 |
| `100f4966e7` | perf(build): reuse explicitly approved frozen Workflow contexts | 6 |
| `49cdb415ef` | test(build): distinguish frozen contexts from ambient Git archive policy | 1 |
| `f54eb9d394` | fix(build): preserve Windows prepared context file bookends | 3 |
| `a755d8b869` | perf(build): expose frozen stdin plan for the Base lifecycle owner | 4 |
| `9bf9c2fe06` | docs(build): separate attestation index from the original runtime artifact | 1 |
| `1e75937209` | fix(build): bind immutable source export to exact Base helper | 11 |
| `ade94c6b59` | feat(build): expose metadata-only default producer request | 6 |

## Что переносится из stage-work-contract

Переносится поведение, а не старый транспорт: оценка независимого Review/Testing
с допустимым бизнес-результатом rework; полное постраничное обсуждение; существующий
итоговый комментарий до передачи; отказ после его изменения/удаления. Инструкции
всех профессий используют один CLI и не требуют собственного будущего receipt.

Не переносятся native bind/checkpoint/rebind, файлы execution request/token,
обходы локальной БД и отдельная PM-реализация исполнения. Исторические SQL-файлы
и опубликованные receipts сохраняются. Новое поведение данных — forward migrations.

## Удаления и замены по владельцам

| Владелец | Удаляется | Сохраняется / заменяет |
| --- | --- | --- |
| Workflow | агентные file flags, DB fallback, runtime-only слой PM-инструкций | общий Base HTTP client, API-only step/history, один канонический каталог всех8 режимов |
| Workflow | исполняющие native bind/checkpoint/retry ветки после переноса потребителей | immutable history, current phase, assignment/version/idempotency и post-model recheck |
| Tracker | перенос native/checkpoint-файлов в агентных бизнес-командах | постоянная identity, текущее назначение и project ACL; server-to-server Workflow result; атомарный handoff |
| Tracker | ограничение «один PM completion на бизнес-задачу» | один immutable completion на execution; original-key history с исходной редакцией/назначением |
| Fleet | delivery wire/CLI refresh, Developer Git request API и capability issuance, Forge/Git/CI/DevOps private generators и renewal files | обычная доставка, permanent config, actual native terminal и current Tracker CAS |
| Fleet | technical runtime-token map и старый Workflow effect transport | один server assignment-reader map, общий Workflow API |
| Fleet | private execution-token/first-step authority для technical history | key из сохранённого назначения; frozen scope и общий role/namespace history read |
| Fleet | dead Forge/Git request parent configuration | настоящий серверный Forge readback credential и namespace reader, оба с redaction |
| Base | параллельный CLI HTTP transport и устаревшие инструкции профессий | общий bounded client; точный CLI cohort; канонические роли и skills |

Удалённые файлы генераторов не заменяются новыми генераторами или второй копией
инструкций в сообщении. Optional чтение старых секретов нужно только для redaction
истории и не создаёт credentials или права исполнения.

## Границы PR и обязательные зависимости

Base #341 в проверенном срезе содержит78 изменённых файлов, включая большой operator/
installation блок и независимый Auth CORS. Сравнение выполнено с Base main `6f32eb88e0a9fbc5b52ece7506a2744cf9db88f7`.
Этот состав нельзя объявлять единым
исправлением Workflow. Разделяются:

- CLI client, canonical skills и точные producer/cohort pins — общий контракт Workflow.
- Operator/runtime/data-preservation доработки — отдельный build/operator PR, если
  выбранная установка действительно требует эти изменения.
- `base-auth/src/application_access.rs`, `base-auth/src/routes.rs` и соответствующие
  тесты — независимый Auth CORS PR; не основание обновлять Auth/common при установке
  этого кандидата.

CLI pins обновляются после фиксации продуктовых SHA. Tracker и Fleet продолжают
потреблять SDK `ed61ec63b58fe9b60d8669c85de5ac6b5bec872b`, пока конкретное изменение
SDK не станет подтверждённой зависимостью. Python Workflow CLI отдельно нуждается
в Base CLI source с новым HTTP client; его SDK/UI pin не заменяет этот producer pin.
Forge CLI source и совместимость его Base layout квалифицируются отдельно.

## Незакрытые этапы

- Квалификация общего critical PM business review: source использует выбранный
  context, обычное системное сообщение и forward108; PostgreSQL/живой проход и
  удаление прежних активных adapters ещё не закрыты. Analyst не запускается.
- Явный переход существующих задач после quiescence. Ключ каждой профессии
  сверяется с настоящим сохранённым Workflow cursor; новый ordinal не может
  сбросить существующую фазу созданием второй задачи.
- Удаление оставшихся активных PM writers и чтение старой истории после restart.
- Rust/PostgreSQL fresh/filled, OpenAPI/generated clients и packaged CLI qualification.
- Отдельный ручной PDLC1 Hermes прогон всех профессий/Rework с независимым оракулом.
  [Сценарий и оракул](../../manual/configured-workflow-proof/README.md) подготовлены
  вне обычной suite; наличие сценария не доказывает выполнение.
- Чистые PR, точный кандидат, data-preserving установка, merge в согласованном
  порядке и проверка итоговых обслуживаемых ресурсов.
