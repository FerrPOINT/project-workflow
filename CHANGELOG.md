# Changelog

## Diagnostics Release Boundary — 2026-11-01

- Release retains v12 prompts, parser, model parameters, retries and catalog10.
  The v17 procedure omission and v18 output-order candidates are not accepted
  for installation. Their branches and all experiment outcomes are retained.
- Captured SDLC-24 reports164/167: control PARTIAL6/6; procedure omission
  PASS6/6. The result confirms a narrow input-framing effect, not model reasoning.
- Correct original-shape47-case replay (three fixed calls per case): exact item
  matches control35/141, v17 91/141, v18 98/141. Negative133 remains falsely
  accepted: control1/3, v17 2/3, v18 1/3. Neither candidate meets acceptance.
  The masked-hash corpus is not semantic quality evidence.
- Four synthetic tests reproduce unmasked configured environment credentials.
  Existing redaction now recognizes these names as well as native PAT prefixes;
  operation keys, content hashes and fencing tokens remain unchanged.
  112 targeted diagnostics/API/LLM tests PASS, including exact v12 policy AST.
- Installed baseline is still1a8a9ee/image ed53633db317. Security changes are
  source-only until the next qualified Workflow-only installation. No PM,
  Hermes, Fleet, credentials or catalog activation is included.
- Next: qualify this diagnostic/security-only SHA, retain both new baseline
  QA outcomes and analyze the remaining contradiction case without rerunning
  unchanged builds or accepting an experimental verdict policy.

## Diagnostics-Only Baseline — 2026-11-01

- Причина: совмещённый кандидат изменял оценку до сбора исходной диагностики;
  сохранённые ложные missing/covered не доказывают внутреннюю причину модели.
- Изменение: сохранены prompt/parser/evidence policy и PM-каталог установленного
  `fb983944` (v12); добавлено только наблюдение через существующие snapshots/history.
- Проверка: 257 целевых тестов PASS, включая неизменность prompt/parser v12,
  диагностику, CLI, публикацию и историю; Ruff PASS.
  Результаты совмещённого v16 не выдаются за проверку этого кандидата.
- Установка: normal Workflow-only Apply завершён на `1a8a9ee`,
  image `ed53633db317`, journal `025453de4ff143c78ae7a5a362d88ad5`.
  Health/schema/catalog OK; Fleet не пересоздан, PM остался на revision23 и
  прежнем Hermes image. Каталог10 `ae220f915d...` не публиковался заново.
- Независимый review воспроизвёл ошибку изоляции metadata: исключение capture
  могло заменить корректный content техническим отказом. Извлечение изолировано;
  текущая запись ограничена шестью полями v12. Пояснения старых trace остаются
  только read-only отображением, не новым контрактом ответа.
- Отдельный полный прогон `3fa96ed`: 3310 PASS, 73 passing subtests,
  15 explicit skips, coverage94.07524752475247%; 132 real-PG PASS с очисткой.
  Итоговый `1a8a9ee`: 3312 PASS, 73 passing subtests, 15 explicit skips,
  coverage94.08223084845125%; 132 real-PG PASS, оба scratch/QA очищены.
- Живая диагностика SDLC-24: четыре PARTIAL в контексте (history164–167)
  требуют результат отправки самого проверяемого отчёта. Вход/ответ v12
  сохранены: HTTP200, stop, без усечения. Это круговой критерий, не ошибка
  Hermes/CLI или доступа. Run уже terminal; повторного запуска не было.
- Следующая проверяемая гипотеза: не добавлять процедуру исполнения в prompt
  judge при явном полном checks/evidence. До ограниченного сравнения с
  положительными и отрицательными случаями новая политика не установлена.
- Точное interleaved сравнение captured164/167 (по три вызова каждого варианта):
  control0/6 PASS, без процедуры6/6 PASS. System/parser/report/criteria/settings
  сохранены; широкий 47-case набор проверяется отдельно, результаты не выбираются.
- Найден source-дефект redaction штатных sdlc_pat_/pdlc_pat_: два failing теста
  воспроизвели пропуск, существующий masker дополнен одной regexp.
  72 целевых теста и Ruff PASS. Это исправление ещё не установлено.

Все значимые изменения проекта документируются здесь.
Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование — [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

### Historical Uninstalled v16 Experiment - 1 November 2026

This section records the earlier combined candidate, not the current release.
Its changed response schema and policy were removed before diagnostic installation.

- Cause: a saved aggregate message/coverage list cannot distinguish every
  provider/format failure or explain which exact prompt was used. Six v15
  refusals are unsupported; other incomplete PM reports are genuine PARTIAL.
- Added bounded, redacted per-attempt evidence to existing evaluation snapshots
  and an opt-in authorized CLI history projection. No new service, migration,
  automatic verdict repair, Hermes change or additional model call.
- Evaluator v16 requests concise item-level explanations and report quotes.
  Invalid annotations are flagged without changing verdict acceptance; v15 and
  older frozen receipts remain readable. Captured-text quote comparison is not
  independent verification of evidence. Capture failures cannot block a valid
  evaluation; an explicit byte budget bounds persisted/exported diagnostics.
- Source checks and installed/live acceptance are separate. This candidate is
  not installed; diagnostic instrumentation alone does not prove that semantic
  false refusals are eliminated. Next: use the captured counterexamples to
  qualify a bounded grading correction before new PM acceptance.
- Three one-shot real-model fixture checks demonstrate useful item reasons and
  matching report quotes, not stable grading:136/163 are false refusals;153 is
  legitimately PARTIAL but falsely covers two criteria. No Workflow writes or
  repeat-until-PASS calls. HTTP200/stop and untruncated inputs rule out a transport
  or capture truncation explanation for these specific failures.
- The first full diagnostic gate stops at an obsolete precommit-label placement
  assertion after631 passes. It now checks the worker contract and actual system
  policy separately, retaining real PASS/PARTIAL and no-future-receipt assertions;
  all71 configured-CLI tests pass.132 real PG tests pass with owned QA cleanup.
- Full source19f018b4 runs every non-PG case:3312 pass,73 subtests pass,15
  explicit skips,132 integration deselections, coverage94.08269961977186%.
  Its sole failure is the old Settings CLI-option allowlist. Adding the new
  optional flag and checking its help/default fixes that test;96 focused
  Settings/diagnostic cases pass afterward. Product/API source is byte-identical
  to19f018b4 and the PG-qualified fcb40db0. The failed full receipt is retained,
  not relabelled as one all-green invocation. Ruff, mypy166 and OpenAPI parity pass.

### PM Stability Follow-Up - 1 November 2026

- Installed v12/catalog10 independently completes both SDLC-22 and SDLC-23 in
  Backlog/Ready. Sparse requirements3, exact owner receipt and zero Analyst/Analysis
  are verified read-only; the previous5/12/8 PARTIAL counts remain a quality gap.
- Source3a85115/v13 separates worker procedure from checks/evidence and preserves
  frozen v12. Full3220 tests plus73 subtests,15 explicit platform/opt-in skips,
  coverage94.03093868956022%,132 real PostgreSQL tests and53 dependency pins pass.
- Previous candidate v15 omits procedure from explicit evaluation prompts while
  retaining every required item, full contract fingerprints and historical
  versions. Corrected PM reports retain the FULL packet; unchanged requirements
  are not republished. Artifact hashba81253 is not yet published to the stand.
- Real-model replay is NOT accepted: independent review identifies six unsupported
  refusals, plus genuinely incomplete old reports. Medium reasoning did not
  eliminate those refusals. Parser consistency/owner/hash guards remain strict;
  no verdict is repaired into PASS and Hermes is unchanged.
- Candidate7940c47 passes132 real PG tests but its full gate stops at the existing
  first-step execution-ID context regression; this is not a passing full gate.
  The stale placement assertion is corrected with both targeted cases passing:
  identity semantics remain in CLI instructions; report delivery and PARTIAL
  behavior are still asserted. A final full run is not claimed.
  v15 remains uninstalled. Whether PM should retain model report grading or use
  authoritative Tracker facts is a separate pending product decision.
- Isolated CLI checks now use the qualified CLI Base278be4a2 through an explicit
  clean checkout/PYTHONPATH, independently of namespace SDK/UI pins. All26
  transport tests pass; CI/local setup is reproducible without a global package.

### Added

- Catalog10 simplifies the three PM phases after SDLC-21 PARTIAL128 demanded
  an extra namespace attestation although the CLI environment already held2.
  Servers still enforce identity/assignment/access; the PM reports actual task,
  request and decisions, not another certification of every technical field.
  Instructions shrink from14632 to5868 characters with identical5/6/5 instruction,
  2/4/5 check,1/2/2 evidence counts, scopes and skills. Requirements completeness,
  exact owner consent and postterminal Tracker completion remain explicit.
  Published hash `ae220f915d33987f1ed9b13e39d9a4c3a82ea5d8db133638a6a06f384ae249ef`;
  seven focused tests and Ruff pass. No code/image rebuild; prior executions stay
  frozen. Full-brief SDLC-22 now reaches real Backlog/Ready: context130,
  preparation131 and terminal135 PASS, exact owner receipt853d9814/req1/hash898f7e7e.
  Independent read-only PG verifies owner/hash and zero Analyst/Analysis. PM
  self-corrected final PARTIAL132-134 without technical hints or document changes;
  that overhead is not claimed eliminated. Sparse SDLC-23 also reaches actual
  Backlog/Ready with revision3, exact owner consent and terminal PASS163;
  independent PG confirms owner/hash and zero Analyst/Analysis.
  Fleet's completed-task initial POST replay returns409; its separate worker
  delivered the fix with five passing Linux regressions. Installation and live
  original-key replay remain open. This is not complete release acceptance.

- Catalog9 text-only correction follows retained SDLC-20 reports120-125:
  the final phase is named "Owner-confirmed requirements", not "before final
  Workflow report"; check5 assesses concrete specification sections, not whether
  the current report's conclusion has already been accepted. Report125 repeated
  that circular requirement despite including FULL requirements and exact owner
  confirmation. Checks1-4, presentation/consent evidence and actual postterminal
  Tracker completion are unchanged. Published hash
  `a85f4a78d79aa28efd5e577db24b5eb7a204cccff54b8ad6352a3ee9b37f4209`;
  seven focused tests and Ruff pass. No product/image rebuild. SDLC-20 remains
  frozen on8, with requirements/consent and PARTIAL history intact; fresh live
  acceptance of9 is still open, not inferred from synthetic tests.

- PM default text follow-up published through the existing API as catalog8:
  final check5 now assesses the affirmative business conclusion against the FULL
  saved document, resolved feedback and included matching owner confirmation.
  Actual SDLC-18 v12 history115 otherwise demanded readbacks of nonexistent
  postterminal operations to prove their absence. Phase02 now explicitly accepts
  actual publication/readback data with the same revision/hash and ONE FULL
  document, without duplicate raw CLI JSON or stdout attestation. Remaining
  document/presentation/owner checks and postterminal Workflow -> Tracker commands
  are unchanged. Candidate normalized hash
  `bd0e6d6e10b8a8b0ab2942e99dab82d0f3a2651ddd5566956910ba3896fd6878`;
  code/image unchanged.18 final-text scoped regressions pass with synthetic
  authorities/verdicts. Catalog7/hash0434499 and old QA18/19 remain preserved,
  unaccepted; NEW full-brief QA is running on catalog8. Sparse and actual
  Backlog/Ready acceptance remain open.

- Evaluator v12 distinguishes the CURRENT report's submission protocol from
  precommit work. Real SDLC-18 report106 demanded proof of sending that same
  report and reading its future result despite coherent catalog7 checks. The
  shared prompt now excludes only that circular prerequisite; actual business
  commands/results, external readbacks, FULL content and owner consent remain
  required. No automatic PASS, new API or Hermes change. Historical v11 terminal
  proof remains explicitly trusted with the same fingerprint/coverage guards.
  Source `fb983944` passes 159 targeted tests, Ruff and mypy (165 source files).
  Full non-PG qualification: 3193 passed, 73 subtests passed, 15 skipped,
  132 deselected; coverage94.02997164844066% at required94%. Dedicated PostgreSQL
  qualification: 132 passed, no skips/failures/errors; owned QA resources cleaned.
  Exact-image fresh migrations/health/OpenAPI smoke passes and is cleaned.
  Normal Workflow-only Apply `82089f04ed294324a5d4b820a71a4884` is COMPLETE:
  image `39d33eebd591a97404c6e351087c5dd695d72a1e191d7540928bae21fc910ba1`,
  actual container reads v12; health/database/schema/catalog OK, Fleet unchanged.
  Catalog7/hash0434499 and old SDLC-15 CLI history/version6 are unchanged.
  SDLC-18 resumed the SAME task/requirements1/owner receipt after the v11
  report106 circularity and acknowledged native cancellation; v12 history115
  remains PARTIAL, not Tracker Backlog acceptance. Sparse SDLC-19 produced its
  first useful question, not requirements or completion. These are separate installation,
  local qualification and live boundaries, not model acceptance from mocks or
  historical PM13. See [the v12 checkpoint](docs/configured-cli-v1.md#installed-v12-checkpoint-2026-10-31).

- Portable default PM text revision in
  `docs/evidence/pm-default-workflow-20261031.json`: three existing phases with
  coherent preparation/presentation/consent requirements. Phase02 evidence is
  the full saved document and prepared review packet, not future presentation;
  phase03 requires actual presentation and exact saved owner consent before
  postterminal Tracker completion. No report per ordinary reply or premature
  consent request. Counts/scopes/skills and sealed legacy artifacts are unchanged.
  The preceding snapshot hash0434499f is published as catalog7 on the checked stand
  through the existing API; the current tracked candidate is described above.
  Old SDLC-15 CLI history remains unchanged. No application
  rebuild, Hermes change, endpoint or migration.18 targeted API/SQLite/CLI-format
  regressions on that preceding catalog7 snapshot pass using explicit synthetic
  Auth/Tracker/LLM fixtures; real PM full/sparse acceptance remains separate.
  Catalog4 exposed a nonexistent Workflow project_id requirement;
  catalog5 passed preparation after repeated conditional-evidence verdicts.
  Final text bounds source-specific comparisons and gives input-resolution
  evidence two explicit applicable paths. Its final phase exposed a future
  completion prerequisite; catalog7's current-Draft/absence check then exposed
  the history115 negative-proof demand, corrected in the new candidate above.
  Actual completion remains after accepted Workflow. Owner
  confirmation uses the separate application control, not a chat phrase.
  No forced PASS or engine change; earlier test/report history remains unchanged.

Historical implementation checkpoints below retain their original source/scope;
their then-pending gates are not the current v12 installation status above.

- Страницы фаз PM показывают один набор инструкций установленного каталога.
  `effective_view` сохраняет raw-поля API без подмены инструкций при исполнении.
  Запись в sealed PM каталог отклоняется; обычные workflow сохраняют редактор.
  Подтверждение владельца относится к третьей фазе. Проверка исходников, UI,
  установка кандидата и живая приёмка учитываются отдельно.

- Configured PM preparation in retained652a now asks questions/offers alternatives
  only for actual gaps or meaningful choices. Eight focused content checks cover
  all supported families, real judge prompts and appended security constraints;
  Ruff/diff checks pass. Catalog bytes and legacy execution remain unchanged.
  This source correction is not installed live acceptance. The generic editor
  still requires compatible sealed-catalog publication/adoption before arbitrary
  text edits can be consumed by configured execution; that gap is not bypassed.
- Configured PM final judging is precommit-only: valid full saved requirements,
  resolved feedback/questions and exact actual owner consent in Draft. The
  worker retains its full terminal-receipt/Tracker completion commands, but the
  judge cannot require those future effects before its verdict. Known retained
  terminal/check/evidence variants are projected without changing the legacy
  catalog or custom security constraints. No forced PASS or new authority.
  All35 configured tests and independent review pass on210db1; normal
  Workflow-only installation preserves all nine history tables. The SAME real
  PM11/FLEETQA-8 then produced PASS/complete=true/version14/history13 and an
  authoritative terminal receipt. PM submitted Tracker completion through CLI;
  Backlog/Ready, one completion and zero downstream assignments/intents were
  verified, including original-key replay. This is assisted existing-task live
  acceptance, not fresh autonomous or full release qualification.

- Configured PM preparation instructions distinguish the independently generated
  Workflow execution_ref from Tracker assignment.execution_id, and Workflow
  cursor versions from Tracker assignment versions. Match task/assignment/agent
  identities by authority; do not rebind or invent IDs to make unrelated IDs
  equal. Eight focused source tests pass, including evaluator prompt coverage.
  The instruction corrections are installed with210db1. In the existing
  live PM chat, an explicit explanation allowed the agent to submit a corrected
  report and advance PM-DRAFT-01 to PM-DRAFT-02; that assisted check is not full
  autonomous PM or Backlog acceptance.

- Opt-in configured-cli-v1 for new PM tasks: existing trusted assignment and
  direct step/history endpoints with a dedicated per-agent Auth PAT, current
  Tracker assignment validation, version/key replay and actual owner-confirmed
  terminal receipts. No temporary CLI files, native/Fleet callback or human-route
  machine admission. Legacy records and applied schemas/catalogs are unchanged.
  Host qualification is scoped; PostgreSQL, packaged/integrated and live gates
  remain open. See docs/configured-cli-v1.md for wire and deployment dependencies.

- Обновлён штатный SSR export Base: страницы ошибок больше не показывают лишний заголовок None. HTTP-регрессия проверяет единственный правильный h1 и возврат к списку как в корне, так и под UI_BASE_PATH.

- Навигация и редактор учитывают UI_BASE_PATH: смена профессии со страницы фазы сбрасывает прежние workflow/mode и сохраняет проектный контекст; порядок инструкций сохраняется без повторного префикса, а возврат со страницы ошибки остаётся внутри приложения.

- Штатный SSR export Base сохраняет размеры полей без внешнего CSS reset. Регрессия редактирования namespace проверяет сохранение как default, так и custom workflow.

- Резервное меню сервисов сохраняет локальную навигацию Workflow. Неподтверждённые
  адреса других приложений недоступны; после восстановления каталога Admin
  и обновления страницы ссылки снова доступны.

- Форма Workflow блокирует поля, повторную отправку и смену выбранного процесса
  до завершения записи и обновления данных. Ошибка сохраняет введённые значения;
  поздний ответ больше не стирает новый ввод. Защита процесса по умолчанию сохраняется.

- Платформенные UI/SDK imports и пути переведены на PDLC и `base-modules/ui`; совместимые readers сохраняют прежние credentials/транзакции. Нормативные термины и границы описаны в `docs/PDLC_BASE_INTEGRATION.md`; установка и включение новых writers выполняются отдельно.

- Оболочка не загружает Google Fonts: использует локально доступные шрифты и
  существующие системные fallback, сохраняя работу без внешней сети.

- Логотип оболочки использует общий размер Base 40 px; компактный сайдбар равен высоте хедера (60 px).

- Base SSR export закреплён на `5b460dd20eea`: WebKit сохраняет click по
  ссылке выхода при переносе фокуса на родительский main. Fingerprint обновлён
  штатным export; включены актуальные Base shell tokens.

- Runtime CLI `step` forwards the supplied operation key, frozen request and scoped token;
  it requires an explicit service URL and never sends execution credentials to the legacy default endpoint.

- Namespace cohort: стабильные refs, локальные binding projections и lifecycle guards; аддитивные migrations, совместимый rollback и отдельные execution v2 gates. Runtime-приёмка ещё не завершена.


### Changed
- 2026-10-30: evaluator `supervisor-evaluator-v11` respects phase-defined
  evidence sufficiency for actual command readbacks and reported user-facing
  presentation. No extra execution/presentation attestation is required unless
  the phase contract requires it; full content, actual presentation and exact
  saved owner consent remain mandatory. Reports use ordinary text/Markdown stdin.
  Source `861e08c` passes 113 scoped mocked-provider/SQLite tests. Its exact image
  passes isolated startup/migrations/health/OpenAPI QA and was installed by normal
  Workflow-only Apply. The SAME assisted PM13 task/execution then reached final
  Workflow PASS/history70/cursor23 and independently verified Tracker Backlog/Ready,
  without Analyst/Analysis records for that task. Earlier failures remain history.
  This is not fresh unassisted, all-role, full-gate or Kubernetes acceptance;
  exact identities, image and local evidence are in
  [the configured CLI record](docs/configured-cli-v1.md#scoped-pm13-evidence-2026-10-30).
- Configured PM first-step reports explicitly include the already observed CLI
  stdout fields and Tracker task/input references. CLI JSON is flattened; do not
  invent HTTP ok/result wrappers or a future report verdict as evidence. Existing
  verifier/check lists remain unchanged. Fifty-one focused tests and Ruff pass;
  the current instruction update is installed; full live acceptance is separate.
- Actual retained0015-copy migration-only qualification passes on `6c98e83`:
  two existing `ensure_migrated()` calls preserve old data/catalog/PM history,
  add only four identity tables and reach0019; outer cleanup is verified.
  Full retry host module39 plus11 adjacent cases pass with scoped Ruff/mypy.
  `init_db()` seeding failures remain retained; image/install, full gates,
  authenticated PM HTTP and live owner-confirmed Backlog/Ready remain open.
- PM terminal resume retry preserves the single trusted observation's null or
  exact inherited source checkpoint marker without treating it as own progress.
  The populated0018 upgrade plus six affected PostgreSQL cases pass on `6c98e83`
  (7/7, cleanup verified); foreign markers and genuine rebound targets remain
  rejected. Full gates, Fleet transactional recovery and live PM acceptance
  remain open; the earlier PG7 keeps its historical scope.
- The normal migration entrypoint accepts0018 as the predecessor of0019.
  Seven actual PostgreSQL retry/migration/concurrency tests pass, including
  retained receipts, rollback refusal and observed row-lock waits. These
  source checks do not claim an installed or live PM business result.
- Documented the opt-in PM terminal resume retry V1 command, distinct receipt,
  scoped readback and additive migration 0019. Source/SQLite and reported Fleet
  golden verification are separated from open PostgreSQL/deployment/live gates;
  retained operation history is never deleted to permit downgrade.
- PM Draft assignments accept the actual Tracker reservation and input snapshot
  without inventing future queue/workspace refs. Additive migration 0009 preserves
  existing assignment history; bind keeps the original agent and generic steps,
  replacement and rebind cannot bypass verified PM enrollment.
- Namespace/workflow context sits beside account on the right; compact sidebar
  applies the Base SSR scope and shrinks with its labels and content offset.
- Mobile service menu stays inside the viewport; namespace selection and history
  update both desktop and drawer selectors.
- Header matches the Base product/service/context/account order; page actions
  leave the global header. Account menu consumes the pinned Base SSR theme
  primitive and synchronizes the browser preference with React products.
- Standalone Compose forwards optional `AUTH_*` settings without changing the empty-issuer default; Central Auth SSO has a documented deployment matrix, container-reachability requirement and browser acceptance path.
- Documentation audit is clean: README has an H1; runtime/auth, quality, reset and historical plans have cross-links and explicit security/runtime boundaries.
- Added regression coverage that proves an empty `AUTH_ISSUER` leaves UI/API open in standalone mode.
- Standalone-режим: репозиторий собирается и запускается без соседнего `services-base` (убраны extra `cli-platform`, uv source, Docker additional_context и CI checkout). Token-режим CLI без `sdlc-cli-core` выдаёт понятную ошибку; запуск без `AUTH_ISSUER` работает без авторизации.

### Fixed
- Machine namespace authorization accepts Base's optional `display_name`
  introspection metadata while preserving required identity/grants, registered
  subjects and rejection of unknown claims.
- Phase saves bind returned check/evidence IDs to the submitted rows, even when
  the list changes during the request. A temporarily blank saved row is not
  silently deleted by saving another field. Health SQL runs in FastAPI's thread
  pool so a slow probe does not stall unrelated requests.
- Legacy v2 runtime steps consume saved instruction/check/evidence text from the
  database; readiness validates the saved phase graph, role ownership and skill
  limits. Valid reordering, parallel execution and added phases do not disable
  the role merely because the graph differs from the seed catalog.
- Runtime discovery ignores presentation changes and unrelated workflows;
  readiness checks the calling managed role. Synchronous human API and HTML
  routes use FastAPI's thread pool. Rejected instruction saves retain entered text.
- Installed catalogs allow normal phase, instruction, agent and namespace edits.
  Saving and reopening retain the new values; startup and migration reruns keep
  saved edits. Packaged executor compatibility is checked at the runtime API,
  independently of editor availability.
- Base binding OpenAPI keeps its published 422 description independent of the
  Python standard library status phrase; validation status and DTO are unchanged.
- Index PM operation history by execution and kind so checkpoint uniqueness
  checks do not scan other executions while holding the task lock. Keep the
  ORM and pending PM migration schema in sync.

- Namespace owner verification bounds streamed responses and the complete
  command with a total deadline, sharing one request-owned HTTP pool.
- Immutable image builder закрепляет Git EOL-настройки только для archive:
  один commit даёт одинаковые source/bundle digests независимо от пользовательских
  `core.autocrlf` и `core.eol`; явные repository EOL rules и binary bytes сохранены.
- Central-mode SSO session, OIDC transaction and namespace selector cookies are scoped to the configured public issuer and Workflow origin, preventing collisions between local ports. Middleware retains its installation-time settings; logout clears only its own session and pending transaction with the configured cookie attributes. Standalone mode and machine-token APIs are unchanged; legacy central-mode cookies require a fresh SSO redirect.
- Task detail partial-verdict использует читаемый основной текст, сохраняя жёлтые фон и рамку: summary и activity badges проходят контраст светлой темы без изменения других verdict-типов (#93).
- Заблокированный статус и список блокеров на task detail используют читаемые цвета текста во всех темах; красные фон и рамки сохранены, включая рамку статуса (#94).
- Номера фаз на task detail читаются как «Фаза N» без недопустимого `aria-label` на generic spans; последовательные и параллельные карточки сохраняют компактные индикаторы.
- SSR-переключатель берёт текущий Workflow и его health из runtime-каталога,
  без hardcoded healthy. Полный fallback из шести UI остаётся unknown при
  сетевой ошибке, пустом или невалидном ответе; TTL cache разделён по URL.
- Immutable image builder передаёт PAX-first tar через deterministic gzip;
  Docker распознаёт stdin как context, а не Dockerfile. Source/bundle digests
  и manifest contract не меняются.
- SQLite migration test закрывает UoW и гарантированно освобождает собственный
  engine; строгий ResourceWarning gate не зависит от момента garbage collection.
- Меню сервисов не перекрывается sidebar и помещается на низком экране;
  локальные переходы сохраняют канонический `localhost` для общей SSO-сессии.
- Standalone Compose получает runtime-каталог через `host.docker.internal`,
  а пример `.env` больше не подменяет этот адрес контейнерным `localhost`.
- Workflow shell синхронизирован с документированным контрактом: header 60 px,
  desktop sidebar 264 px, tablet rail 72 px и mobile drawer только ниже 768 px.
- Workflow shell доступен с touch и клавиатуры (#49); улучшены phase controls и accessibility (#48).
### Added
- Central SSO и token-mode CLI transport (`feat/central-sso-cli`, #43): browser-сессии central auth и personal tokens как транспорт CLI.
- Hosted CI (quality + compose-readiness) на каждый push/PR.

### Changed
- UI `/phases`: длинные цепочки открываются компактным списком с переключением на схему; единственный воркфлоу больше не дублируется в навигации.
- UI `/phases`: быстрый переход к фазе в длинном списке с фокусом на выбранной фазе; иконки пространства в header сохраняют цель 40 px.
- UI: улучшен контраст dark brand subtitle (#44).

### Removed
- Мобильные галереи и auth-скриншоты из README — desktop-only evidence standard.
- Explicit Base control-plane image variant закрепляет private Base package
  и candidate 7/11/33 без подключения legacy execution bridge. Default каталог
  прежних installations остаётся неизменным; автономное исполнение не включено.
