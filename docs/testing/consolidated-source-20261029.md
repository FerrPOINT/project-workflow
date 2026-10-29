# Workflow PR152: Source Consolidation

This qualification concerns source integration, not deployment or new live acceptance.
The starting point is PR152 `dd88002b17ba3133db61cc3866f9702fa5017554`;
the integrated master is `b57ae791fffdf4fa694cc6b918f8c703c8b2a797`.
No additional UI PR head is integrated. Fleet/Base release work belongs to the main integrator.

## PR148 And Conflicts

PR148 `f130760443b3e01959fcfa302085536259310c78` has one commit absent
from the PR152 baseline. Its useful change tells PM to continue accepted phases
inside the same execution, waiting only for missing input or required owner consent.
That guidance now appears in configured CLI reads and persisted nonterminal report
responses. Tests check the unchanged execution reference and the actual returned
instructions. The retired `configured_cli_instructions.py` layer is not restored.

The current sealed catalog/manifest remain byte-identical to the baseline:
`7bc022089b08b246fbb04fb03fa374940cc4a6c0a023bc1e310e260e4f04f67e` /
`e0cde0c044fe1a38b6fa0f387cc30e0da6e89dedb35b89a893263fd7d2558a40`.
No migration, catalog replacement or runtime installation is part of this change.

Base can retain CLI source pin `dd88002b17ba3133db61cc3866f9702fa5017554`.
The `project_workflow/interfaces/cli` tree is unchanged:
`d74565d75550b5cbc8a4445bdd2823e881467042`.
The configured CLI domain contract, exported platform namespace, `pyproject.toml`,
`uv.lock` and `constraints.txt` are also unchanged. This is a CLI subtree comparison,
not a claim that the whole backend package has identical bytes.

Nine files had textual merge conflicts:

- `README.md`: keep the configured entrypoint and the current verdict names.
- `project_workflow/infrastructure/llm.py`: keep master removal of backtracking
  and PR152 phase/business-outcome distinctions; add the targeted evaluator rules below.
- `project_workflow/interfaces/ui/templates/base.html`: keep external controllers
  and the safe default for missing administration context.
- `project_workflow/interfaces/ui/templates/workflows.html`: keep master card
  actions/controller loading and PR152 read-only protection for the historical PM catalog.
- `tests/test_llm.py` and `tests/test_supervisor_reliability.py`: agree on prompt v10.
- `tests/test_phase_draft_protection.py`: use the external controller and one page stub.
- `tests/test_postgres_integration.py`: retain useful master changes without
  restoring tests importing retired native/callback executors.
- `tests/test_ui.py`: inspect external assets and preserve configured behavior;
  repair the merged handler assertion's undefined variable.

The PM read-only guards were also transferred into the external workflow controller.
Effective phase/instruction reads now use the existing `page.ready` and scoped fetch,
so partial navigation does not wait for an already-fired `DOMContentLoaded` event.

## Findings And Prospective Fixes

The original [direct PM result](direct-cli-20261029.md) remains accepted for SDLC-5
only. The [strict attempt](strict-user-request-20261029.md) remains WAIT with its
recorded independent-check failures. Neither historical document nor frozen evidence
was edited or reclassified.

| Recorded defect | Source change | Regression boundary |
| --- | --- | --- |
| Advisor invents JSON content inside SUMMARY | Prompt v10 respects the destination explicitly required by the phase | Prompt contract test; no claim of a fresh live-model verdict |
| Advisor rejects the encoding-only `-X utf8` flag | Prompt accepts equivalent required behavior, retaining execution/output obligations and explicit exact-command contracts | Prompt contract test; failed or different tests still cannot count as success |
| Advisor says evidence is absent while marking it covered | Prompt requires the whole item and consistent message/coverage | Prompt contract test; saved model decisions are not rewritten |
| Snapshot rejects Python-created `__pycache__` | Record bounded regular bytecode files with their paths, kind and SHA-256, tied to existing source files | Real `py_compile` cache; unexpected entries still fail |
| Oracle rejects pure `type` / `ValueError` validation | Add these restricted builtins; `type` is limited to one-argument validation | Six independent vectors, incorrect arithmetic and forbidden-call negative cases |
| Prompt upgrade rejects previously accepted terminal proof | Validate frozen v9 and v8-no-backtracking proofs against their own saved version and hashes | Actual readback/replay and unchanged ledger snapshots; unknown versions still fail |
| Master verdict removal rejects historical rollback in Fleet summaries | Allow the saved rollback value only in history projection, not active evaluation | Existing summary/privacy/pagination tests and seeded PostgreSQL readback; full history remains byte-identical |

The two harness failures were reproduced by new regressions before the harness fix.
`checks.py` now exercises the current CLI oracle; historical engine-diagnostic
`run.py` is unchanged. No old attempt is rerun against modified criteria.

## Qualification

Python 3.13.13 uses all exact versions from `constraints.txt`; supplementary
Playwright is pinned to 1.63.0 and Base CLI core to source
`278be4a2eb0b3ce49dac2cd14ea7e2871f2ffe1d`. Dependencies came from the existing
local cache. The sibling prepared environments and sources were not modified.

Evidence is local to this checkout under `.local/consolidation-20261029/`.
The first full attempt was interrupted before completion to prepare the missing
qualified CLI/browser dependencies. The next attempt timed out inside system
Git's `git init` in repository-hygiene tests. Neither attempt is a PASS.
With bundled Git 2.53.0 first in PATH, the independent eight-case hygiene suite passes.
Intermediate full runs exposed stale inline-controller and retired-transition tests;
they were adapted to execute the actual public JS assets and real response parser.
The first sharded attempt also placed generic TEMP beneath the Git checkout,
invalidating a nonrepository hygiene fixture, and failed scratch cleanup on read-only
Git objects. That attempt is not a PASS. The final runner uses external TEMP and
the standard temporary-directory cleanup. Historical failed logs are retained.

Completed checks before the final full gate:

- Targeted integration tests: 434 passed, 11 skipped before Python Playwright was available.
- Frozen-proof/profile/prompt follow-up: 60 passed.
- `python -B manual/file-sandbox/checks.py -v`: 10 passed.
- `python -B manual/file-sandbox/cli_checks.py`: 7 passed.
- `python -B manual/file-sandbox/catalog_checks.py`: 4 passed.
- `python -B -m scripts.build_single_task_profile --check`: baseline hashes match.
- `ruff check .`: PASS; `mypy project_workflow scripts`: 160 source files, PASS.
- SDK revision/export checks: PASS on pinned Base `2bb386503eeb009e2238160e88970eae0fab2824`.
- Bundled Playwright 1.62.1/Chromium checks on an owned synthetic loopback fixture:
  partial navigation to phase and instruction editors passes at 1440 and 375 px,
  with no page errors or horizontal overflow. Screenshots were opened and inspected.
  The fixture server was stopped.
- Staged repository hygiene and `git diff --check`: PASS.
- The eight-file final focused attempt had 168 passes and 17 failures in controller
  test fixtures, not a PASS. Corrected theme cases pass; corrected editor cases
  separately pass all 17 cases, including parallel-group insertion and failed-save
  text retention. No production source change was needed for those fixture failures.
- Actual optional PM effective-view browser cases: 11 passed on Edge.
- Seeded configured PostgreSQL suite: 16 passed; the subsequent targeted historical
  rollback summary guard: 1 passed, 16 deselected. Both Compose-v2 journals are
  `cleaned`; containers, networks and volumes were checked absent.

The final non-PostgreSQL suite combines coverage with ResourceWarning and
PytestUnraisableExceptionWarning as errors, using Coverage 7.15.4 `sysmon`.
PostgreSQL uses seeded disposable fixtures, explicit fake external authorities,
the qualified pinned PostgreSQL image, and Base cleanup journal v2. No runtime
database copies, real credentials, installs, live model calls or Hermes executions
are used. At source integration commit `3174df07bb2007da807b12bd4c5461850a960bc9`,
the final non-PG gate was still running. That source commit was published by an
ordinary fast-forward to canonical PR152 before the gate finished.

The same running gate then completed without a restart:

- 3158 selected items across all 166 files, 116 integration items deselected.
- 3157 passed, 1 skipped, 73 subtests passed; zero failures/errors.
- The single skip is the existing Git executable-mode case on NTFS, which cannot
  represent executable bits. It is not a private-source or live acceptance case.
- Combined line coverage: 11346/12069, approximately 94.01%; unchanged 94% gate PASS.
- ResourceWarning and PytestUnraisableExceptionWarning were errors in all four shards.
- Source fingerprint before/after:
  `d25e99d581af8a3696aa4f9bffd660dafa51f1a8b382c908af56dbca51b53723`.
- Evidence: `.local/consolidation-20261029/full-sharded-final/`, including per-shard
  commands/logs/JUnit, combined coverage XML and `result.json`. The runner completed,
  external scratch was cleaned, and no runner/pytest process remains.

Published product source trees at `3174df0`:

- `project_workflow`: `d0f55b90cf543e4642f5ed46a334d4f7ea722ace`.
- `project_workflow/interfaces/ui`: `c02056fcf080ecdfa128ad8d9d1442a66ac0c6af`.
- Protocol `configured-cli-v1`, domain-contract blob:
  `2f08bc71126c1436b342281d0f02dd24c4194d9f`.
- Base UI pin: `2cbd859746393bc867c3cd90cb906a54aa20218e`.

The broader legacy PostgreSQL suite and Compose/image/deployment gates were not
run in this source-only consolidation. The subsequent qualification commit changes
only this report; the published backend/UI/protocol/CLI source trees remain unchanged.

Other professions' live acceptance is not a source-merge requirement added by
this consolidation and remains NOT RUN. The changed evaluator instructions need
a future targeted live check to measure model behavior; unit tests do not establish
that behavior. There is no new claim of complete strict user-request acceptance.
