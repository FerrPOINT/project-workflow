# Changelog

## Advisor: Qualified Results And Remaining Live Acceptance - 2026-11-03

- Final wire inspection found omitted C4 classifications, not injected hashes or
  extra response fields. Strict validation and existing format repair remain intact.
  Removed readiness/self-verdict claims from future PM reporting instructions;
  business facts and the FULL document remain required.
- A separate predeclared factual-report control accepted all three samples in three
  HTTP calls, without format or transport errors (cap five). Parent remains failed/
  incomplete after 21 exact results and a timeout; its unknown upstream outcome is
  not reclassified. Including 15 unchanged phase01/03 results gives 39 exact final
  results across distinct evidence sets, not one 39/39 run. Subsequent ledger:894.
- Clarified existing recovery: unknown acceptance uses original-operation readback;
  valid PARTIAL needs changed facts, while a known retryable technical failure can
  be resubmitted after recovery with a fresh key/current version. No automatic retry.
- Full native PM-v4 suite:3455 passed,75 subtests,15 skips, coverage94.118578%.
  Latest affected suites:78 passed; Ruff and mypy166 pass. Unchanged full-suite
  results are reused, not claimed as a fresh run of the later tests-only changes.
- PostgreSQL:128 preceding cases passed; the corrected admission block passed5/5,
  covering the failed case and all three previously unrun cases. The test now
  reaches the SQL guard and waits for its original database deadline as well as
  the host deadline. SQLSTATE42501, real row-lock wait and unchanged data remain
  mandatory. No application/migration change; all owned QA resources cleaned.
- Limited QA installation can test these final results with the existing native
  protocol. The stricter historical zero-invalid-raw/zero-transport criterion is
  not met and is not silently waived for release. Installation, two autonomous PM
  scenarios and merge remain unaccepted; high settings are still QA-only.

## Advisor: Actual Wire Payload Recheck - 2026-11-03

- Inspected 25 saved HTTP prompts of candidate 3ad48803, including native format
  repairs: no 32–64-character hex values or UUIDs. Diagnostic hashes and expected
  labels are not model input. This does not describe arbitrary reports or deployed v12.
- All 24 returned objects contain only the existing six fields. Three omit C4;
  native format repair recovered them. Removing FULL duplication from E1 did not
  eliminate these omissions; their sole cause is not established.
- 21 completed evaluations match the prospective labels. A subsequent ReadTimeout
  leaves qualification incomplete, with two unrun slots and unknown upstream outcome.
  No new inference, installation, configuration activation or live acceptance.
- Added actual HTTP-payload regressions for all three catalog phases: only system
  and user messages, one report and each criterion once, no worker instructions,
  credentials or diagnostic metadata. 25 prompt tests and Ruff PASS.

## PM: Source Evidence Versus Readiness - 2026-11-03

- PM-DRAFT-02 E2 now asks for an account of owner decisions and unanswered
  material questions. It no longer independently demands all answers be obtained
  or a separate resolution narrative; unchanged C1/C2/C3 still require agreement,
  consistent requirements and resolved material decisions. Counts and API stay fixed.
- This is an intentional prospective evidence-contract change, not literal
  equivalence or retrospective scoring. Honest pending input may cover E2 while
  C2/C3 remain missing. The existing worker reporting instruction is preserved.
-22 focused tests PASS after integration. A controlled-provider runtime submission
  plus actual CLI readback verifies that E2 coverage does not complete preparation
  when C2/C3 are missing. This does not prove model recognition or live PM readiness.
- Previous high trial:30 evaluations/32 HTTP,26 exact, all verdicts correct;
  two malformed responses recovered. Old E2 revision:15/15 HTTP,12 exact,
  all verdicts correct. Both remain failed qualifications, unchanged. The stage
  ended at47/48 HTTP; subsequent ledger843. High was QA-only, not activated.
- New contract qualification is prepared with independently reviewable expectations,
  including a complete document with an expressly omitted owner account. No build,
  publication, configuration activation or installation; live acceptance remains open.

## Advisor Documentation Boundary - 2026-11-03

- Corrected the diagnostics guide's stale PM-v2 lead: the current source is
  PM-v4 without the abandoned server-confirmation context block. Kept v2 as
  historical, not an activation instruction. Installed generic v12 and the
  unaccepted source candidate remain explicitly distinct; no runtime change.

## Advisor: Compact Rubric Experiment - 2026-11-02

- Tested prospective criteria only, not a production/publication change. Same
  eight reports/goldens, v4 system, model and medium settings; three rounds each.
- Consolidation alone:24 HTTP/24 evaluations,13 exact,0 false PASS,5 false PARTIAL.
  Raw answers read 'available answers' as required choices and confused supplied
  evidence with readiness. The variant is rejected, not installed.
- Evidence-only clarification:24 HTTP/24 evaluations,22 exact,0 false PASS/PARTIAL.
  All9 positives pass and all15 negatives are rejected. Two extra evidence flags
  remain: an unsupported original-request demand, and an ambiguous demand for
  explicit approval status. Frozen labels and all answers remain unchanged.
- Both runs terminal;48 cumulative HTTP,0 malformed/recovery/error/unknown.
  Subsequent ledger796. No cardinality-validator change, parser relaxation,
  configuration activation, build, installation or live acceptance. Passing
  verdicts do not erase incorrect item feedback; qualification remains open.

## Advisor Payload Recheck - 2026-11-02

- Read-only inspection of26 saved actual HTTP prompts found no hex hashes,
  UUIDs, credentials, bootstrap or log blocks; diagnostics are stored separately.
  This describes the candidate fixtures, not the installed v12 or arbitrary reports.
- Confirmed phase02 FULL-presence duplication (C4/E1) and overlapping owner-input
  criteria (C1/C3/E2). One raw answer acknowledges FULL but marks C4 missing;
  the parser did not introduce that contradiction. Duplicate criteria are not
  established as the sole cause of all model errors.
- Six model-output fields are distinct from the enriched server/CLI response;
  confidence is not used for acceptance. No new filter, response schema, model
  calls, build or stand mutation. Compact criteria remain unqualified; live
  acceptance and release remain open.

## PM Advisor: Separate Content, Review And Blockers - 2026-11-02

- Cause: PM-v3 allowed ordinary pending owner input to be both PARTIAL and
  BLOCKED. PM-v4 changes only those two definitions: unfinished phase work,
  including obtaining an owner decision, is PARTIAL; BLOCKED requires an
  obstacle to performing that work. No PASS rule or criterion is weakened.
- Generic v12 and the six-field parser are unchanged. Input still contains only
  phase, criteria and the current report. Frozen PM-v3 receipts remain accepted
  alongside v1/v2, without regrading or provider calls.
- The catalog proposal now separates observable business acceptance outcomes
  from owner consent, and completed presentation of the latest saved FULL text
  from subsequent feedback. Same phases/counts/commands; no field-label exceptions.
- Verification:40 focused prompt/server/history tests PASS; Ruff and mypy166
  PASS. A source digest regression proves no other PM-system wording changed.
  Final catalog publication/CLI checks:20 PASS, targeted Ruff PASS. These are
  targeted checks, not a new full repository gate.
- Fixed trial:9 evaluations/9 HTTP,8 exact,0 malformed/unknown/false PASS.
  Realistic fictional API failure:BLOCKED3/3; ordinary owner choice:PARTIAL3/3.
  Complete163:PASS2/3. The remaining C5 refusal treats the field label
  'brief description' as a required length constraint; two independent reviews
  found no such input-validation rule in the report.
- Subsequent frozen C5 and C1 trials retained every report/golden. Final medium
  phase03 trial:9/9 exact in9 HTTP,0 malformed/false PASS; vague acceptance and
  pending-owner controls remain rejected. Earlier intermediate trials stay8/9.
- Same final input under installed none:9 HTTP,5 valid-JSON responses omit C5,
  4 completed evaluations/3 exact,1 terminal contract error,4 unrun slots.
  Existing strict recovery stopped normally; no invalid response was promoted.
  This is not evidence that unrun positives failed. Installed settings unchanged.
- Cycle used46 of its48 HTTP limit; no further calls. All700 subsequent calls
  remain preserved separately from the original48. No build, publication or install.
- Consolidation is not a text-only change: catalog publication preserves counts
  and requires evidence. Structural catalog work is deferred, not added as a PM
  release prerequisite. No validator, baseline or parser is relaxed.
- Remaining cases:15 evaluations/17 HTTP, all verdicts correct,13 exact item
  partitions. Complete170/171 pass3/3 each; missing FULL and content contradiction
  are rejected3/3 each. The residual defect is extra missing flags on a rejected
  contradictory report, not an inability to run Hermes or save requirements.
- A three-item phase02 wording revision and a private comparison-direction
  sentence failed full item qualification:12/15 and13/15 exact respectively.
  Neither is retained: the rubric revision was reverted, private v5 never entered
  product code. All old reports, goldens and raw responses remain preserved.
- This stage ended at48 HTTP/45 evaluations;0 false PASS or false PARTIAL,
  3 contract-invalid responses recovered,0 terminal/unknown outcomes. Different inputs
  are not pooled as a general accuracy score. Subsequent HTTP ledger total748.
- Integrated current master UI pin; pinned Base/namespace checks PASS, restored
  catalog target tests20 PASS. No image build, config activation or installation.
- The earlier plan froze criterion counts. A user decision is requested before
  permitting compact criteria through the existing publication validator. No
  structural change, parser relaxation or further calls are applied meanwhile.
  Full final gates and two live Backlog / Ready scenarios remain open.

## PM Advisor: Semantic Input Candidate - 2026-11-02

- Cause: the PM contract mixed business review with identity/receipt attestation.
  Phase02 also mixed current FULL-content checks with future procedure, while
  some source wording was interpreted as requiring original owner messages.
- Implemented candidate PM-v3: system1390; only phase, allowed verdicts,
  criteria and current report. Removed TASK/count-formula/revision-context blocks.
  No hash table, aliases, decoder, generic text stripper or new effort setting.
  Exact assignment/owner/requirements/consent guards remain server-side.
- Added the reproducible business-only catalog proposal. Phase02 now separates
  reported-request agreement, unambiguous rules, resolved owner input and current
  FULL presence. A readable source summary is sufficient; the document stays FULL.
  Existing phases, counts, CLI commands, six response fields and history remain.
- Code verification:3445 passed,15 skips,132 PG deselected,75 subtests;
  coverage94.118578% on frozen tree18b12d5. Subsequent changes affect only the
  catalog artifact/tests;20 targeted publication/actual-CLI checks pass. The final
  combined prompt/catalog regression run has41 PASS; targeted Ruff also passes. Runtime
  Python is byte-identical. PostgreSQL132 pass,0 skips on final staged treedccd136;
  dedicated clock DB supplied, v2-owned container/network/volume cleaned.
  Ruff and mypy166 pass. Skips:11 missing Playwright,1 NTFS executable-mode
  limitation,3 private-package opt-ins; none is counted as verified. No image
  build, installation or live acceptance.
- Model evidence: the existing native format-recovery path was checked without
  adding retries. Current nine cases,27 evaluations: none produced13 exact/6
  positive non-PASS in31 HTTP; medium produced18 exact/4 positive non-PASS in28
  HTTP. Both had0 negative PASS. Medium had1 malformed response, recovered once,
  no terminal errors or unknown outcomes. Neither meets the frozen acceptance.
  The medium experiment changed only the existing request parameter, not the
  installed configuration. A separate longer-system variant was rejected.
- Independent review found that search matching is genuinely unspecified in
  case170: its three medium refusals are not established model errors. Frozen
  scores stay unchanged; the materiality boundary needs clarification before
  another experiment. Do not tune toward an unexamined positive golden.
- All654 subsequent HTTP calls are retained separately from the original48;
  different inputs/settings are not pooled as a quality score. No further
  wording/parameter sweep, build or installation is justified by these results.
  Next: settle the concrete business-readiness criteria, not add model context.
  Catalog publication, installation, two live scenarios and merge remain open.

## Advisor Responsibility Boundary: Business Report Only - 2026-11-02

- Confirmed: PM system, catalog checks/evidence and raw reports still ask the
  advisor to compare machine identities. Removing values alone would leave
  impossible criteria and recreate missing-evidence refusals.
- Removed the uncommitted display experiment, decoder and PM-only effort setting.
  No table/alias replacement or generic hash/UUID stripper is accepted. Preserved
  all private evidence: latest24+30 calls bring the subsequent total to513;
  neither display variant qualifies the newly requested metadata-free boundary.
- The experimental full unit/coverage run was interrupted, not passed. No new
  model calls, catalog publication, build or stand mutation in this recheck.
- Next minimal fix: align PM prompt and catalog instructions/checks/evidence on
  semantic phase readiness. Reports retain FULL business content, not CLI/receipt
  dumps. Exact assignment/owner/revision/consent checks stay in server code.
  Keep the existing six-field response/parser and frozen history. No new layers.
- Not yet installed or live accepted. See the current boundary section of
  docs/ADVISOR_DIAGNOSIS_20261101.md; earlier sections remain historical evidence.

## Actual PM Source Qualification: Rejected - 2026-11-02

- Cause: private SYS1095 trials did not qualify source PM-v2/SYS2000. Independent
  review also found that published10 evidence requires correct identities, not
  presence-only fields. Do not rewrite the catalog to force one missing item.
- Changed QA input, not production: actual source builder/system and unchanged
  catalog10/raw reports,8 cases/3 rounds. Captured164/170/171 IDs/delegate and
  complete generic requests are reproduced before applying the PM policy;
  phase03 remains explicitly reconstructed, not an exact historical HTTP capture.
- Prospective C4 for133/receipt-negative is covered because the source now supplies
  genuine latest owner consent. Identity contradictions still require PARTIAL;
  old goldens/results are preserved. Both independent reviewers agree.
- Result:24 valid,14 exact,1 false PASS133,5 false PARTIAL170/171,21 item
  disagreements,0 format errors. Candidate rejected; no catalog/source change,
  build, installation or live acceptance. Total459 post-comparison calls retained.
- 59 targeted source tests PASS. Do not repeat the tested sufficiency-only wording:
  it already failed, and v12 had that rule but still rejected these reports.
  Next fix must address evidence interpretation and opaque identity comparison
  without bypassing negative checks or adding a prose parser/another verifier.

## Advisor Causal And Context Recheck - 2026-11-02

- Current finding: removing worker procedure and stale PM coverage fixes input
  defects; forwarding existing verified consent fixes missing server context.
  These changes do not establish model quality. Further wording experiments
  partly compensated overlapping evidence/identity obligations instead of
  resolving their contract. No new model calls, builds or installation in this audit.
- Four captured installed-v12 requests contain only system/user, not full chat
  history, SOUL, skills, logs or diagnostic snapshots. None is truncated;
  each has one successful response identical to the saved server decision.
  Worker procedure contributes1693/2068 unnecessary characters to these inputs.
- Keep installed v12, source PM-v2/SYS2000 and private SYS1095/display experiments
  distinct. HEXREF legends are private experiments, not product input formatting.
  Source PM-v2 model qualification and two live PM acceptances remain open.
- Retained server-fact trial:18 valid,16 exact,1 false PARTIAL,2 item disagreements.
  Subsequent confirmation-fields trial:18 valid, all18 verdicts agree,9 item
  disagreements. Some concern ambiguous overlapping obligations, not established
  model errors. Neither trial qualifies the actual source SYS2000. Total435
  post-comparison calls retained; no unrun/unknown slots counted as results.
- Next: settle the existing criteria's responsibility boundaries before another
  experiment. Preserve server consent/version checks and report contradictions;
  do not add aliases, exceptions, automatic PASS or a second verifier.

## PM Context Candidate: Use Existing Server Evidence - 2026-11-02

- Cause: final configured PM already verifies actual Tracker owner confirmation,
  but the advisor previously received only the worker's account of it. The last
  one-C1 correction still had a false163 refusal demanding the actual receipt.
- Implemented, NOT installed/accepted: PM policy v2 forwards only the already
  verified requirements revision as an explicit server fact. No new API, read,
  credential, response field or authority; content/presentation/report conflicts
  and all existing server checks remain required. Other roles/preparation unchanged.
- Old PM-v1 frozen proof remains readable/replayable. No provider call on replay.
- Targeted checks:136 PASS on the pinned interpreter; Ruff all
  and mypy166 files PASS. Controlled providers prove wiring/guards, not model quality.
- Last presentation-only experiment:18 valid, exact16,1 false PARTIAL and1
  negative-item ambiguity; no false PASS. Total399 post-comparison calls retained.
- Next: freeze a comparison adding only the actual server-confirmation fact to
  preserved cases. Qualification, installation and two live PM tasks remain open.
  Default PM system2000, generic v12, Hermes/model/credentials/stand unchanged.

## Goal Iteration: Separate Authority From Report Consistency - 2026-11-02

- Verified cause: server reads the actual latest requirements/owner confirmation,
  compares final CLI revision/hash and rechecks before commit. It does NOT parse
  arbitrary hashes copied inside report prose. Removing every consistency check
  would preserve consent authority, not rejection of contradictory reports.
- Prospective explicit-current-document criteria:30 valid calls, plain exact11/15,
  display10/15; plain has1 false PASS. Rejected, no catalog publication.
- Same plain inputs with only requested effort=medium:15 valid, exact12/15,
 2 false PASS. All15 report reasoning tokens, but quality still fails. No activation
  or higher-effort sweep.
- Atomic-v1:36 valid calls; plain exact11/18 with2 false PASS, display exact10/18
  with0 false PASS/PARTIAL but10 item disagreements. Not accepted or published.
- Evidence-presence scope clarification, same six reports and unchanged prospective
  goldens:18 valid display calls, exact14; all9 negatives rejected, but1 positive
  falsely rejected for an invented separate presentation record. Rejected too.
- Total381 post-comparison calls; all responses retained, no technical retries.
 29 targeted server authority/terminal checks and14 documentation tests PASS.
- Next: remove the introduced independent-presentation-record burden, not add an
  artifact or bypass judging. Review negative item ambiguities separately. No
  further calls are scheduled in this iteration; no unqualified text is activated.
  Historical v2 labels/results remain unchanged. No new build/install or stand change.
- Installed93c14f8/PM23/catalog10 remain unchanged. Two new autonomous live PM
  acceptance scenarios and release gates remain open.

## Goal Iteration: Reference Comparison Versus Criterion Meaning - 2026-11-02

- Shared short1095 system, none/low:42 of48 planned calls,41 valid. First
  inconsistent_pass is atomically recorded as aborted;6 slots not executed.
  Valid false PASS: none1/21, low2/20. Neither policy is accepted or installed.
- Lossless reference display,30 paired calls: contradictory133 changes from
  false PASS3/3 to expected PARTIAL3/3. All9 positive replies per arm remain PASS,
  including repaired-hash and legitimately older-revision controls. But exact
  item matching remains9/15 per arm; wrong labels18->11. No product formatter added.
- Explicit independent-item instruction:15 valid, exact9, wrong items9; not retained.
  Facts-first existing-six-field policy stops after6/30 calls on an omitted ID.
  Actual message-first order is observed6/6, but it does not establish correctness.
- Public explanations expose inconsistent referents for current document versus
  presentation/confirmation and partial reading of compound checks. Next:
  independent contract-clarity review preserving all business guarantees, not
  post-hoc golden changes or another generic strictness instruction.
- Preserved282 post-comparison calls, including all rejected replies and aborted
  runs. Hermes/model/credentials/catalog/stand and product3d84a60 remain unchanged.
  No new build/install or live PM completion is claimed. Detailed manifests,
  counts and limits are in docs/ADVISOR_DIAGNOSIS_20261101.md.

## Goal Iteration: Reasoning Parameter Is Not A Complete Fix - 2026-11-02

- Preserved source requests send reasoning_effort=none. Tested exactly this
  request parameter against low, on unchanged original product PMv1 system and
  all eight reports/items/goldens. Model/endpoint/credentials and live config
  remain unchanged. Predeclared48 calls, alternating paired order, no retries.
- All48 responses are valid HTTP200/stop. none: exact12/24, false PASS1,
  false PARTIAL6,21 wrong items. low: exact10/24, false PASS0, false PARTIAL5,
 23 wrong items. Neither arm passes; low is not activated.
- API usage reports nonzero reasoning tokens in5/24 low replies versus0/24 none.
  This does not establish a particular upstream backend or single internal cause.
  The short936 system combined with low has not been tested; do not transfer
  results across prompts or claim none alone causes the failures.
- Harness review found a crash/resume window after an error-slot checkpoint.
  This run had no errors, interruption or resume. Preserve the frozen runner;
  future reuse must atomically persist abort and reject an error state.
- Current post-comparison total:189 bounded calls,0 accepted candidates,0 stand
  changes. Both live PM acceptance scenarios and release remain open. Next:
  preregister the missing short-prompt/effort comparison, changing only effort
  on one fixed short prompt. No new rules, reports or criteria in that comparison.

## Goal Iterations: Reject Unsafe Framings - 2026-11-02

- Cause: preserved inputs contain the FULL documents and identity/readback facts,
  but advisor still demands extra provenance; other replies overlook contradictory
  hashes or cover a compound criterion after checking only part of it.
- Completed141 bounded offline calls after the original48 comparison. Trials:
  sufficiency24, preparation contract9, role wording24, example order24,
  readback representation12, criterion-only24, clause/identity validation24.
  All responses and prior goldens are
  retained; no format errors. None meets the full positive/negative item-wise gate.
- Criterion-only936-character system accepts all12 positive replies, but falsely
  accepts contradictory133 twice; exact15/24,21 wrong item labels. It is rejected,
  not installed. A full readback JSON also fails to remove extra proof demands;
  do not add a reporting burden or another provenance layer to PM.
- Final bounded candidate: same eight reports and goldens,24 calls, a general
  clause/content/exact-identity rule and explicit existing verdict boundaries.
  Exact17/24, false PASS3, false PARTIAL1,21 wrong item labels. It is rejected too:
  requesting character-for-character comparison does not reliably perform it.
  This whole-system trial does not isolate causality of one sentence.
- Next: inspect exact reference lengths, occurrences and line escaping without
  model calls. Do not repeat another strictness rewording or install a failed
  policy; establish one discriminating input/comparison experiment first.
- Read-only reference audit completed: seven reports have normal newlines; the
  absent-context control is intentionally single-line. None has literal escaped
  newlines.133 has64/50-character values sharing32 initial characters;
  they are different and not prefix abbreviations. The mismatching receipt control
  differs at its first character. These facts do not prove a model-internal cause.
  Next question: can a lossless explicit representation of opaque-value equality
  remove this comparison error without changing facts or criteria? No new model
  calls or product normalization are yet accepted for that hypothesis.
- Product3d84a60, runtime93c14f8, catalog10, PM23, Hermes/model/credentials remain
  unchanged. No new image, installation or live PM acceptance is claimed.
  Details and immutable input hashes: docs/ADVISOR_DIAGNOSIS_20261101.md.

## Goal Iteration: Evidence Sufficiency - 2026-11-02

- Hypothesis: global commands/readbacks wording may override the individual
  criterion's evidence standard. One system sentence replaced in an offline trial;
  all eight prior users/reports/items/goldens and model settings stayed unchanged.
- Predeclared24 calls completed without retry or format error. Exact14/24;
  false PARTIAL2, but contradictory133 received false PASS1/3.170 passed3/3;
 171 passed1/3. This variant is rejected: fewer refusals do not justify false PASS.
- No product prompt, catalog, runtime, credentials or model change was applied.
  The341 targeted product tests remain evidence for unchanged product3d84a60,
  not quality evidence for this experimental text. Full release remains open.
- Next: inspect phase2 result/evidence wording for ambiguous report sufficiency
  and self-referential readiness; no new layer or case-specific exception.

## Configured PM Policy Candidate - 2026-11-02

- Implemented, not installed: verified configured PM enrollment selects the short
  `supervisor-evaluator-pm-v1` prompt. Worker procedure stays in the CLI, not judge
  input. Other roles and generic calls retain v12 and the existing six-field wire.
- Actual selected system/version are recorded in diagnostics and fingerprints;
  frozen new-policy receipts replay without provider calls. Prior frozen versions
  retain validation. No public API, schema, dependency or Hermes change.
- Final targeted suite on product3d84a60:341 PASS, including prompt, configured
  CLI/authority, frozen receipts, coverage and diagnostic regressions. Ruff and
  mypy166 source files PASS. Full release gates remain open.
- Separate coverage change: PM-DRAFT-02/03 use only current report coverage before
  and after provider calls, including fingerprint and technical-error fallback.
  Phase01/general history reader are unchanged.13 policy/coverage tests PASS,
  including three-attempt format failure. Independent review has no blockers.
- Before any model calls, golden133 C4 is explicitly revised to missing, consistent
  with the receipt-mismatch control: both reports claim exact consent despite a
  contradictory hash. Historical goldens/results remain unchanged.
- Completed fixed comparison on source3d84a60:48/48 client requests,24 per arm,
  all HTTP200/stop, no format errors or false PASS on the tested negatives.
  Candidate exact12/24 versus baseline8/24, but170/171 remain false PARTIAL6/6;
  candidate has22 item-label disagreements against predeclared v2. Not accepted.
- Input audit: system5297->2000 characters; worker procedure removed, reports
  unchanged. Context164 changes from PARTIAL3/3 to PASS3/3. Remaining phase2 refusals
  demand extra readback/provenance despite item-defined sufficiency. No parser,
  transport or truncation cause was found. Global commands/readbacks wording is
  one next hypothesis, not an established internal model cause or accepted fix.
- Harness limitations retained: historical133/153/163 use ordinal reconstruction;
  derived absent-context also omits delegation relative to captured164. No response
  used DELEGATE; missing harness allowlist validation had no observed effect.
  Scores do not establish production quality. No relabelling after responses.
- Do not install or merge this policy: mandatory model gate failed. Full release
  gates, new image, live tasks and browser acceptance are deliberately not claimed.
  Runtime93c14f8, PM23, credentials and catalog10 remain unchanged. No stand changes.

## Advisor Chain Diagnosis - 2026-11-02

- Problem: circular refusals and false covered items were conflated with runtime,
  prompt and model hypotheses. Read-only architecture/context/QA review is complete;
  the detailed result is in `docs/ADVISOR_DIAGNOSIS_20261101.md`.
- Proven: worker procedure enters the judge alongside result criteria; captured
  164/167 require their own future ACK. Historical coverage is not revision/hash
  bound and later missing does not retract covered. This is an input contradiction,
  not a demonstrated cause of the initial refusals with empty prior coverage.
- Check: exact prompt reconstruction and parsing for164/167/170/171; in-memory
  history-reader and parser boundary checks, no database/model/business calls.
  Report170/171 retains owner decisions and FULL documents;153 genuinely lacks
  the current FULL packet.133 has contradictory hashes;163 is a valid historical PASS.
- QA correction: evidence179 in negative B was ambiguously labelled; old goldens
  remain untouched. The prior4/12 exact score is not an unqualified quality metric.
  Positive0/6 PASS and negative6/6 PARTIAL observations remain valid.
- Runtime93c14f8/v12, catalog10 and PM23 are unchanged. Current route discovery
  lists three app-test entries for chatgpt/gpt-6-luna, not historical per-call proof
  or an established cause. New inference calls0/48; builds/installs/publications0.
- Next package: configured PM judge input without worker procedure; independently
  test current-report-only coverage for PM-DRAFT-02/03. Version the contract,
  preserve other roles/legacy/frozen v12 and exact owner guards. Not implemented;
  no semantic guarantee or new PM Backlog / Ready acceptance is claimed.

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
- Diagnostic/security93c14f8/image bdfb02159989 is installed through normal
  Workflow-only Applydaced4eb. Health/schema/catalog pass; PM23, original Hermes,
  Fleet, credentials and catalog10 are unchanged. History171 reads identically
  before/after installation.
- Final93c14f8:3319 tests and73 subtests PASS,15 explicit skips,
  coverage94.08269961977186%;132 real PostgreSQL tests PASS. Owned scratch and
  Compose resources cleaned. Exact-image fresh-DB smoke and independent review pass.
- Sparse baseline SDLC-25 asks useful questions, saves requirements1 and2 after
  ordinary feedback, presents the document and reads exact owner confirmation.
  Stale revision1 returns409; initial replay preserves all5 runs and bindings.
  It remains Draft/InProgress after unsupported phase2 PARTIAL170/171.
  Corrected-report409 is proven same-key/different-report-and-version rejection,
  not a reason to weaken idempotency. CLI currently exposes only a generic409.
- Two separately bounded text trials are not accepted: context instruction5-only
  gives5/6 positive PASS and6/6 correct negative PARTIAL (11/12 exact); preparation
  evidence clarification gives0/6 positive PASS,6/6 negative PARTIAL but4/12 exact
  item classifications. All outcomes retained; no publication, rebind or retry to PASS.
- Next: resolve the demonstrated semantic grading gap before further PM acceptance.
  No more unchanged builds or broad replay are required for the recorded failures.

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
