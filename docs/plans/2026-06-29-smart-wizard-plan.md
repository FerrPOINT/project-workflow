# Smart Wizard — Implementation Plan (No External Verification)

> **Constraint:** Wizard must NOT verify the outside world. It believes the report, but it must deeply understand it. No git, no file checks, no tool calls, no network probes.

**Goal:** Make the workflow wizard reason like Hermes using only the report text, conversation history, phase contract, and per-task memory. It stays sandboxed inside the application layer.

**Architecture:** Add small, feature-flagged modules around `WizardEngine`. Default mode unchanged; smart features opt-in via `SMART_*` env flags. Keep the existing thin Ollama/OpenAI-compatible client — no LangChain.

**Tech Stack:** Python 3.10+, existing `OllamaClient`, SQLite for memory, prompt engineering.

---

## Phase 1 — Per-Task Memory

### Task 1.1: Add `wizard_memories` table/model

**Objective:** Persist per-task memories (corrections, lessons, blocker patterns, preferences).

**Files:**
- Inspect: `project_workflow/infrastructure/db/models.py`
- Modify: add `WizardMemory` SQLAlchemy model
- Create Alembic revision or update runtime schema if project uses auto-create
- Test: `tests/test_wizard_memory_model.py`

**Step 1:** Inspect current DB model structure and how tables are created (`create_all()` path).
**Step 2:** Add model:
```python
class WizardMemory(Base):
    __tablename__ = "wizard_memories"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    memory_type = Column(String, nullable=False)  # correction | lesson | blocker_pattern | preference
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
```
**Step 3:** Failing test on table creation + create.
**Step 4:** Make test pass.
**Step 5:** Commit.

```bash
git add project_workflow/infrastructure/db/models.py tests/test_wizard_memory_model.py
git commit -m "feat(wizard): add WizardMemory model"
```

---

### Task 1.2: Create `MemoryStore`

**Objective:** Repository-like access to wizard memories.

**Files:**
- Create: `project_workflow/wizard/memory.py`
- Test: `tests/test_wizard_memory_store.py`

**Step 1:** Implement:
```python
class MemoryStore:
    def __init__(self, uow):
        self.uow = uow

    def add(self, task_id: int, memory_type: str, content: str) -> int:
        ...

    def list_for_task(self, task_id: int, limit: int = 10) -> list[dict]:
        ...

    def find_by_type(self, task_id: int, memory_type: str, limit: int = 5) -> list[dict]:
        ...
```
**Step 2:** TDD cycle.
**Step 3:** Commit.

```bash
git add project_workflow/wizard/memory.py tests/test_wizard_memory_store.py
git commit -m "feat(wizard): add MemoryStore for task memory"
```

---

### Task 1.3: Auto-capture memories from evaluate results

**Objective:** When wizard gives BLOCKED/PARTIAL, it stores the blocker pattern or missing item as a lesson.

**Files:**
- Modify: `project_workflow/wizard/core.py`
- Test: `tests/test_wizard_memory_capture.py`

**Step 1:** After `evaluate()` returns BLOCKED/PARTIAL/HARD_FAIL, store:
- `blocker_pattern` for each blocker
- `lesson` for first missing item (truncated)

**Step 2:** Test with mocked store.
**Step 3:** Commit.

```bash
git add project_workflow/wizard/core.py tests/test_wizard_memory_capture.py
git commit -m "feat(wizard): auto-capture memory from blocked/partial verdicts"
```

---

## Phase 2 — Chain-of-Thought Reasoning

### Task 2.1: Add `ReasoningEngine`

**Objective:** Parse structured reasoning output from LLM.

**Files:**
- Create: `project_workflow/wizard/reasoning.py`
- Test: `tests/test_wizard_reasoning.py`

**Dataclass:**
```python
@dataclass
class ReasoningResult:
    analysis: str
    claims: list[dict]
    blockers: list[str]
    missing: list[str]
    verdict: str
    confidence: float
    next_steps: list[str]
    raw: dict
```

**Step 1:** TDD parser.
**Step 2:** Commit.

```bash
git add project_workflow/wizard/reasoning.py tests/test_wizard_reasoning.py
git commit -m "feat(wizard): add ReasoningEngine parser"
```

---

### Task 2.2: Add chain-of-thought prompt

**Objective:** LLM analyses claims in the report and returns reasoning structure.

**Files:**
- Modify: `project_workflow/wizard/prompt.py` — add `build_reasoning_prompt`
- Test: `tests/test_wizard_reasoning_prompt.py`

**Prompt requirements:**
- Identify each claim in the report.
- Match claim to phase contract items.
- Note contradictions or vague statements.
- Return JSON: `analysis`, `claims`, `blockers`, `missing`, `verdict`, `confidence`, `next_steps`.

**Step 1:** Write test checking prompt contains contract items.
**Step 2:** Implement.
**Step 3:** Commit.

```bash
git add project_workflow/wizard/prompt.py tests/test_wizard_reasoning_prompt.py
git commit -m "feat(wizard): add chain-of-thought reasoning prompt"
```

---

### Task 2.3: Integrate reasoning into evaluate

**Objective:** When `SMART_REASONING=1`, use reasoning prompt + parser before final verdict.

**Files:**
- Modify: `project_workflow/wizard/evaluate.py`
- Modify: `project_workflow/wizard/core.py` (pass flag)
- Test: `tests/test_wizard_reasoning_evaluate.py`

**Step 1:** Mock LLM to return reasoning JSON; assert result contains reasoning fields.
**Step 2:** Implement path in `evaluate_llm_report`.
**Step 3:** Commit.

```bash
git add project_workflow/wizard/evaluate.py project_workflow/wizard/core.py tests/test_wizard_reasoning_evaluate.py
git commit -m "feat(wizard): integrate chain-of-thought reasoning into evaluate"
```

---

## Phase 3 — Persona Adapter

### Task 3.1: Create `PersonaAdapter`

**Objective:** Convert any result into user's preferred output style.

**Files:**
- Create: `project_workflow/wizard/persona.py`
- Test: `tests/test_wizard_persona.py`

**Rules:**
- No emojis.
- No "All checks passed" / "You can proceed" / internal phase codes.
- Three sections only: Инструкции, Чекапы, Доказательства.
- PASS → show next phase contract items with pending markers (·).
- PARTIAL/SOFT_FAIL → "Ты сделал часть, доделай:" + not-done items.
- BLOCKED → explicit blocker + what to fix.
- Always end with one actionable next step.

**Step 1:** TDD for PASS, PARTIAL, BLOCKED cases.
**Step 2:** Commit.

```bash
git add project_workflow/wizard/persona.py tests/test_wizard_persona.py
git commit -m "feat(wizard): add persona adapter for user-aligned output"
```

---

### Task 3.2: Use persona adapter in `format_result`

**Objective:** Apply adapter when `SMART_PERSONA=1`.

**Files:**
- Modify: `project_workflow/wizard/core.py`
- Test: `tests/test_wizard_format_persona.py`

**Step 1:** Keep legacy `format_result` as default.
**Step 2:** If `SMART_PERSONA`, use `PersonaAdapter`.
**Step 3:** TDD.
**Step 4:** Commit.

```bash
git add project_workflow/wizard/core.py tests/test_wizard_format_persona.py
git commit -m "feat(wizard): wire persona adapter into format_result"
```

---

## Phase 4 — Plan Builder

### Task 4.1: Create `PlanBuilder`

**Objective:** Build concrete action plan for BLOCKED/PARTIAL results.

**Files:**
- Create: `project_workflow/wizard/plan_builder.py`
- Test: `tests/test_wizard_plan_builder.py`

**Input:** missing items, blockers, current phase contract.
**Output:** ordered list like:
```python
[
    {"order": 1, "action": "Допиши тесты для X", "contract_item": "..."},
    {"order": 2, "action": "Перезапусти pytest", "contract_item": "..."},
]
```

**Step 1:** TDD.
**Step 2:** Commit.

```bash
git add project_workflow/wizard/plan_builder.py tests/test_wizard_plan_builder.py
git commit -m "feat(wizard): add plan builder for partial/blocked results"
```

---

### Task 4.2: Expose `action_plan` in result

**Objective:** `evaluate()` returns `action_plan` when not PASS.

**Files:**
- Modify: `project_workflow/wizard/core.py`
- Modify: `project_workflow/wizard/types.py` (WizardAssessment)
- Test: `tests/test_wizard_action_plan.py`

**Step 1:** Add field to result dict and assessment.
**Step 2:** TDD.
**Step 3:** Commit.

```bash
git add project_workflow/wizard/core.py project_workflow/wizard/types.py tests/test_wizard_action_plan.py
git commit -m "feat(wizard): expose action_plan in evaluate results"
```

---

## Phase 5 — Smart Context Assembly

### Task 5.1: Inject memory into prompt context

**Objective:** `WizardContextBuilder` loads task memories into context.

**Files:**
- Modify: `project_workflow/wizard/context.py`
- Test: `tests/test_wizard_context_memory.py`

**Step 1:** Add `memories` to context (formatted as short bullets).
**Step 2:** TDD.
**Step 3:** Commit.

```bash
git add project_workflow/wizard/context.py tests/test_wizard_context_memory.py
git commit -m "feat(wizard): include task memory in evaluation context"
```

---

### Task 5.2: Add recent conversation summary

**Objective:** Context includes summary of recent messages, not just raw dump.

**Files:**
- Modify: `project_workflow/wizard/context.py`
- Test: `tests/test_wizard_context_conversation_summary.py`

**Step 1:** Summarize last N messages into a few bullets.
**Step 2:** TDD.
**Step 3:** Commit.

```bash
git add project_workflow/wizard/context.py tests/test_wizard_context_conversation_summary.py
git commit -m "feat(wizard): add conversation summary to context"
```

---

## Phase 6 — Clarification Mode

### Task 6.1: Add `needs_clarification` detection

**Objective:** If report is too vague or skips contract items, wizard asks clarifying questions instead of guessing.

**Files:**
- Create: `project_workflow/wizard/clarify.py`
- Test: `tests/test_wizard_clarify.py`

**Output structure:**
```python
{
    "needs_clarification": True,
    "questions": ["..."],
    "missing_contract_items": ["..."],
}
```

**Step 1:** TDD with vague report.
**Step 2:** Commit.

```bash
git add project_workflow/wizard/clarify.py tests/test_wizard_clarify.py
git commit -m "feat(wizard): add clarification detection"
```

---

### Task 6.2: Integrate clarification into evaluate

**Objective:** When `SMART_CLARIFY=1`, short-circuit to clarification instead of weak verdict.

**Files:**
- Modify: `project_workflow/wizard/core.py`
- Test: `tests/test_wizard_clarify_evaluate.py`

**Step 1:** Before deterministic rules, run clarification detector.
**Step 2:** If needs clarification, return `CLARIFICATION` verdict with questions.
**Step 3:** Commit.

```bash
git add project_workflow/wizard/core.py tests/test_wizard_clarify_evaluate.py
git commit -m "feat(wizard): integrate clarification mode into evaluate"
```

---

## Phase 7 — Feature Flags & CLI

### Task 7.1: Add `SMART_*` flags to config

**Objective:** All smart features opt-in.

**Files:**
- Modify: `project_workflow/config.py`

Add:
```python
SMART_REASONING = os.getenv("SMART_REASONING", "").lower() in ("1", "true", "yes", "on")
SMART_MEMORY = os.getenv("SMART_MEMORY", "").lower() in ("1", "true", "yes", "on")
SMART_PERSONA = os.getenv("SMART_PERSONA", "").lower() in ("1", "true", "yes", "on")
SMART_PLAN = os.getenv("SMART_PLAN", "").lower() in ("1", "true", "yes", "on")
SMART_CLARIFY = os.getenv("SMART_CLARIFY", "").lower() in ("1", "true", "yes", "on")
```

**Step 1:** Commit.

```bash
git add project_workflow/config.py
git commit -m "feat(config): add SMART_* feature flags"
```

---

### Task 7.2: Add `--smart` CLI flag to step command

**Objective:** Enable all smart features per call.

**Files:**
- Inspect current step CLI location (`project_workflow/interfaces/cli/ui.py` or similar)
- Modify: add `--smart` option
- Test: `tests/test_cli_smart_flag.py`

**Step 1:** Find step command implementation.
**Step 2:** Add flag that sets env vars for command duration.
**Step 3:** TDD.
**Step 4:** Commit.

```bash
git add project_workflow/interfaces/cli/ui.py tests/test_cli_smart_flag.py
git commit -m "feat(cli): add --smart flag to step command"
```

---

## Phase 8 — Verification & Final Commit

### Task 8.1: Run targeted tests

```bash
pytest tests/test_wizard_memory_model.py tests/test_wizard_reasoning.py tests/test_wizard_persona.py tests/test_wizard_plan_builder.py tests/test_wizard_clarify.py -v
```
Expected: all pass.

### Task 8.2: Run full suite

```bash
pytest -q --timeout=60 --forked
```
Expected: 869 passed, 6 deselected.

### Task 8.3: Lint

```bash
ruff check project_workflow tests
```
Expected: All checks passed!

### Task 8.4: Type check

```bash
mypy project_workflow
```
Expected: Success: no issues found.

### Task 8.5: UI health

```bash
systemctl restart project-workflow-ui.service
curl -s -o /dev/null -w "%{http_code}" http://localhost:8811/api/tasks
```
Expected: 200.

### Task 8.6: Commit plan and any remaining changes

```bash
git add docs/plans/2026-06-29-smart-wizard-plan.md
git commit -m "docs: smart wizard plan (no external verification)"
```

---

## Notes

- Wizard stays sandboxed: no git, no file reads, no subprocess, no network.
- All smart behaviour is prompt- and memory-driven.
- Every task follows TDD; every task ends with a commit.
- Default evaluate remains unchanged unless `SMART_*` flags are on.
