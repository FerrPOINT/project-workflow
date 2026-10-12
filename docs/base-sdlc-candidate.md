# Base SDLC candidate v1

Статус: configuration-only, не установлен, 2026-10-02.

Source slice 2026-10-03: [opt-in admission](base-sdlc-admission.md) подключён
к существующим assign/bind/step. Durable terminal receipt/readback и explicit
source-only v3 exporter добавлены поверх accepted history/bind/cursor ledger.
Owner-contract audit: локальная согласованность ledger не подтверждает frozen
Fleet execution/config или Forge evidence. Production Base step/replay/terminal
readback fail closed до trusted owner lookup; успешная receipt derivation
проверена только как synthetic component. Fleet `runtime_ready=false` сохраняется.
Это не установка candidate и не завершение
полного B-SDLC-03; ограничения и зависимые owner capabilities указаны отдельно.
Дополнение 2026-10-03: read-only donor audit семи legacy DEV databases обнаружил
managed 7/13/39 и total 8/14/58 (workflow/mode/phase); managed инструкции,
checks и evidence совпадают с committed legacy catalog. Это не Base acceptance.
Candidate остаётся 7/11/33: Developer только initial/rework с независимым scope.
Не импортировать legacy DB/лишние modes и не объявлять candidate установленным.
Исторические metadata/hashes находятся в приватном services-base donor package;
effective config/materialization принадлежат Fleet, admission/exporter — B-SDLC-03.
Отдельный файл: `project_workflow/references/base_sdlc_catalog_v1.json`.
Сохранены technical schema `relevanter-project-workflow-catalog/v1`, workflow keys,
namespace/profile, mode keys и 33 phase codes существующего каталога.
Семь workflow, 11 modes, три упорядоченные фазы каждого режима. Version 3 — отдельный
candidate, не переключение default catalog version 2.

| Роль | Mode | Scope |
| --- | --- | --- |
| Project Manager | draft | business |
| Analyst | analysis | business |
| Architect | decomposition | business |
| Developer | initial, rework | delivery, aggregate (независимый scope) |
| Reviewer | delivery, integration | delivery, aggregate соответственно |
| Tester | delivery, integration | delivery, aggregate соответственно |
| DevOps | delivery, integration | delivery, aggregate соответственно |

Фазы: exact step admission → полный порядок действий роли → accepted report,
complete=true, итоговый комментарий и разрешённая owner terminal capability.
Количество инструкций не ограничено тремя. Первый шаг получают через реально
настроенную Workflow tool: Fleet PM использует MCP `workflow_step` с `report=null`.
CLI step/history допустим только при установленной и настроенной интеграции,
не как запасной способ обойти недоступный MCP.

## Передача задачи после последнего шага

### Opt-In CLI V4 Source

Новый [CLI catalog v4](../project_workflow/references/base_sdlc_catalog_cli_v4.json)
закрепляет merged Base `4e5647d3a3015c26be8f5a390c4d5537d1d10d02`.
Сохранены семь ролей, 11 modes, 33 phase codes, profiles, skills и graph.
Исторический v3 `base_sdlc_catalog_v1.json` не перезаписан. Это только source:
активный default, bootstrap, installed IDs, bindings и history не переключены.

```bash
python scripts/build_base_sdlc_candidate.py --cli-v4 --skills-root <authorized-base>/agent-skills --skills-sha 4e5647d3a3015c26be8f5a390c4d5537d1d10d02
python scripts/verify_base_sdlc_candidate.py --candidate project_workflow/references/base_sdlc_catalog_cli_v4.json --skills-root <authorized-base>/agent-skills
```

Флаг `--cli-v4` пишет только новый v4 artifact; verifier без `--candidate`
по-прежнему проверяет v3. Проверка читает immutable Git package, не заменяет
runtime admission или deployment. Старые receipts не квалифицируют v4.
Runtime protocol v2 — отдельный контракт, не номер source catalog.

### Explicit CLI V4 Adoption

Producer поддерживает opt-in `PROJECT_WORKFLOW_CATALOG_VARIANT=base-cli`; default
`legacy` и source-only `base` (v3) не изменены. Существующий image builder принимает
`--catalog-variant base-cli` и формирует тот же семиполевой runtime compatibility
descriptor: `catalogVersion=4`, Base `4e5647d3a3015c26be8f5a390c4d5537d1d10d02`,
`capabilityRevision=hermes-sdlc-runtime/v2`. Revision/hashes descriptor вычисляются
из immutable image source и exact Git package, а не задаются агентом.

После отдельного operator review/build deployment с этим variant может вызвать
существующий `python -m scripts.init_db`. В одной catalog-locked транзакции v3→v4
добавляются новые mode/phase rows и переключается active version для новых
assignments. Полный frozen v3 проверяется до первого изменения; divergent/partial
state отвергается. Повторная установка идемпотентна. Workflow/namespace/role IDs,
старые mode/phase IDs, tasks и history не переписываются. Поддерживается также
пустая managed DB; legacy v2→v4 не является этим adoption path и отвергается,
а не заменяется сбросом БД или relabel старых rows.

Для pin verification нужен существующий `PROJECT_WORKFLOW_BASE_SKILLS_ROOT`
на авторизованный canonical Git package с exact v4/4e object. Для отдельного
исторического v3 source readback по-прежнему требуется v3/4b9 object.
Source export и namespace binding readback сохраняют schema и поля, но допускают
только согласованные пары v3/4b9 либо v4/4e. `sourceOnly=true`/`runtimeReady=false`
остаются границей этих read-only observations, не execution acceptance.
Fleet должен отдельно поддержать v4 tuple; этот пакет не меняет Fleet pin/default.

V4 исполняется через существующие machine assign/bind/step и PM
assign/checkpoint/resume/rebind/readback, с текущими role credentials, namespace
ownership, immutable descriptor, CAS/run fences и execution token. Legacy human
step и обычное создание задачи не обходят owner assignment. V3 admission/HOLD
сохраняется; v4 не использует этот source-only receipt как новый runtime protocol.
Первый agent terminal command получает reportless Workflow step через настроенный
HTTP CLI. Это не Hermes hook и не требование доказательства до обращения к модели.

Final instructions остаются exact role/mode content: typed result, разрешённый
Tracker transition и его readback. PM ждёт подтверждения человеком exact revision,
не подтверждает за владельца. Workflow technical completion не является Tracker
business completion: недоступный scoped Tracker CLI/producer transition остаётся
blocker, не подменяется CRUD patch, новым tool или выдуманным receipt. Здесь не
активированы runtime/config, не выполнены PG/native/live acceptance.

Source-only уточнение генератора `scripts/build_base_sdlc_candidate.py`:
будущие first/final instructions используют только existing runtime CLI `step`
с operation key, request JSON и scoped execution token; report идёт тем же CLI.
Ни frozen JSON ниже, ни pins/default/history этим изменением не обновляются;
описанная ниже таблица сохраняет исторический content, не новые CLI-команды.
Генератор готовит Analyst typed result через Workflow report; Tracker
`sdlc analysis result submit/operation` допустим только authorized caller.
Текущую scheduler identity нельзя выдавать Hermes. Для остальных non-PM ролей
guarded completion/readback CLI остаётся конкретной producer dependency;
target status/stage не угадываются и generic CRUD не является обходом.
PM по-прежнему ждёт exact owner confirmation, не подтверждает за человека.
Обычные структурированные clarification и owner checkpoint ведёт PM. Остальные
профессии принимают обычные технические решения в рамках approved requirements;
только критическая бизнес-неопределённость передаётся через PM/root с linked
checkpoint. Инфраструктурные blockers адресованы оператору, а tool approval
не заменяет бизнес-ответ или owner consent.
Отдельные comment mutation и checkpoint/readback CLI здесь не добавляются.
Base skill content с прежними MCP references требует отдельного owner update;
этот пакет не квалифицирует установленный CLI, role execution или handoff.

Уточнение инструкций от 2026-10-12 не устанавливает candidate и не добавляет
несуществующие tools. После `complete=true` и сохранения результата агент должен
запросить через разрешённую Tracker capability следующий **статус и стадию**, затем
прочитать transition receipt. Tracker проверяет переход и остаётся владельцем
бизнес-состояния. Обычный patch карточки не заменяет эту операцию.

| Завершённая роль | Запрашиваемая передача |
| --- | --- |
| PM | После подтверждения владельцем exact revision/hash: Draft → Backlog; Tracker ставит Analysis/Готово в очередь |
| Analyst | Architecture/Готово |
| Architect | Development/Готово разрешённых задач с сохранением root barrier |
| Developer initial/rework | Review/Готово той же задачи |
| Reviewer | Testing/Готово; при needs_rework — Rework/Готово с frozen findings |
| Tester | Deployment/Готово; при needs_rework — Rework/Готово с frozen findings |
| DevOps | Deployment/Завершено только проверенной задачи; child не завершает root |

Assignment/execution, версии, исходный operation key, Workflow receipt и evidence
передаются вместе с запросом. Неизвестный ACK сначала сверяется по тому же ключу;
недоступная capability остаётся конкретным blocker, а не успешным завершением.
PM не подтверждает требования за человека и не запускает Analyst вручную.
Набор Fleet PM MCP не содержит отдельной terminal transition tool и не нуждается
в ней для дублирования owner confirmation. PM проверяет именно её Backlog receipt
и server-created Analysis intent; новый machine publish вместо человека запрещён.
Pin Base, default catalog, bootstrap и существующая история здесь не изменяются;
обновлённый пакет role/skill-инструкций требует отдельной совместимой активации.
Source-only exporter проверяет новую опубликованную редакцию каталога
`b01fc3c9b017b81a178ef678754d8f23f9943af7`, Git blob
`71560ee37de8acfd020630d58a036618f007b94b`. Проверка целостности остаётся строгой;
старые receipts и skills pin не переименовываются в новую редакцию.

## Проверка без установки

```bash
python -c "from project_workflow.infrastructure.db.managed_catalog import load_managed_catalog; load_managed_catalog('project_workflow/references/base_sdlc_catalog_v1.json'); print('PASS')"
python scripts/verify_base_sdlc_candidate.py --skills-root ../services-base/agent-skills
python -m pytest -q tests/base_candidate --timeout=60
```

`Business Markdown comment` оставлен только как literal compatibility marker
текущего валидатора. Его смысл здесь — Task Tracker comment. `publishDraft` и
`completeAssignedStage` — target capabilities Tracker, не новые CLI-команды.
Ни marker, ни schema не возвращают ownership Relevanter Business.

## Assignment/receipt v1: оставшаяся адаптация

Канонические role-инструкции и skills принадлежат приватному Base; Fleet —
потребитель и владелец effective runtime config. Skills source закрепляет exact
Base commit. Проверка читает Git blobs этого commit, а не текущий HEAD/filesystem:
следующий docs commit Base не меняет pin. Неизвестный commit, неправильный source,
schema/hash/allowlist — ошибка без Fleet/local fallback. Для чтения требуется
авторизованный доступ к Base; credentials и копии пакета сюда не добавляются.
Pin candidate не переключает SDK `.base-revision` и active legacy catalog.

Workflow владеет каталогом и technical cursor, а не Task lifecycle. Исторический v3
admission остаётся source-only: рабочие действия требуют совместимых exact Tracker
assignment, Fleet config и Forge workspace lease; это не Hermes pre-model hook.
Report/history keyed task+mode+scope+cycle+phase+assignment/run fence.
Accepted terminal receipt фиксирует complete=true, assignment/result hash,
catalog/config/skills hashes и cursor revision. Task completion остаётся Tracker.
Повтор key/payload возвращает receipt; иной payload conflict; stale run/revision
не продвигает cursor. Resume требует owner checkpoint ACK, fresh lease/run и CAS
rebind unfinished phase при прежних mode/scope/cycle/attempt.

Legacy runtime exporter по-прежнему содержит Business-routing/workspace metadata.
Отдельный `/internal/runtime/base/source-catalog` использует native derivative,
но содержит Tracker/Fleet/Forge ownership и `sourceOnly=true`, `runtimeReady=false`;
экспорт этого candidate нельзя считать готовой runtime конфигурацией Base.
Default catalog, migrations, runtime token config и pinned history не изменяются.
Explicit v4 adoption описан выше; его наличие в source не подтверждает deployment
или business/runtime acceptance.
