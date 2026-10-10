# PM continuation verification

This record describes the current Workflow candidate and its acceptance boundary.
The protocol is defined in [PM continuation contract](pm-continuation-contract.md),
[Namespace ownership](pm-namespace-ownership.md), and
[runtime assignment contract](runtime-assignment-contract.md).

## Source qualification

Workflow runtime source `f197ed7de675ef8a65d09a336a7159387384fad5` includes
Namespace context changes from Workflow #99. The later documentation cleanup
changes no application, migration, dependency, or image recipe input.

| Check | Result |
| --- | --- |
| Full unit suite with strict resource warnings | 2506 passed, 4 optional private-package skips |
| Coverage | 94.41%; required floor 94% |
| PostgreSQL 16 integration | 80 passed |
| Ruff | Passed |
| mypy | Passed, 120 source files |
| Isolated authoring UI | Instruction save/reload and reorder/reload passed in Codex in-app browser |

Ordinary phase, instruction, check and evidence edits persist through the editor.
Runtime validation checks the graph, role and available skills; it does not
require edited text to match the seed catalog. Editing requires no new execution
version. Original assignment identities and accepted history remain protected.

Migrations are additive: `0007_resource_execution_contexts`,
`0008_pm_execution`, then `0009_pm_draft_assignment`. Previously applied
migration bytes and skills pins are unchanged. Populated upgrade and restart
cases are included in the PostgreSQL gate.

## Native PM acceptance

The isolated QA roundtrip used canonical Workflow source above, merged Fleet
`91f64808e303c90a0d819bfdb70940b8d7133da2`, Tracker
`503f064e4f5adc530ec3418b6f237757c24571c4`, and compiler SDK
`913370b487ceadd408f975ea7f8ca96bfcb99484`. The Fleet UI-only follow-up changes
neither its backend nor embedded runtime inputs.

Verified sequence:

1. Actual native Hermes produces a question and checkpoint for requirements 1.
2. A separately authenticated owner submits the answer.
3. Continuation retains the original Task, assignment, execution and concrete agent.
4. Requirements 2 includes the owner answer.
5. An independent verifier stores three checks against that exact revision/hash.
6. Owner confirmation advances to Backlog and the Analysis queue; replay matches.

The controlled model transport exercises real native tools, owner APIs and
storage. This proves requirements completeness, not implementation of the
application described by those requirements.

Live negative cases reject human native admission (401), completed native work
(409), unknown execution (503), PM self-verification (403), a foreign agent (409),
and stale-revision evidence (409). Workflow/Fleet restart preserves PM identity
and confirmation. Tracker outage permits original context replay and rejects a
new context with 503.

Namespace context v2 stores verified resource references. Its general autonomous
execution adapter is unfinished, so `runtime_ready=false` and
`dispatch_allowed=false`. This is separate from editable Workflow instructions
and the qualified PM path. No installed or production runtime was replaced.

## Reproduce

Run the canonical source gate from the repository root using
[quality-gate.md](quality-gate.md). Its constrained `uv` commands include:

```sh
uv run --isolated --with-requirements constraints.txt --all-extras pytest -q --timeout=60
uv run --isolated --with-requirements constraints.txt --all-extras pytest -q -m integration tests/test_postgres_integration.py --timeout=120
uv run --isolated --with-requirements constraints.txt --all-extras pytest --cov=project_workflow --cov-report=term --timeout=60
uv run --isolated --with-requirements constraints.txt --all-extras ruff check .
uv run --isolated --with-requirements constraints.txt --all-extras mypy project_workflow scripts
uv run --isolated --with-requirements constraints.txt --all-extras python -m scripts.export_pm_openapi
git diff --check
```

Native acceptance additionally needs the coordinated Auth, Tracker, Fleet,
Workflow and real resource owners. Follow
[the continuation contract](pm-continuation-contract.md) and
[the resource context configuration](resource-execution-context.md). Private QA
credentials, snapshots, raw logs and host-specific paths stay outside this repo.
Each dependency update needs its own current acceptance; the Tracker #127
state-write-permit follow-up is not covered by the earlier roundtrip above.
