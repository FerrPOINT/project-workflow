"""Integration tests against a real PostgreSQL instance.

These tests are skipped by default (`-m 'not integration'`).
Run them explicitly with:
    pytest -m integration tests/test_postgres_integration.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Barrier, Thread
from unittest.mock import patch
from urllib.request import urlopen

import psycopg
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from project_workflow import config as config_module
from project_workflow.infrastructure.db.session import (
    ensure_migrated,
    ensure_schema,
    get_engine,
    reset_engine,
    run_alembic_command,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork

REPO_ROOT = Path(__file__).resolve().parents[1]

PG_HOST = os.environ.get("PGHOST", "localhost")
PG_PORT = int(os.environ.get("PGPORT", "5432"))
PG_USER = os.environ.get("PGUSER", "project_workflow")
PG_PASSWORD = os.environ.get("PGPASSWORD", "project_workflow")
PG_ADMIN_DB = os.environ.get("PGDATABASE", "project_workflow")


@pytest.fixture(scope="function")
def pg_url(monkeypatch):
    """Create a fresh PostgreSQL database and yield a SQLAlchemy URL for it."""
    if not PG_PASSWORD:
        pytest.skip("PGPASSWORD is not set")
    pid = os.getpid()
    db_name = f"project_workflow_test_{pid}"
    base_url = f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{db_name}"

    admin_conn = psycopg.connect(host=PG_HOST, port=PG_PORT, dbname=PG_ADMIN_DB, user=PG_USER, password=PG_PASSWORD)
    admin_conn.autocommit = True
    with admin_conn.cursor() as cur:
        cur.execute("SET idle_in_transaction_session_timeout = 0")
        cur.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
        cur.execute(f"CREATE DATABASE {db_name}")
    admin_conn.close()

    monkeypatch.setenv("DATABASE_URL", base_url)
    monkeypatch.setenv("DB_SCHEMA", "project_workflow")
    config_module.get_settings.cache_clear()
    reset_engine()
    from project_workflow.infrastructure.db.schema import mark_catalog_not_ensured

    mark_catalog_not_ensured()

    yield base_url

    reset_engine()
    admin_conn = psycopg.connect(host=PG_HOST, port=PG_PORT, dbname=PG_ADMIN_DB, user=PG_USER, password=PG_PASSWORD)
    admin_conn.autocommit = True
    with admin_conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
    admin_conn.close()


@pytest.mark.integration
class TestPostgresSession:
    def test_get_engine_postgresql(self, pg_url):
        engine = get_engine(pg_url)
        assert engine.dialect.name == "postgresql"
        assert engine.url.database == pg_url.rsplit("/", 1)[-1]

    def test_ensure_schema_creates_tables(self, pg_url):
        engine = get_engine(pg_url)
        ensure_schema(engine)
        with engine.connect() as conn:
            from sqlalchemy import text

            rows = conn.execute(
                text("""SELECT table_name FROM information_schema.tables
                       WHERE table_schema='project_workflow'""")
            ).fetchall()
            tables = {r[0] for r in rows}
        assert "workflows" in tables
        assert "projects" in tables
        assert "tasks" in tables

    def test_ensure_migrated_applies_migrations(self, pg_url):
        engine = get_engine(pg_url)
        ensure_migrated(engine)
        with engine.connect() as conn:
            from sqlalchemy import text

            version = conn.execute(text("SELECT version_num FROM project_workflow.alembic_version")).scalar()
        inspector = inspect(engine)
        columns = {column["name"] for column in inspector.get_columns("agents", schema="project_workflow")}
        indexes = {index["name"] for index in inspector.get_indexes("agents", schema="project_workflow")}
        assert version == "c31a9f6d4e20"
        assert "hermes_profile" in columns
        assert "uq_agents_hermes_profile" in indexes

    def test_hermes_profile_migration_preserves_agents_and_enforces_unique_owner(self, pg_url):
        engine = get_engine(pg_url)
        run_alembic_command("upgrade", engine, "b7f3c9d2a641")
        with engine.begin() as conn:
            agent_id = conn.execute(
                text("INSERT INTO project_workflow.agents (name, description) VALUES ('Existing', '') RETURNING id")
            ).scalar_one()

        ensure_migrated(engine)
        with engine.connect() as conn:
            preserved = conn.execute(
                text("SELECT name, hermes_profile FROM project_workflow.agents WHERE id = :id"),
                {"id": agent_id},
            ).one()
        assert preserved.name == "Existing"
        assert preserved.hermes_profile is None

        with engine.begin() as conn:
            conn.execute(
                text("UPDATE project_workflow.agents SET hermes_profile = 'shared_profile' WHERE id = :id"),
                {"id": agent_id},
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.agents (name, description, hermes_profile) "
                        "VALUES ('Duplicate', '', 'shared_profile')"
                    )
                )

    def test_upgrade_preserves_existing_run_and_creates_unique_index(self, pg_url):
        from project_workflow.infrastructure.db import schema
        from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

        engine = get_engine(pg_url)
        ensure_migrated(engine)
        uow = SAUnitOfWork(engine)
        schema.ensure_phase_catalog(uow)
        bootstrap_default_project(uow)
        project = uow.projects.get_by_code("TASK")
        phase = uow.phases.list(workflow_id=project.workflow_id)[0]
        task_id = uow.tasks.create(
            {"project_id": project.id, "task_key": "TASK-MIGRATION", "current_phase": phase.code}
        )
        run_id = uow.supervisor_runs.create(
            {"task_id": task_id, "phase_id": phase.id, "verdict": "partial", "report": "old"}
        )
        uow.commit()
        uow.close()

        run_alembic_command("downgrade", engine, "becf90549ae1")
        assert "report_fingerprint" not in {
            column["name"] for column in inspect(engine).get_columns("supervisor_runs", schema="project_workflow")
        }
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO project_workflow.supervisor_runs "
                    "(task_id, phase_id, verdict, report) VALUES "
                    "(:task_id, :phase_id, 'soft_fail', 'legacy soft'), "
                    "(:task_id, :phase_id, 'hard_fail', 'legacy hard')"
                ),
                {"task_id": task_id, "phase_id": phase.id},
            )
        ensure_migrated(engine)
        ensure_migrated(engine)

        columns = {
            column["name"] for column in inspect(engine).get_columns("supervisor_runs", schema="project_workflow")
        }
        indexes = {index["name"] for index in inspect(engine).get_indexes("supervisor_runs", schema="project_workflow")}
        assert "report_fingerprint" in columns
        assert "uq_supervisor_runs_task_report_fingerprint" in indexes
        check_uow = SAUnitOfWork(engine)
        try:
            runs = check_uow.supervisor_runs.list(task_id=task_id)
            assert any(run.id == run_id for run in runs)
            assert {run.verdict for run in runs} == {"partial", "blocked"}
        finally:
            check_uow.close()

        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.supervisor_runs "
                        "(task_id, phase_id, verdict, report) "
                        "VALUES (:task_id, :phase_id, 'soft_fail', 'rejected')"
                    ),
                    {"task_id": task_id, "phase_id": phase.id},
                )

    def test_catalog_upgrade_replaces_legacy_contracts_and_preserves_audit(self, pg_url):
        from project_workflow.infrastructure.db import schema
        from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

        engine = get_engine(pg_url)
        run_alembic_command("upgrade", engine, "f61c2a7d9e04")
        uow = SAUnitOfWork(engine)
        schema.ensure_phase_catalog(uow)
        bootstrap_default_project(uow)
        project = uow.projects.get_by_code("TASK")
        phase = uow.phases.get_by_code("0.0a")
        assert phase is not None
        task_id = uow.tasks.create(
            {"project_id": project.id, "task_key": "TASK-CATALOG-MIGRATION", "current_phase": phase.code}
        )
        run_id = uow.supervisor_runs.create(
            {"task_id": task_id, "phase_id": phase.id, "verdict": "blocked", "report": "preserved audit"}
        )
        phase_id = phase.id
        uow.commit()
        uow.close()

        with engine.begin() as conn:
            conn.execute(
                text("UPDATE project_workflow.phases SET name = 'Suite Verification' WHERE id = :phase_id"),
                {"phase_id": phase_id},
            )
            conn.execute(
                text("DELETE FROM project_workflow.checks WHERE phase_id = :phase_id"),
                {"phase_id": phase_id},
            )
            conn.execute(
                text(
                    "INSERT INTO project_workflow.checks (phase_id, description) "
                    "VALUES (:phase_id, 'JIRA_ACCESS_TOKEN, GLAB_TOKEN and verify-suite are required')"
                ),
                {"phase_id": phase_id},
            )
            conn.execute(
                text(
                    "UPDATE project_workflow.instructions SET description = 'Write mandatory PLAN.md' "
                    "WHERE phase_id = (SELECT id FROM project_workflow.phases WHERE code = '3')"
                )
            )

        ensure_migrated(engine)
        ensure_migrated(engine)

        with engine.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM project_workflow.alembic_version")).scalar_one()
            upgraded = conn.execute(
                text(
                    "SELECT p.id, p.name, string_agg(items.description, ' ') "
                    "FROM project_workflow.phases p "
                    "JOIN ("
                    "SELECT phase_id, description FROM project_workflow.instructions "
                    "UNION ALL SELECT phase_id, description FROM project_workflow.checks "
                    "UNION ALL SELECT phase_id, description FROM project_workflow.evidence"
                    ") items ON items.phase_id = p.id "
                    "WHERE p.id = :phase_id GROUP BY p.id, p.name"
                ),
                {"phase_id": phase_id},
            ).one()
            legacy_count = conn.execute(
                text(
                    "SELECT count(*) FROM ("
                    "SELECT name AS value FROM project_workflow.phases "
                    "UNION ALL SELECT description FROM project_workflow.instructions "
                    "UNION ALL SELECT description FROM project_workflow.checks "
                    "UNION ALL SELECT description FROM project_workflow.evidence"
                    ") catalog WHERE lower(value) ~ 'jira|gitlab|glab_token|verify-suite|mandatory plan.md'"
                )
            ).scalar_one()
        assert revision == "c31a9f6d4e20"
        assert upgraded.id == phase_id
        assert upgraded.name == "Runtime Readiness"
        active_contract = upgraded.string_agg.casefold()
        assert all(
            term not in active_contract
            for term in ("jira", "gitlab", "glab_token", "verify-suite", "hermes")
        )
        assert legacy_count == 0

        check_uow = SAUnitOfWork(engine)
        try:
            task = check_uow.tasks.get_by_key("TASK-CATALOG-MIGRATION")
            runs = check_uow.supervisor_runs.list(task_id=task.id)
            assert task.id == task_id
            assert any(run.id == run_id and run.report == "preserved audit" for run in runs)
        finally:
            check_uow.close()

    def test_skill_backfill_updates_only_empty_default_seed_instructions(self, pg_url):
        from project_workflow.infrastructure.db import schema
        from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

        engine = get_engine(pg_url)
        run_alembic_command("upgrade", engine, "e92c4f7a1b63")
        uow = SAUnitOfWork(engine)
        schema.ensure_phase_catalog(uow)
        bootstrap_default_project(uow)
        project = uow.projects.get_by_code("TASK")
        phase = uow.phases.get_by_code("0.9")
        task_id = uow.tasks.create(
            {"project_id": project.id, "task_key": "TASK-SKILL-MIGRATION", "current_phase": phase.code}
        )
        run_id = uow.supervisor_runs.create(
            {"task_id": task_id, "phase_id": phase.id, "verdict": "partial", "report": "preserved"}
        )
        custom_workflow_id = uow.workflows.create(
            {"name": "Custom Workflow", "description": "custom", "is_default": False}
        )
        custom_phase_id = uow.phases.create(
            {
                "workflow_id": custom_workflow_id,
                "code": "0.9",
                "name": "Custom phase",
                "phase_order": 1,
                "is_seed_managed": True,
            }
        )
        custom_instruction_id = uow.instructions.create(
            custom_phase_id, {"step_num": 1, "description": "Custom instruction", "skills": None}
        )
        uow.commit()
        uow.close()

        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE project_workflow.instructions SET skills = CASE step_num "
                    "WHEN 1 THEN NULL WHEN 2 THEN '' WHEN 3 THEN '[]' END "
                    "WHERE phase_id = :phase_id"
                ),
                {"phase_id": phase.id},
            )
            custom_value = '["ui-custom"]'
            conn.execute(
                text(
                    "UPDATE project_workflow.instructions SET skills = :skills "
                    "WHERE phase_id = (SELECT id FROM project_workflow.phases "
                    "WHERE workflow_id = :workflow_id AND code = '0.6') AND step_num = 1"
                ),
                {"skills": custom_value, "workflow_id": project.workflow_id},
            )

        ensure_migrated(engine)
        ensure_migrated(engine)

        with engine.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM project_workflow.alembic_version")).scalar_one()
            migrated = conn.execute(
                text(
                    "SELECT step_num, skills FROM project_workflow.instructions "
                    "WHERE phase_id = :phase_id ORDER BY step_num"
                ),
                {"phase_id": phase.id},
            ).all()
            preserved_custom = conn.execute(
                text(
                    "SELECT skills FROM project_workflow.instructions "
                    "WHERE phase_id = (SELECT id FROM project_workflow.phases "
                    "WHERE workflow_id = :workflow_id AND code = '0.6') AND step_num = 1"
                ),
                {"workflow_id": project.workflow_id},
            ).scalar_one()
            custom_workflow_skills = conn.execute(
                text("SELECT skills FROM project_workflow.instructions WHERE id = :instruction_id"),
                {"instruction_id": custom_instruction_id},
            ).scalar_one()

        assert revision == "c31a9f6d4e20"
        assert [json.loads(row.skills) for row in migrated] == [
            ["agent-workflow-patterns"],
            ["workflow-systematic-debugging"],
            ["agent-workflow-patterns"],
        ]
        assert preserved_custom == custom_value
        assert custom_workflow_skills is None

        check_uow = SAUnitOfWork(engine)
        try:
            task = check_uow.tasks.get_by_key("TASK-SKILL-MIGRATION")
            runs = check_uow.supervisor_runs.list(task_id=task.id)
            assert task.id == task_id
            assert any(run.id == run_id and run.report == "preserved" for run in runs)
        finally:
            check_uow.close()


@pytest.mark.integration
class TestPostgresUoW:
    def test_create_and_read_workflow_project_task(self, pg_url):
        uow = SAUnitOfWork(pg_url)
        with uow:
            uow.create_all()
            wf_id = uow.workflows.create({"name": "Test Workflow", "description": "Test", "is_default": True})
            workflows = {w.name: w.id for w in uow.workflows.list()}
            assert workflows.get("Test Workflow") == wf_id

            proj_id = uow.projects.create({"workflow_id": wf_id, "code": "TST", "name": "Default"})
            projects = {p.code: p.id for p in uow.projects.list()}
            assert projects.get("TST") == proj_id

            task_id = uow.tasks.create(
                {
                    "project_id": proj_id,
                    "code": "TST-1",
                    "task_key": "TST-1",
                    "title": "First task",
                }
            )
            tasks = {t.task_key: t.id for t in uow.tasks.list()}
            assert tasks.get("TST-1") == task_id
            uow.commit()

    def test_ensure_phase_catalog_does_not_overwrite_existing_workflow(self, pg_url):
        from project_workflow.infrastructure.db import schema as schema_module

        uow = SAUnitOfWork(pg_url)
        with uow:
            uow.create_all()
            default_wf_id = uow.workflows.create({"name": "Default", "description": "default", "is_default": True})
            uow.projects.create({"workflow_id": default_wf_id, "code": "DEFAULT", "name": "Default Project"})
            uow.commit()

        schema_module.ensure_phase_catalog(uow)
        with uow:
            default_wf = uow.workflows.get_default()
            phases = uow.phases.list(workflow_id=default_wf.id)
            assert phases == []

    def test_uow_commit_and_rollback(self, pg_url):
        uow = SAUnitOfWork(pg_url)
        with uow:
            uow.create_all()
            wf_id = uow.workflows.create({"name": "Rollback WF", "description": "rollback"})
            uow.rollback()

        with uow:
            ids = {w.id for w in uow.workflows.list()}
            assert wf_id not in ids


def _pass_response(user_prompt: str) -> dict:
    item_ids = []
    for line in user_prompt.splitlines():
        stripped = line.strip()
        if stripped.startswith('ID: "') and '" — ' in stripped:
            item_ids.append(stripped[5:].split('" — ', 1)[0])
    return {
        "verdict": "PASS",
        "covered": item_ids,
        "missing": [],
        "blockers": [],
        "message": "ok",
        "confidence": 1.0,
    }


def _prepare_concurrent_task(pg_url: str, task_key: str) -> None:
    from project_workflow.infrastructure.db import schema
    from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

    engine = get_engine(pg_url)
    ensure_migrated(engine)
    uow = SAUnitOfWork(engine)
    schema.ensure_phase_catalog(uow)
    bootstrap_default_project(uow)
    project = uow.projects.get_by_code("TASK")
    phase = uow.phases.list(workflow_id=project.workflow_id)[0]
    uow.tasks.create({"project_id": project.id, "task_key": task_key, "current_phase": phase.code})
    uow.commit()
    uow.close()


@pytest.mark.integration
@pytest.mark.parametrize("same_report", [True, False])
def test_concurrent_reports_create_one_transition_and_run(pg_url, same_report):
    from project_workflow.wizard import WizardEngine

    task_key = "TASK-CONCURRENT"
    _prepare_concurrent_task(pg_url, task_key)
    barrier = Barrier(2)

    def evaluate(report: str):
        uow = SAUnitOfWork(pg_url)
        engine = WizardEngine(task_key, uow=uow, create_if_missing=False)
        barrier.wait()
        try:
            return engine.evaluate(report)
        finally:
            uow.close()

    reports = ["same report", "same report" if same_report else "different report"]
    with (
        patch(
            "project_workflow.wizard.evaluate.OpenAICompatibleClient.chat",
            side_effect=lambda *_args, **kwargs: _pass_response(kwargs["user"]),
        ),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = list(pool.map(evaluate, reports))

    uow = SAUnitOfWork(pg_url)
    task = uow.tasks.get_by_key(task_key)
    runs = uow.supervisor_runs.list(task_id=task.id)
    history = uow.tasks.get_history(task.id)
    uow.close()

    assert len(runs) == 1
    assert history
    assert sum(result["verdict"] == "PASS" for result in results) == (2 if same_report else 1)
    if same_report:
        assert sum(result["replayed"] is True for result in results) == 1
    else:
        assert sum(result["verdict"] == "BLOCKED" and result["retryable"] is True for result in results) == 1


class _ProviderState:
    def __init__(self) -> None:
        self.chat_requests: list[dict] = []
        self.chat_phases: list[str] = []
        self.model_requests = 0


@contextmanager
def _openai_compatible_server():
    state = _ProviderState()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != "/v1/models":
                self._send_json(404, {"error": "not found"})
                return
            state.model_requests += 1
            self._send_json(200, {"object": "list", "data": [{"id": "e2e-contract-model"}]})

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self._send_json(404, {"error": "not found"})
                return
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            state.chat_requests.append(payload)
            user_prompt = str(payload["messages"][-1]["content"])
            phase_line = next(line for line in user_prompt.splitlines() if line.startswith("CURRENT PHASE:"))
            state.chat_phases.append(phase_line.split(":", 1)[1].split(" — ", 1)[0].strip())
            item_ids = [
                line.strip()[5:].split('" — ', 1)[0]
                for line in user_prompt.splitlines()
                if line.strip().startswith('ID: "') and '" — ' in line
            ]

            if "MODE=HTTP_ERROR" in user_prompt:
                self._send_json(503, {"error": "provider unavailable"})
                return
            if "MODE=INVALID" in user_prompt:
                content = "not-json"
            else:
                verdict = "PASS"
                covered = item_ids
                missing: list[str] = []
                blockers: list[str] = []
                if "MODE=PARTIAL" in user_prompt:
                    verdict, covered, missing = "PARTIAL", item_ids[:1], item_ids[1:] or item_ids
                elif "MODE=BLOCKED" in user_prompt:
                    verdict, covered, missing, blockers = "BLOCKED", [], item_ids, ["Controlled test blocker"]
                elif "MODE=ROLLBACK" in user_prompt:
                    verdict, covered, missing = "ROLLBACK", [], item_ids
                elif "MODE=DELEGATE" in user_prompt:
                    verdict, covered, missing = "DELEGATE", [], item_ids
                content = json.dumps(
                    {
                        "verdict": verdict,
                        "covered": covered,
                        "missing": missing,
                        "blockers": blockers,
                        "message": f"Controlled {verdict}",
                        "confidence": 1.0,
                    }
                )
            self._send_json(
                200,
                {
                    "id": "chatcmpl-e2e",
                    "object": "chat.completion",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
                },
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _cli_env(pg_url: str, provider_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": pg_url,
            "DB_SCHEMA": "project_workflow",
            "OPENAI_BASE_URL": provider_url,
            "OPENAI_MODEL": "e2e-contract-model",
            "OPENAI_TIMEOUT": "10",
            "OPENAI_API_KEY": "integration-test-key",
            "PYTHONUTF8": "1",
        }
    )
    env.pop("PYTHONIOENCODING", None)
    return env


def _run_process(
    args: list[str], env: dict[str, str], *, encoding: str = "utf-8"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding=encoding,
        timeout=30,
        check=False,
    )


def _run_cli(env: dict[str, str], *args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = _run_process(["-m", "project_workflow.interfaces.cli", *args], env)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"CLI did not return JSON: stdout={result.stdout!r}, stderr={result.stderr!r}") from exc
    return result, payload


def _initialize_cli_database(env: dict[str, str]) -> None:
    result = _run_process(["scripts/init_db.py"], env)
    assert result.returncode == 0, result.stderr or result.stdout


def _step(env: dict[str, str], task_key: str, report: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    return _run_cli(env, "--json", "step", "--task", task_key, "--report", report)


@pytest.mark.integration
@pytest.mark.timeout(120)
def test_full_wizard_runtime_through_cli_postgres_and_http(pg_url):
    expected_phases = [
        "-1",
        "0.0a",
        "0.01",
        "0.000",
        "0.00",
        "0.7",
        "0.9",
        "0.5",
        "0.6",
        "1.5",
        "3",
        "3.5",
        "4",
        "4.5",
        "5.5",
        "6",
        "7",
        "7.5",
        "7.7",
        "8",
        "9",
        "10",
    ]
    expected_groups = {
        "0.6": ["0.6", "1"],
        "1.5": ["1.5", "2"],
        "4.5": ["4.5", "5"],
        "7.5": ["7.5", "7.6", "7.6.R"],
    }
    task_key = "TASK-82001"

    with _openai_compatible_server() as (provider_url, provider_state):
        env = _cli_env(pg_url, provider_url)
        _initialize_cli_database(env)
        with urlopen(f"{provider_url}/models", timeout=5) as response:
            assert response.status == 200

        bootstrap_uow = SAUnitOfWork(pg_url)
        try:
            workflows = list(bootstrap_uow.workflows.list())
            projects = list(bootstrap_uow.projects.list())
            assert [workflow.name for workflow in workflows] == [config_module.DEFAULT_WORKFLOW_NAME]
            assert [project.code for project in projects] == ["TASK"]
            assert len(bootstrap_uow.phases.list(workflow_id=workflows[0].id)) == 27
        finally:
            bootstrap_uow.close()

        first_report = "E2E report 1 for phase -1"
        for index, expected_phase in enumerate(expected_phases, start=1):
            report = first_report if index == 1 else f"E2E report {index} for phase {expected_phase}"
            result, payload = _step(env, task_key, report)
            assert result.returncode == 0, result.stderr or result.stdout
            assert payload["verdict"] == "PASS"
            assert payload["phase"] == expected_phase
            assert payload["group_phases"] == expected_groups.get(expected_phase)

            if index == 1:
                request_count = len(provider_state.chat_requests)
                replay_result, replay = _step(env, task_key, first_report)
                assert replay_result.returncode == 0
                assert replay["replayed"] is True
                assert len(provider_state.chat_requests) == request_count

            if expected_phase == "0.6":
                assert payload["next_phase"] == "1.5"
                assert payload["next_phase_contract"]["group_phases"] == ["1.5", "2"]
                assert any(
                    "Используй skills: workflow-code-intelligence." in instruction
                    for instruction in payload["next_phase_contract"]["instructions"]
                )
                uow = SAUnitOfWork(pg_url)
                task = uow.tasks.get_by_key(task_key)
                project = uow.projects.get_by_id(task.project_id)
                phases = {phase.id: phase.code for phase in uow.phases.list(workflow_id=project.workflow_id)}
                statuses = {phases[row["phase_id"]]: row["status"] for row in uow.tasks.get_history(task.id)}
                assert task.current_phase == "1.5"
                assert statuses["1.5"] == "pending"
                assert statuses.get("2") != "done"
                uow.close()

            if expected_phase == "1.5":
                assert payload["next_phase"] == "3"

            if expected_phase == "3":
                assert payload["next_phase_contract"]["group_phases"] is None
                assert any(
                    "Используй skills: agent-workflow-patterns." in instruction
                    for instruction in payload["next_phase_contract"]["instructions"]
                )

        terminal_result, terminal = _run_cli(env, "--json", "step", "--task", task_key)
        history_result, history_payload = _run_cli(env, "--json", "history", "--task", task_key)
        assert terminal_result.returncode == history_result.returncode == 0
        assert terminal["phase"] == "10"
        assert terminal["status"] == "done"
        assert history_payload["count"] == 22

        completed_request_count = len(provider_state.chat_requests)
        completed_result, completed = _step(env, task_key, "New report after workflow completion")
        assert completed_result.returncode == 0
        assert completed["verdict"] == "PASS"
        assert completed["status"] == "done"
        assert completed["next_phase"] is None
        assert "уже завершён" in completed["message"]
        assert len(provider_state.chat_requests) == completed_request_count

        human_env = env.copy()
        human_env.update({"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1251"})
        human_step = _run_process(
            ["-m", "project_workflow.interfaces.cli", "step", "--task", task_key],
            human_env,
            encoding="cp1251",
        )
        assert human_step.returncode == 0
        assert "Auto-Improve" in human_step.stdout
        assert "UnicodeEncodeError" not in human_step.stderr

        assert provider_state.model_requests == 1
        assert len(provider_state.chat_requests) == 22
        assert provider_state.chat_phases == expected_phases
        assert all(request["model"] == "e2e-contract-model" for request in provider_state.chat_requests)

    uow = SAUnitOfWork(pg_url)
    task = uow.tasks.get_by_key(task_key)
    runs = list(uow.supervisor_runs.list(task_id=task.id, limit=100))
    task_history = list(uow.tasks.get_history(task.id))
    assert task.current_phase == "10"
    assert task.status == "done"
    assert len(runs) == 22
    assert len(task_history) == 27
    assert all(row["status"] == "done" for row in task_history)
    fingerprints = [run.report_fingerprint for run in runs]
    assert all(fingerprints)
    assert len(set(fingerprints)) == 22
    assert all(run.context_snapshot["model"] == "e2e-contract-model" for run in runs)
    assert all(run.context_snapshot["endpoint_mode"] == "openai-compatible" for run in runs)
    assert all(run.context_snapshot["prompt_version"] == "wizard-evaluator-v4" for run in runs)
    assert all(run.context_snapshot["raw_evaluator"]["verdict"] == "PASS" for run in runs)
    uow.close()


def _advance_to_phase(env: dict[str, str], task_key: str, phases: list[str]) -> None:
    for index, phase in enumerate(phases, start=1):
        result, payload = _step(env, task_key, f"Advance {index} through {phase}")
        assert result.returncode == 0
        assert payload["verdict"] == "PASS"
        assert payload["phase"] == phase


@pytest.mark.integration
@pytest.mark.timeout(120)
def test_cli_verdicts_replay_and_fail_closed_through_postgres_and_http(pg_url):
    with _openai_compatible_server() as (provider_url, provider_state):
        env = _cli_env(pg_url, provider_url)
        _initialize_cli_database(env)

        partial_result, partial = _step(env, "TASK-82002", "MODE=PARTIAL incomplete report")
        request_count = len(provider_state.chat_requests)
        replay_result, replay = _step(env, "TASK-82002", "MODE=PARTIAL incomplete report")
        assert partial_result.returncode == replay_result.returncode == 0
        assert partial["verdict"] == replay["verdict"] == "PARTIAL"
        assert replay["replayed"] is True
        assert len(provider_state.chat_requests) == request_count

        blocked_result, blocked = _step(env, "TASK-82003", "MODE=BLOCKED blocked report")
        assert blocked_result.returncode == 1
        assert blocked["verdict"] == "BLOCKED"
        assert blocked["retryable"] is False

        invalid_result, invalid = _step(env, "TASK-82004", "MODE=INVALID invalid response")
        invalid_retry_result, invalid_retry = _step(env, "TASK-82004", "MODE=INVALID invalid response")
        assert invalid_result.returncode == invalid_retry_result.returncode == 1
        assert invalid["verdict"] == invalid_retry["verdict"] == "BLOCKED"
        assert invalid["retryable"] is invalid_retry["retryable"] is True
        assert invalid["replayed"] is invalid_retry["replayed"] is False

        http_result, http_error = _step(env, "TASK-82005", "MODE=HTTP_ERROR provider error")
        assert http_result.returncode == 1
        assert http_error["verdict"] == "BLOCKED"
        assert http_error["retryable"] is True

        phases_before_rollback = ["-1", "0.0a", "0.01", "0.000", "0.00", "0.7"]
        _advance_to_phase(env, "TASK-82006", phases_before_rollback)
        rollback_result, rollback = _step(env, "TASK-82006", "MODE=ROLLBACK return to suite verification")
        assert rollback_result.returncode == 0
        assert rollback["verdict"] == "ROLLBACK"
        assert rollback["rollback_target"] == "0.0a"

        _advance_to_phase(env, "TASK-82007", phases_before_rollback)
        delegate_result, delegate = _step(env, "TASK-82007", "MODE=DELEGATE hand off review")
        assert delegate_result.returncode == 0
        assert delegate["verdict"] == "DELEGATE"

    uow = SAUnitOfWork(pg_url)
    partial_task = uow.tasks.get_by_key("TASK-82002")
    blocked_task = uow.tasks.get_by_key("TASK-82003")
    invalid_task = uow.tasks.get_by_key("TASK-82004")
    http_task = uow.tasks.get_by_key("TASK-82005")
    rollback_task = uow.tasks.get_by_key("TASK-82006")
    delegate_task = uow.tasks.get_by_key("TASK-82007")
    assert (partial_task.current_phase, partial_task.status) == ("-1", "active")
    assert (blocked_task.current_phase, blocked_task.status) == ("-1", "blocked")
    assert (invalid_task.current_phase, invalid_task.status) == ("-1", "active")
    assert (http_task.current_phase, http_task.status) == ("-1", "active")
    assert (rollback_task.current_phase, rollback_task.status) == ("0.0a", "active")
    assert (delegate_task.current_phase, delegate_task.status) == ("0.9", "active")
    invalid_runs = list(uow.supervisor_runs.list(task_id=invalid_task.id, limit=10))
    assert len(invalid_runs) == 2
    assert all(run.report_fingerprint is None for run in invalid_runs)
    assert uow.tasks.get_history(invalid_task.id) == []
    assert uow.tasks.get_history(http_task.id) == []
    uow.close()
