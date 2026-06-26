# Plan: smart agent in `project-workflow` via ChatGPT/OpenAI subscription

Date: 2026-06-06
Project: `/opt/dev/hermes-workspace/project-workflow`

## 1. What I verified in the current codebase

This plan is grounded in the live repository, not invented from scratch.

### Existing runtime and UI surface
- Main UI routes live in `project_workflow/ui.py`:
  - `/` — minimal dashboard
  - `/phases`
  - `/phase/{phase_id}`
  - `/tasks`
  - `/task/{task_key}`
  - `/projects`
  - `/workflows`
  - `/agents`
  - `/settings`
- `settings` is already intentionally **read-only CLI reference**, auto-built from real Click commands by `_load_cli_reference()` in `project_workflow/ui.py`.
- `_load_cli_reference()` already excludes the `ui` command, which matches the product rule that web UI launch must **not** appear as a user CLI command.

### Existing CLI contract
- CLI is intentionally thin.
- Registered user-facing commands are currently only:
  - `step`
  - `history`
- There is already a guard in tests preventing uncontrolled CLI growth (`tests/test_ui.py` + CLI module comments/tests).

### Existing data model
Current SQLite schema in `project_workflow/db_schema.sql` contains:
- `agents`
- `workflows`
- `phases`
- `instructions`
- `checks`
- `evidence`
- `projects`
- `tasks`
- `task_history`
- `cli_history`

Important current fact:
- `agents` currently has only `id`, `name`, `description`.
- There are **no** tables for users, auth, subscriptions, provider configs, LLM usage, or agent chat sessions.

### Existing conversation / wizard foundation
- `project_workflow/conversation.py` already stores task conversation in a separate SQLite DB (`~/.project-workflow/conversation.db`).
- Roles already include `user | system | wizard | agent`.
- `project_workflow/wizard.py` already provides:
  - `WizardEngine.get_phase_prompt()`
  - `WizardEngine.get_full_context()`
  - `WizardEngine.evaluate(report)`
- This is a strong existing foundation for a smart assistant because task context, phase state, and message history already exist.

### Important architectural constraints already visible in code/tests
- Removed legacy wizard HTTP endpoints must stay removed (`tests/test_ui_api.py` asserts `/api/wizard/*` is 404).
- Therefore new smart-agent API must be introduced as a **new bounded surface**, not by restoring the old generic wizard API.
- Dashboard is intentionally minimal and must remain real-data only.
- Settings page must continue reflecting real CLI only, and must not become a generic admin dump.

---

## 2. External product constraint: ChatGPT subscription != API entitlement

Before implementation, one architectural fact must be accepted:

- OpenAI documents that **ChatGPT billing and API billing are separate systems**.
- ChatGPT Plus/Business subscription does **not** automatically give programmatic API usage rights for this app.
- Therefore the workflow app cannot safely infer "active smart-agent access" from a ChatGPT web subscription alone.

Official references used for this plan:
- https://help.openai.com/en/articles/9039756-billing-settings-in-chatgpt-vs-platform
- https://help.openai.com/en/articles/6950777-what-is-chatgpt-plus
- https://help.openai.com/en/articles/8156019-how-can-i-move-my-chatgpt-subscription-to-the-api

## Conclusion from this constraint
For this codebase, the correct first implementation is:
1. Treat smart-agent access as an **application/workspace subscription/entitlement**.
2. Use a server-side OpenAI API key / provider configuration for execution.
3. Optionally expose project-level enable/disable on top of the workspace entitlement.

Do **not** design v1 around reading a user’s personal ChatGPT Plus status.

---

## 3. Recommended product scope for v1

## Goal
Add a **smart assistant for workflow tasks** that:
- understands current phase,
- sees task/project/workflow context,
- reads task conversation/history,
- suggests next steps,
- drafts reports/checklists,
- helps prepare phase completion evidence,
- is visible only when subscription/entitlement is active.

## Explicit non-goals for v1
- No full autonomous agent that mutates workflow state freely.
- No user-account system unless separately approved.
- No raw ChatGPT web login embedding.
- No new public CLI commands beyond the current contract unless explicitly approved.
- No provider/admin settings inside `/settings` because that page is reserved for CLI reference.

---

## 4. Product decision that best fits the current architecture

Because the app currently has:
- no auth,
- no users,
- no seats,
- no org model,
- local SQLite storage,
- single-workspace style operation,

The lowest-risk shape is:

## v1 subscription scope = workspace-level entitlement + project-level toggle

That means:
- Workspace owner configures OpenAI/API access once.
- App knows whether smart-agent capability is active.
- Each project can enable/disable smart-agent usage and choose default agent persona.

This fits the current architecture much better than multi-user subscriptions.

### Future v2 (optional)
If later needed, expand to:
- users,
- login,
- seat-based subscriptions,
- per-user usage limits,
- audit by actor.

But that is **not** the correct first step for the current repo.

---

## 5. Proposed UX (text-only, no implementation yet)

These are proposed page behaviors, not code yet.

### A. Task detail page: `/task/{task_key}`
Purpose:
- main place where the smart agent helps on a real task.

Add a right-side or lower panel:
- block title: `Умный агент`
- status line:
  - `Активен` / `Недоступен` / `Подписка не активна`
- quick actions:
  - `Что делать дальше?`
  - `Суммируй прогресс`
  - `Проверь готовность фазы`
  - `Собери черновик отчёта`
- free-text prompt input
- conversation thread for this task
- optional “apply as draft note” action that saves the answer into task conversation/history

Important behavior:
- agent must use current task phase + workflow data + prior conversation
- agent may suggest a report, but actual phase transition must still go through the existing workflow gate logic

### B. Projects page: `/projects`
Purpose:
- configure whether a project uses smart-agent features.

For each project, add:
- `Smart agent enabled` toggle
- `Default agent` selector
- optional usage policy section (simple, human-readable; no noisy raw tuning)

Because the app is already strongly project-scoped, this is the cleanest configuration point.

### C. Agents page: `/agents`
Purpose:
- keep it as agent persona catalog.

Visible main fields should remain human-readable:
- `Имя`
- `Описание`

Optional advanced config may be stored for runtime, but should **not** turn the main list into a dump of numeric knobs.

Possible advanced fields (not necessarily shown in the main grid):
- system prompt
- allowed action set
- response style
- default workflow focus

### D. New dedicated admin page for provider/subscription
Recommended new page:
- `/assistant` or `/subscription`

Purpose:
- manage provider connection and entitlement status.

Suggested content:
- provider name (`OpenAI`)
- configured model
- secret source (`OPENAI_API_KEY` env reference only; never show the secret)
- subscription/entitlement status
- last successful validation
- daily/monthly usage counters
- last error if provider is unavailable

Important:
- **do not put this into `/settings`**
- `/settings` must stay a read-only CLI reference page

### E. Dashboard: `/`
Purpose:
- remain minimal.

Only add smart-agent info if it is real and useful, for example:
- one compact card: `Умный агент: активен / недоступен`
- optionally `N диалогов сегодня`

Do not add placeholders, fake KPIs, or synthetic token charts.
If there is no real configured data, hide the block entirely.

---

## 6. Data model changes (recommended)

Current schema has no place for provider/subscription/runtime metadata.

Recommended new tables in `workflow.db`:

### 6.1 `assistant_provider_configs`
Purpose:
- store non-secret provider runtime configuration.

Suggested fields:
- `id`
- `code` UNIQUE
- `provider` (`openai` for v1)
- `base_url` NULLABLE
- `api_key_env` (example: `OPENAI_API_KEY`)
- `default_model`
- `enabled` CHECK (0/1)
- `created_at`
- `updated_at`

Important:
- store env var name/reference, not the secret itself.

### 6.2 `assistant_subscriptions`
Purpose:
- local entitlement/subscription state for the app.

Suggested fields:
- `id`
- `provider_config_id` FK
- `scope` CHECK (`workspace`, `project`)
- `project_id` NULLABLE FK
- `plan_code`
- `status` CHECK (`inactive`, `trial`, `active`, `past_due`, `cancelled`)
- `started_at`
- `renews_at`
- `ends_at`
- `external_ref` NULLABLE
- `source` CHECK (`manual`, `provider`, `imported`)
- `meta_json` TEXT default `'{}'`

### 6.3 `project_assistant_settings`
Purpose:
- enable/disable assistant per project without inventing users.

Suggested fields:
- `project_id` PK/FK
- `enabled` CHECK (0/1)
- `default_agent_id` NULLABLE FK
- `provider_config_id` NULLABLE FK
- `allow_draft_notes` CHECK (0/1)
- `allow_phase_readiness_checks` CHECK (0/1)

### 6.4 `assistant_sessions`
Purpose:
- audit each task-level assistant interaction session.

Suggested fields:
- `id`
- `task_id` FK
- `project_id` FK
- `agent_id` NULLABLE FK
- `provider_config_id` FK
- `status` CHECK (`active`, `completed`, `failed`)
- `started_at`
- `finished_at`
- `input_tokens` INTEGER default 0
- `output_tokens` INTEGER default 0
- `estimated_cost_usd` REAL default 0
- `last_error` TEXT NULLABLE

### 6.5 `assistant_messages`
Purpose:
- persist assistant chat messages in the main workflow DB.

Suggested fields:
- `id`
- `session_id` FK
- `task_id` FK
- `role` CHECK (`user`, `assistant`, `system`)
- `content` TEXT
- `created_at`

## Alternative implementation note
Because `conversation.py` already exists, v1 may also:
- store transcript in existing `conversation.db`,
- store only usage/audit metadata in `workflow.db`.

### Recommended choice
For the first iteration, prefer:
- keep current `conversation.py` untouched for wizard/task history compatibility,
- add smart-agent metadata tables in `workflow.db`,
- mirror assistant/user chat entries into `conversation.db` with existing roles.

This avoids a risky full conversation migration in the same feature.

---

## 7. Backend/service design

## New modules recommended

### `project_workflow/assistant_service.py`
Responsibilities:
- validate entitlement/project enablement
- open/reuse task assistant session
- assemble task context
- call provider client
- persist request/response metadata
- optionally mirror messages into `conversation.py`

### `project_workflow/assistant_provider_openai.py`
Responsibilities:
- wrap OpenAI API calls
- isolate provider-specific payload shape
- normalize errors/timeouts
- return a stable internal response DTO

### `project_workflow/subscription_service.py`
Responsibilities:
- compute effective entitlement:
  - workspace active?
  - project enabled?
  - provider enabled?
- return a single availability verdict for UI/API

### `project_workflow/context_builder.py` (optional, but clean)
Responsibilities:
- combine:
  - task record
  - project record
  - workflow/phases
  - task history
  - `WizardEngine.get_full_context()`
  - recent conversation
- build a compact LLM-ready context object

## Reuse existing code instead of bypassing it
Must reuse:
- `WizardEngine.get_full_context()`
- current phase/task history loading in `ui.py`
- `conversation.py`
- project/workflow/phase DB access in `db.py`

Do **not** create a second disconnected state model for the assistant.

---

## 8. API surface (new, bounded, non-legacy)

Do **not** restore `/api/wizard/*`.

Recommended new endpoints:

### Task assistant
- `GET /api/tasks/{task_key}/assistant/state`
  - returns availability, project enablement, active session summary
- `GET /api/tasks/{task_key}/assistant/messages`
  - returns current assistant thread
- `POST /api/tasks/{task_key}/assistant/messages`
  - send user message to assistant
- `POST /api/tasks/{task_key}/assistant/actions/next-step`
  - structured quick action
- `POST /api/tasks/{task_key}/assistant/actions/phase-readiness`
  - structured quick action
- `POST /api/tasks/{task_key}/assistant/actions/report-draft`
  - structured quick action

### Assistant admin
- `GET /api/assistant/config`
- `PUT /api/assistant/config`
- `GET /api/assistant/subscription`
- `POST /api/assistant/subscription/validate`

### Project-level settings
- `GET /api/projects/{project_id}/assistant-settings`
- `PUT /api/projects/{project_id}/assistant-settings`

## Important rule
All assistant responses must be human-readable and workflow-oriented.
No leaking raw provider payloads into the user-facing UI.

---

## 9. Behavior rules for the smart agent

These rules are critical so the feature respects the current workflow philosophy.

### Rule 1: assistant is advisory-first
The assistant may:
- summarize
- suggest
- draft
- explain phase requirements
- help map missing evidence

The assistant must not silently mutate workflow state.

### Rule 2: workflow state remains authoritative
Any real phase progression must still be driven by the existing workflow logic.

Meaning:
- assistant can draft a candidate report
- final phase pass/fail must still use the existing gate semantics (`wizard.py` / shared service logic)

### Rule 3: project/workflow context always included
Every assistant request should include at minimum:
- task key/title/status
- current phase
- project
- workflow
- relevant phase instructions/checks/evidence
- recent conversation
- recent task history

### Rule 4: no placeholder analytics
If usage/cost/subscription data is not real, do not show the widget.

### Rule 5: secrets stay outside DB
Store only env var references, never API secrets in SQLite.

---

## 10. File-by-file implementation map

## Schema and DB
- `project_workflow/db_schema.sql`
  - add new assistant/subscription tables
- `project_workflow/db.py`
  - CRUD and query helpers for new tables
  - project assistant settings resolution
  - session/message persistence helpers

## Services
- `project_workflow/assistant_service.py` (new)
- `project_workflow/subscription_service.py` (new)
- `project_workflow/assistant_provider_openai.py` (new)
- `project_workflow/context_builder.py` (optional new)

## UI/backend routes
- `project_workflow/ui.py`
  - new assistant admin page route
  - new task assistant API routes
  - new project assistant settings routes
  - task detail context expansion

## Templates
- `project_workflow/templates/v2/task_detail.html`
  - add smart-agent panel
- `project_workflow/templates/v2/projects.html`
  - add project-level enable/default-agent controls
- `project_workflow/templates/v2/agents.html`
  - keep main list human-readable; optionally add advanced editor affordance
- `project_workflow/templates/v2/dashboard.html`
  - optional minimal assistant status card only if real data exists
- `project_workflow/templates/v2/settings.html`
  - likely no logic change; only regression protection
- `project_workflow/templates/v2/assistant.html` or `subscription.html` (new)
  - provider/subscription admin page

## Existing runtime reuse
- `project_workflow/wizard.py`
  - context/reuse, not duplicate logic
- `project_workflow/conversation.py`
  - optional mirroring of chat transcript

---

## 11. TDD / test plan (mandatory)

Implementation must be test-first.
No real provider dependency in tests.
Use mocks/fakes for OpenAI responses.

## New/updated test files

### DB and constraints
- `tests/test_db_constraints.py`
  - invalid subscription statuses rejected
  - FK integrity for project/settings/session rows
  - booleans/check constraints enforced
- `tests/test_db.py`
  - CRUD for provider config / subscription / project assistant settings / sessions

### Service layer
- `tests/test_assistant_service.py` (new)
  - unavailable when no active entitlement
  - unavailable when project disabled
  - builds context from task + wizard + history
  - persists session/messages/usage
  - mirrors conversation if enabled
- `tests/test_subscription_service.py` (new)
  - workspace active + project enabled => available
  - inactive subscription => unavailable
  - disabled provider => unavailable

### UI/API
- `tests/test_ui_api.py`
  - new task assistant endpoints return 200/403 correctly
  - `/api/wizard/*` stays 404
  - `/api/settings` still excludes `ui`
- `tests/test_ui.py`
  - task detail shows assistant panel only when enabled
  - dashboard stays minimal
  - agents page still focuses on name/description
  - settings page remains CLI-only
  - no provider/admin leakage into settings page

### Integration
- `tests/test_integration.py`
  - full path: enable provider + enable project + ask assistant on task + persist session + see UI/API result

## Important test policy
- No real network calls to OpenAI in unit/integration tests.
- Mock provider responses with deterministic payloads.
- If browser/UI proof is later requested during implementation, provide screenshots.

---

## 12. Recommended delivery order (small safe milestones)

## Milestone 0 — decision freeze
Deliverables:
- confirm scope = workspace subscription + project toggle
- confirm page name for provider/subscription admin
- confirm whether assistant is advisory-only in v1

## Milestone 1 — schema + DB layer
Deliverables:
- new tables
- DB CRUD
- constraint tests

## Milestone 2 — provider + entitlement services
Deliverables:
- provider config model
- entitlement resolution
- mocked provider client
- service tests

## Milestone 3 — task smart-agent API
Deliverables:
- task assistant session/message endpoints
- quick actions
- persistence and context builder

## Milestone 4 — task detail UI
Deliverables:
- assistant panel in `/task/{task_key}`
- real-time-ish refresh via existing simple frontend style
- no placeholders

## Milestone 5 — project/admin UI
Deliverables:
- project assistant toggle/default agent
- dedicated assistant/subscription page
- settings page untouched except regression tests

## Milestone 6 — dashboard polish
Deliverables:
- minimal real status card only if data exists

## Milestone 7 — hardening
Deliverables:
- timeouts
- retries
- cost tracking
- error states
- usage caps / abuse guard

---

## 13. Risks and pitfalls

### Risk 1: wrong subscription model
If implementation assumes ChatGPT Plus directly unlocks API execution, the feature will be structurally broken.

### Risk 2: accidental CLI pollution
Adding assistant/admin commands into CLI would violate the current design/tests.
Recommendation: keep assistant management in UI/backend config layer unless explicitly approved otherwise.

### Risk 3: restoring legacy wizard API
Tests already encode that the old generic wizard API is removed.
Do not bring it back.

### Risk 4: duplicated state machines
If assistant phase logic diverges from `wizard.py`, users will get conflicting answers.
Reuse the same context and verdict machinery.

### Risk 5: dashboard/settings bloat
Do not turn `/settings` into an admin junk drawer.
Do not turn dashboard into fake analytics.

### Risk 6: secret handling
Never persist raw API keys in SQLite.
Use env references only.

---

## 14. Recommended final architecture choice

If implementation started today, I would recommend this exact v1 shape:

1. **Workspace-level OpenAI provider config**
2. **Workspace subscription/entitlement record**
3. **Project-level smart-agent enable toggle + default agent**
4. **Smart-agent panel only on task detail page first**
5. **Dedicated `/assistant` admin page, not `/settings`**
6. **Reuse `WizardEngine.get_full_context()` and `conversation.py`**
7. **Assistant is advisory/drafting only; phase progression still uses existing workflow gate logic**
8. **No new public CLI commands in v1**

This is the cleanest path that fits the current codebase instead of fighting it.

---

## 15. If we continue after this plan

Best next step after plan approval:

### Option A — safe and incremental
Start with Milestone 1 only:
- schema
- DB CRUD
- tests

### Option B — vertical slice
Implement one thin working slice:
- provider config
- project enablement
- task detail assistant panel
- one action: `Что делать дальше?`
- mocked tests first, real provider behind env flag

## My recommendation
Start with **Option B after schema/tests**, because it gives visible value fastest while still respecting the current architecture.
