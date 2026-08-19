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

1. **Tests**
   ```bash
   pytest -q --timeout=60
   ```
   Expected: **865 passed, 11 deselected**, 0 failed, 0 errors. Integration tests
   are intentionally deselected here; run them separately as described below.

2. **PostgreSQL integration**
   ```bash
   pytest -q -m integration tests/test_postgres_integration.py --timeout=60
   ```
   Expected: **11 passed**, 0 failed, 0 errors. This includes the real CLI
   subprocess -> PostgreSQL -> OpenAI-compatible HTTP workflow path.

3. **Coverage**
   ```bash
   pytest --cov=project_workflow --cov-report=term --timeout=60
   ```
   Expected: total coverage >= 90%. Current baseline: **96.16%**.

4. **Lint**
   ```bash
   ruff check project_workflow tests
   ```
   Expected: `All checks passed!`

5. **Type check**
   ```bash
   mypy project_workflow
   ```
   Expected: `Success: no issues found in 81 source files`.

6. **UI service health**
   ```bash
   systemctl restart project-workflow-ui.service
   curl -s -o /dev/null -w "%{http_code}" http://localhost:8811/api/tasks
   ```
   Expected: `200`.

7. **Browser check** for UI changes
   - Open `http://localhost:8811/` and `http://localhost:8811/phases`.
   - Capture a screenshot.

## Notes

- Use `pytest -q --timeout=60` for the standard full suite. `--forked` is no longer required for stability; coverage reports are inaccurate under `--forked`.
- `DATABASE_URL` is required in runtime. SQLite is used only by isolated tests.
- The repeatable CLI workflow acceptance process is documented in `LIVE_TEST_PLAN.md`.

## Production-readiness — what we deliberately skip

This project is an internal lightweight agent utility, not a customer-facing production service. The following items were evaluated and explicitly rejected for this repo:

| Item | Decision | Rationale |
|---|---|---|
| CI/CD pipeline (GitLab/GitHub) | **Skip** | Repo is maintained manually; verification ritual above is sufficient. |
| Security middleware (CORS, CSP, HTTPS redirect, rate limits) | **Skip** | UI runs on a private host / VPN; no external exposure. |
| Hardcoded local credentials in `docker-compose.yml` | **Accept for dev only** | Compose stack is for local development; production uses env-provided `DATABASE_URL`. |
| Observability / metrics / structured JSON logs | **Skip** | Request logging middleware and `/health` endpoint provide enough visibility for an internal tool. |
| Input validation / sanitization hardening audit | **Skip** | API uses Pydantic schemas and SQLAlchemy ORM; raw SQL is limited to migration/admin scripts. |
| Graceful connection draining beyond lifespan dispose | **Skip** | Internal tool tolerance for brief connection drops is acceptable. |
| Backup/restore runbook | **Skip** | Data is seed-reproducible and task-level state is not business-critical. |
| Bandit/safety/pre-commit hooks | **Skip** | `ruff` + `mypy` + `pytest` coverage gate is the agreed quality bar. |
| Hardcoded internal URLs (`JIRA_BASE_URL`, `GITLAB_BASE_URL`) | **Accept** | These are stable internal endpoints; still overridable via env if needed in the future. |

If any of these assumptions change (e.g. external exposure, multi-user access, customer data), revisit this section before expanding scope.
