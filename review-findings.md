# Code Review Findings — project-workflow

Baseline: 949 tests passed

## CRITICAL & HIGH

1. **Missing Transaction Rollbacks (HIGH)**
   - `project_workflow/application/*.py`: Service methods call `self._uow.commit()` outside a context manager. If an exception happens, `rollback()` is not called, leaving the session dirty and causing `PendingRollbackError` on next requests.
   - *Fix:* Wrap in `with self._uow:` or `try...finally`.

2. **Partial Updates / Split Commits (HIGH)**
   - `project_workflow/wizard/core.py:472` and `transitions.py`: `evaluate()` performs disjoint commits. The state transition commits, then `_persist_supervisor_run()` commits separately. If the second fails, audit log is lost.
   - *Fix:* Remove internal `.commit()` calls and commit exactly once at the end.

3. **DB Session Leaks in FastAPI (HIGH)**
   - `project_workflow/interfaces/ui/routes/api.py`, `application/ui.py`: Endpoints instantiate `SAUnitOfWork` but rarely use it as a context manager and never call `.close()`. Exhausts `QueuePool`.
   - *Fix:* Use `with uow:` or FastAPI `Depends()` with `yield uow`.

4. **XSS / Unescaped Inputs (HIGH)**
   - `project_workflow/interfaces/ui/templates/phase_detail.html:160, 580`: Jinja `{{ phase.name }}` inside JS strings isn't safely escaped for JS (e.g. `O'Reilly` breaks the string and executes JS).
   - *Fix:* Use `{{ phase.name | tojson }}` or `| escapejs`.

5. **State Mismatches API vs DB (HIGH)**
   - `routes/api.py`: Atomic edits to instructions (create/update/delete/reorder) never call `persist_phase_update_to_seed()`. Changes are lost on restart/reseed.
   - *Fix:* Call `persist_phase_update_to_seed` after instruction mutations.

6. **Primary Key Overwrite (CRITICAL)**
   - `infrastructure/db/repositories/phase.py:64`: `update()` blindly uses `setattr(row, key, val)`. Passing `{"id": 999}` overwrites the PK.
   - *Fix:* Ignore `id` and `workflow_id` from the update payload.

7. **N+1 Query & Heavy Lazy-Loading Bug (HIGH)**
   - `infrastructure/db/repositories/converters.py:73`: `_row_to_task` reads `row.project.workflow.phases` to find `current_phase_name`. Triggers N+1 for Project, Workflow, Phase for every task.
   - *Fix:* Add `joinedload(m.Task.project)` and `selectinload(m.Project.workflow.phases)` to `task.py:list()`.

8. **N+1 Queries in Phase/Project Converters (HIGH)**
   - `infrastructure/db/repositories/converters.py:42, 68`: `_row_to_phase` calls `row.workflow.name`. Triggers N+1.
   - *Fix:* Add `joinedload` for workflow.

9. **Empty Report Bypass (HIGH)**
   - `wizard/checks.py:29`: `check_coverage` evaluates an empty report to PASS if `previously_covered` items fulfill the checklist.
   - *Fix:* Ensure report has actual content or block empty text.

10. **False Positive Blockers (HIGH)**
    - `wizard/checks.py:46`: `extract_blockers` uses raw substring matching. Benign text like "no blockers" triggers a blocker.
    - *Fix:* Use NLP or better regex boundaries.

11. **False Positive Coverage (HIGH)**
    - `wizard/checks.py:24`: `extract_keywords` uses substring matching. "flint" matches "lint".
    - *Fix:* Use word boundaries `\b`.

12. **Broken Numeric Regex (HIGH)**
    - `domain/validation.py:77`: Regex `r"^\d+$"` is a raw string but probably over-escaped as `r"^\\d+$"`, failing to match digits.
    - *Fix:* Fix regex escape.

13. **DB Constraint Crash on Invalid Verdicts (HIGH)**
    - `wizard/reasoning.py:33`: `ReasoningEngine.parse` doesn't enforce strict enum. LLM generating "PASS (ALMOST)" hits the PostgreSQL CHECK constraint and crashes.
    - *Fix:* Validate and coerce verdict to strict ENUM before saving.

## MEDIUM

14. **Race Conditions in Sequence Generation**
    - `application/phase.py:434`, `instruction.py:133`: Phase codes and instruction `step_num` are generated via unlocked max scans. Concurrent creation raises `IntegrityError`.

15. **Unhandled DB Integrity Errors**
    - `application/project.py`, `task.py`: Unique constraint violations crash with 500 instead of HTTP 409 Conflict.

16. **Cross-Phase Instruction Corruption Risk**
    - `application/instruction_service.py:243`: `reorder_instructions` doesn't validate if `instruction_ids` belong to `phase_id`. Could update other phases' instructions.

17. **Unpaginated Large Queries**
    - `application/ui.py` (`_load_tasks`): Fetches all tasks via `id.desc()` with no LIMIT. Will OOM eventually.

18. **Missing Validation / API Crash**
    - `routes/api.py:145`: `int(workflow_id)` on a non-digit string crashes with HTTP 500.

19. **SQLite Pragma Listener Dead Code**
    - `infrastructure/db/session.py:121`: Checks `getattr(connection_record, "dialect")` which was removed in SQLAlchemy 2.0. `foreign_keys=ON` and `WAL` are silently ignored.

20. **Multi-Workflow Collision on `get_by_code`**
    - `infrastructure/db/repositories/phase.py:38`: `scalar_one_or_none` by `code` will crash if two workflows have the same phase code.

21. **Blocking Sync Operations in Async FastAPI Routes**
    - `interfaces/ui/routes/api.py`: `async def` endpoints call blocking SQLAlchemy logic natively, tanking concurrency.

22. **Silent State Failures**
    - `domain/fsm.py:47`: `apply_verdict` catches `MachineError` and silently returns the old state, masking errors.

23. **Arbitrary Rollbacks**
    - `wizard/checks.py:67`: `determine_verdict` forces rollback if the word "rollback" is anywhere in the report ("no rollback needed").

24. **Crashing Custom Patterns**
    - `domain/validation.py:169`: Custom pattern without named groups crashes with `IndexError`.

25. **Single-Char Prefix Rejection**
    - `domain/validation.py:173`: Legitimate 1-character prefixes overridden because `min_prefix_len` defaults to 2.

## LOW

26. **CLI Prompt Bug / Exit Code Inconsistency**
    - `interfaces/cli/ui.py:124` vs `wizard/core.py:516`: Legacy test-runner alias exits 1 if not PASS. `PARTIAL` and `DELEGATE` should be success codes.

27. **Missing Boolean Coercion on New Migration Flags**
    - `infrastructure/db/repositories/phase.py:68`: `update()` coerces `is_seed_managed` but forgets `is_blocker`, `is_delegated`, `is_critic`.

28. **Memory Leak in PromptCache**
    - `wizard/core.py:49`: `PromptCache.invalidate()` leaves old keys orphaned.

29. **Dead Code in Contracts**
    - `wizard/contracts.py:120`: Fallback logic for "researcher" delegate is dead code.

## Fix Status (review/full-audit)

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| 1 | Missing transaction rollbacks / UoW per request (app services, api routes) | HIGH | FIXED (07236ef) |
| 2 | Partial updates: disjoint commits in wizard evaluate() | HIGH | FIXED (f739c53) |
| 3 | XSS in phase_detail.html JS string interpolation | HIGH | FIXED (5054858) |
| 4 | PK corruption: phase update() allows id/workflow_id overwrite | HIGH | FIXED (fecdad6) |
| 5 | N+1: task/phase/project list without eager loading | HIGH | FIXED (fecdad6) |
| 6 | Instruction edits not persisted to seed | HIGH | FIXED (fecdad6) |
| 7 | Empty report bypasses coverage via previously_covered | HIGH | FIXED (45e4650) |
| 8 | False positive blockers/keywords via substring match | HIGH | FIXED (45e4650) |
| 9 | LLM verdict not coerced to DB enum before insert | HIGH | FIXED (45e4650) |
| 10 | Dead SQLite pragma listener (SA 2.0 API mismatch) | MEDIUM | FIXED (45e4650) |
| 11 | task_history FK mismatch with phase-code convention | HIGH | FIXED (45e4650) — exposed by pragma fix |
| 12 | Digit-only reject regex never fired (over-escaped) | MEDIUM | FIXED (45e4650) |
| 13 | api_phase_create 500 on missing workflow_id | MEDIUM | FIXED (45e4650) |
| 14 | CLI exit codes treat PARTIAL/DELEGATE as errors | MEDIUM | FIXED (6eb6a9a) |
