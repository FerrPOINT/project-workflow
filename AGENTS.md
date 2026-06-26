# AGENTS.md

## Repo rules

1. После завершения задачи нельзя оставлять готовую работу в незакоммиченном состоянии.
   - Сначала прогнать релевантные проверки.
   - Для UI-изменений обязательно сделать браузерную проверку и скриншот.
   - Затем сразу сделать git commit по выполненной задаче.

2. Не считать задачу завершённой, если рабочее дерево осталось dirty по её изменениям.

3. Merge и deploy запрещены без явной команды пользователя.

## Verification ritual

After any change to the SQLAlchemy layer, application services, UI state, or wizard engine, run the following checks before committing:

1. **Full test suite**
   ```bash
   pytest -q --timeout=60 --forked
   ```
   Expected: **869 passed, 6 deselected**, 0 failed, 0 errors.

2. **Lint**
   ```bash
   ruff check project_workflow tests
   ```
   Expected: `All checks passed!`

3. **Type check**
   ```bash
   mypy project_workflow
   ```
   Expected: `Success: no issues found in 57 source files`.

4. **UI service health**
   ```bash
   systemctl restart project-workflow-ui.service
   curl -s -o /dev/null -w "%{http_code}" http://localhost:8811/api/tasks
   ```
   Expected: `200`.

5. **Browser check** for UI changes
   - Open `http://localhost:8811/` and `http://localhost:8811/phases`.
   - Capture a screenshot.

## Notes

- `pytest -n auto` without `--forked` can hang on SQLite WAL due to FD exhaustion; use `--forked` for the full suite.
- `SAUnitOfWork()` with no arguments resolves PostgreSQL `DATABASE_URL` first, then falls back to SQLite `DB_PATH`. This is intentional to keep CLI/UI/test paths aligned.
- The in-repo skill `project-workflow-test-suite-recovery` contains the full checklist and failure-symptom table.
