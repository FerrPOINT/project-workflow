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


## Additional Incoming Instruction Fix

Workflow commit `7d0576d` makes questions, alternatives and preparation evidence
conditional on actual gaps. The current canonical catalog already contains this
behavior. Keep it in `single_task_delivery_instructions.py`, covered by
`test_pm_clarifies_real_gaps_and_requires_saved_exact_owner_confirmation`.
The removed runtime instruction replacement module is not restored: one
persisted catalog supplies the worker and evaluator instructions. A modified
historical catalog is rejected by the forward migration instead of silently
replacing appended security constraints; see
`test_upgrade_refuses_customized_catalog_without_changing_data_or_ledger`.


## Retired Native Assignment Test Coverage

`test_runtime_assignment_contract.py` retains the strict historical wire and
catalog role-key tests. Its old positive `assign_runtime_task`, native bind,
continuation and retry tests are removed together with those deleted commands.
They must not force a second executable protocol back into `TaskService`.

Current behavior is covered through the actual configured HTTP boundary:

| Invariant | Current regression |
| --- | --- |
| All professions, Developer initial/rework | `test_professions_share_assignment_step_history_and_terminal` |
| Resume unfinished work without native rebind | `test_new_assignment_continues_unfinished_phase_with_compare_and_swap` |
| Exact retry and changed payload conflict | `test_exact_report_replay_and_changed_payload_conflict` |
| Concurrent stale evaluator cannot commit | `test_report_interleaving_while_provider_releases_transaction` |
| Preserve old rows and phase during adoption | `test_new_assignment_adopts_retired_business_cursor_without_rewriting_history` |
| Tampered historical assignment cannot gain authority | `test_retired_history_and_adoption_refuse_unknown_or_tampered_assignment` |
| No alternative old HTTP writers | `test_retired_native_routes_are_absent_and_cannot_write_any_ledger` |

Historical DTOs, applied migrations and read-only history remain. This coverage
map does not claim the full suite, PostgreSQL or manual Hermes gate has passed.


## Retained PM History Reader

The read-only PM decoder validates the saved descriptor and custody hashes,
not equality with the current image's descriptor or installed manifest. Known
old single-task manifests remain decodable after the catalog upgrade. Historical
snapshots explicitly report `workflow_step_allowed=false`; no retired writer
is reintroduced.

`test_retained_pm_readers.py` checks unavailable current-image metadata, repeat
reads without mutations, corrupted payloads (including rehashed foreign roots),
agent/execution identity substitution and known archived manifests. Namespace
ownership and human project-scope tests now seed retained records directly
instead of invoking removed PM bind endpoints. Their focused combined run passed
104 tests; real PostgreSQL filled-upgrade and live acceptance remain separate gates.


The old `test_runtime_api.py` positive native assign/bind/rebind/step families
are retired with their HTTP writers. Its packet constructors and closed legacy
hash check remain for history fixtures. Credential isolation is now exercised
by `test_configured_service_auth.py`; replay, conflict and evaluator races use
`test_configured_cli.py`.

The former simultaneous legacy/current execution scenario is replaced by
`test_configured_namespace_coexistence.py`: identical human task keys in two
namespaces retain distinct records and reports, while only the configured
namespace executes. The focused coexistence/legacy-wire/reader run passed11
checks. Full pytest collection remains valid (3429 selected,149 excluded
integration cases); collection is not execution evidence.


## Перенос native PM проверок, 28 октября

Удалены исполняющие тестовые семьи PM bind/checkpoint/rebind/native continuation:
`test_pm_execution`, `test_pm_execution_edges`, `test_concrete_agent_mapping`,
`test_pm_assignment_guard`, `test_pm_generic_continuation`, `test_pm_draft_assignment`.
Удалены также один старый Base/PM executor-сценарий и 11 PostgreSQL-функций,
проверявших эти же удалённые RPC. Их helper-код не переносится в новый транспорт.

Права, идентичность исполнителя, CAS, повтор команд, смена назначения во время
оценки и продолжение текущей фазы проверяются через `test_configured_cli`,
`test_configured_cli_tracker`, `test_configured_service_auth` и API surface tests.
Исторические данные проверяются через прямой sealed fixture в
`test_retained_pm_readers`, `test_configured_namespace_coexistence` и отдельный
`test_retained_pm_migrations`: заполненная SQLite с версии 0014 обновляется до
0020 с сохранением прежних строк, идентификаторов и исходных JSON. Применённые
миграции и архивы сохранены. PostgreSQL namespace/project ownership fixtures
теперь создают исторические строки напрямую, без вызова удалённого bind RPC.

Scoped прогон общего протокола, authority и сохранённой истории: 125 passed.
Новый `test_configured_postgres` проверяет HTTP-путь всех семи профессий/восьми
режимов, одновременные отчёты и смену назначения во время оценки на настоящем
PostgreSQL. Внешние authority и evaluator в нём явно синтетические. Эти проверки
ещё не запускались; они не заменяют ручной прогон с Hermes.

Продолжается перенос оставшихся single-task/Base-native/retry test families и
удаление неиспользуемых адаптеров. Полная suite, PostgreSQL, упаковка и живой gate
ещё не пройдены. Уменьшение числа старых executor-тестов не является приёмкой.


## Удаление неиспользуемых native адаптеров и проверка источника инструкций

Удалены `infrastructure/pm_readback.py` и неиспользуемый
`application/single_task_terminal.py`: у последнего не осталось продуктовых
потребителей, текущий terminal endpoint принимает только configured selectors.
Сохранённые отчёты и terminal JSON остаются в прежней истории; PM history reader,
Base history reader и исходные таблицы сохранены. Удалены только ненужные
PM readback URL/token из product config, Compose и примера окружения. Runtime
и секреты установленной среды этим изменением не очищаются.

Удалены single-task native execution/producer/terminal, PM native review/resume
и PostgreSQL bootstrap/retry сценарии удалённых RPC. Проверки закрытого формата
сохранённого review context и forward-миграции 0019 перенесены в самостоятельные
retained history tests. PostgreSQL schema/catalog/UoW проверки сохранены;
устаревшие assignment/bind/rebind методы в них ещё требуют отдельного разбора.

Известный старый профиль остаётся доступен для чтения и не переписывается
bootstrap-процедурой. Новое назначение и исполнение требуют точного текущего
каталога configured-инструкций; иначе агент получил бы файловый bootstrap под
новым транспортом. Проверено на трёх настоящих архивных профилях: новое назначение
отвергается без изменения строк, архив продолжает читаться. Текущий профиль
остаётся положительным соседним случаем в общей protocol suite.

Scoped проверки после этого изменения: 100 passed; collection без ошибок импорта
(3155 selected, 110 integration excluded). Полный прогон и PostgreSQL остаются
открытыми. Этот результат не является установкой или живой приёмкой.


## Общая проверка сохранённого результата и завершение retirement тестов

Новый terminal readback теперь проверяет полную сохранённую оценку отчёта:
замороженный контракт и граф фаз, fingerprint, полный набор уникальных covered
IDs, ответ evaluator, точный сохранённый текст отчёта и исходный command hash.
Та же проверка действует на точный повтор финального отчёта и чтение завершённого
шага. Чтение terminal receipt не обращается к текущему native run или к модели.
Проверка извлечена из historical Base reader в общий `supervisor/evidence.py`;
исторический report fingerprint и текущий operation fingerprint имеют явных
владельцев, без двух реализаций валидатора. Supervisor сохраняет полное состояние,
из которого он уже вычисляет fingerprint; JSON history и таблицы не заменяются.

Сценарии Base-native admission/terminal/owner executor перенесены на текущий путь:
общий configured API и `test_frozen_evaluation`. Удалены старые positive bind,
rebind, callback и DB-CLI fallback тесты, требовавшие удалённых методов. Для mode,
managed catalog и hardening сохранены проверки схемы, editing, прав и history.
Широкая work-item revision PostgreSQL проверяется через импорт архивной записи и
типизированное чтение, без восстановления native assignment writer.

Локальные DB-CLI E2E retired: агентный CLI больше не создаёт задачу локально и не
читает DATABASE_URL. Их custom/parallel/rollback evaluator поведение остаётся в
Supervisor unit/application tests. Новый integration-сценарий запускает настоящий
CLI subprocess → HTTP приложения → PostgreSQL для PM и Developer Rework, с точным
повтором, stdin, history и контролем отсутствия служебных файлов. Все семь
профессий и восемь режимов дополнительно покрыты API/PG сценариями. Внешние
Tracker/Auth/evaluator там синтетические; PostgreSQL и subprocess scenarios пока
не запускались. Они не заменяют отдельную ручную приёмку с настоящим Hermes.

Scoped configured API и frozen-proof проверки: 101 passed за 94.75 s. Проверены
повреждённые fingerprint, контракт, coverage, evaluator, worker report и outcome;
положительные текущие и historical fingerprint варианты сохранены. Итоговый
полный прогон, PostgreSQL, packaged CLI, установка и Hermes/IAB остаются открытыми.


Дополнительно восстановлена граница обычного Supervisor: TaskService выбирает
начальную фазу сам; удалён вызов уже удалённого private guard и дублировавший этот
выбор helper. Managed/single-task задачи без назначения не исполняются через
обычный Supervisor. Пользовательский специализированный workflow сохраняет
обычное поведение. Проверки текущего назначения идут по общему configured fence.

Иконка и цвет профессии исключены из технической идентичности Single-task
каталога. Иначе обычное изменение оформления блокировало capabilities и работу
всех профессий. Названия, ключи, workflow/mode membership и полное содержимое
инструкций продолжают проверяться; bootstrap не переписывает оформление.
Legacy managed comparator по умолчанию остаётся строгим. Проверены три варианта
оформления и соседние отказы при повреждении инструкций/режимов.

Для source CLI-проверок в отдельный task-venv установлен `pdlc-cli-core` из
согласованного Base contract checkout. Это не обновление SDK pin или runtime.
Первый install без build isolation обнаружил отсутствие hatchling; стандартный
изолированный offline build из существующего cache завершился успешно.
Scoped соседние проверки: 75 прошли; ещё четыре устаревших native instruction/API
assertions перенесены на текущие контракт и guards. Следующий focused прогон
прошёл 44 проверки, одна точная текстовая проверка исправлена на фактический
`Backlog / Ready`; финальная проверка этого случая выполняется отдельно.
Все PostgreSQL и итоговые release gates по-прежнему не выполнены.


Последний focused catalog case прошёл: 1 passed. На фазах Reviewer/Tester
сохраняются отдельные инструкции по честному verdict/rework после инструкции
отправки отчёта; проверка учитывает весь terminal phase contract. Collection:
2966 selected / 3076 total, 110 integration deselected, ошибок импорта нет.
Новые subprocess/PG tests только собраны, их исполнение не заявляется.


## Source qualification recovery, 2026-10-28

The first complete Workflow unit run found 35 failures and did not meet the
94% coverage threshold. It is not a passed qualification. Fixture/head assertions,
current CLI help and the no-bootstrap error expectation were corrected; the first
recovery batch passed 86 tests, then 13 UI/help/catalog tests. Ruff and mypy passed.

The canonical SingleTask builder now owns rendering directly. Its catalog and
manifest hashes are unchanged. The unused intermediate proposal builder and the
uninstalled PM Draft CLI prototype were removed; historical descriptions link to
the frozen Git version. Applied migrations and published history were retained.

The unconsumed `/internal/runtime/base/terminal-receipt/readback` route, its
admission placeholder, temporary PM token verifier and native Supervisor fence
were removed. They had no Tracker/Fleet/Base consumer. The configured terminal
route and read-only retained PM history remain. The obsolete admission-executor
test was retired with that executor; actual source binding/catalog/history and
retired-route refusal checks passed 121 tests, with three environment skips.
Final coverage, PostgreSQL, packaged CLI and live acceptance remain outstanding.
