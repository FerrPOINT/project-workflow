"""Current HTTP protocol and real PostgreSQL locks; external authorities are fakes."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from project_workflow import config
from project_workflow.application import configured_cli
from project_workflow.application import state as app_state
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.session import ensure_migrated, get_engine
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces import ui as ui_package
from project_workflow.interfaces.ui import state as ui_state
from tests import test_configured_cli as protocol
from tests.test_postgres_integration import pg_url as pg_url

pytestmark = pytest.mark.integration


@pytest.fixture
def configured(pg_url, monkeypatch, request):
    engine = get_engine(pg_url)
    assert engine.dialect.name == "postgresql"
    ensure_migrated(engine)
    state = app_state._AppState(database_url=pg_url)
    for module in (app_state, ui_state, ui_package):
        monkeypatch.setattr(module, "_app_state", state)
    config.get_settings.cache_clear()
    yield from protocol.configured.__wrapped__(monkeypatch, request)


@pytest.mark.parametrize("configured", [("developer", "initial")], indirect=True)
@pytest.mark.parametrize("prompt_version", ["supervisor-evaluator-v9", "supervisor-evaluator-v8-no-backtracking"])
def test_seeded_terminal_history_survives_prompt_upgrade(configured, supervisor_llm, monkeypatch, prompt_version):
    from tests.test_frozen_evaluation import test_prompt_upgrade_keeps_frozen_terminal_readback_and_replay

    test_prompt_upgrade_keeps_frozen_terminal_readback_and_replay(
        configured, supervisor_llm, monkeypatch, prompt_version,
    )


def test_seeded_summary_retains_rollback_without_changing_full_history(configured):
    from tests.test_runtime_history_summary import (
        history,
        test_summary_whitelists_saved_values_without_changing_full_history,
    )

    test_summary_whitelists_saved_values_without_changing_full_history(history.__wrapped__(configured))


def test_seeded_native_history_stays_read_only_without_the_old_image(pg_url, monkeypatch):
    from tests._retained_pm_history import retained_pm
    from tests.test_retained_pm_readers import test_saved_pm_history_survives_foreign_or_unavailable_current_image

    engine = get_engine(pg_url)
    assert engine.dialect.name == "postgresql"
    ensure_migrated(engine)
    state = app_state._AppState(database_url=pg_url)
    for module in (app_state, ui_state, ui_package):
        monkeypatch.setattr(module, "_app_state", state)
    config.get_settings.cache_clear()
    historical = retained_pm(monkeypatch)
    try:
        test_saved_pm_history_survives_foreign_or_unavailable_current_image(next(historical), monkeypatch)
    finally:
        historical.close()


@pytest.mark.parametrize("configured", [
    ("project_manager", "draft"), ("analyst", "analysis"), ("architect", "decomposition"),
    ("developer", "initial"), ("developer", "rework"), ("reviewer", "delivery"),
    ("tester", "delivery"), ("devops", "delivery"),
], indirect=True)
def test_all_professions_persist_three_phases_and_exact_replays(configured, supervisor_llm, monkeypatch):
    initial = protocol.enroll(configured)
    supervisor_llm("PASS")
    pm = configured[1]["role_key"] == "project_manager"
    confirmation = {
        "id": str(uuid4()), "task_id": protocol.TRACKER_TASK, "revision": 7,
        "content_hash": "a" * 64, "owner_subject": protocol.OWNER, "stage": "Draft",
    }
    monkeypatch.setattr(configured_cli, "confirmation", lambda _payload: confirmation)
    for version in (1, 2, 3):
        command = {
            "report": f"Controlled completed phase {version}",
            "operation_key": f"pg-report-{version}", "expected_version": version,
        }
        if pm and version == 3:
            command.update(requirements_revision=7, requirements_sha256="a" * 64)
        response = protocol.step(configured, **command)
        assert response.status_code == 200, response.text
        assert protocol.step(configured, **command).json() == response.json()
    result = response.json()["result"]
    assert result["complete"] is True and result["version"] == 4
    assert result["execution_ref"] == initial["execution_ref"]
    assert result["terminal_receipt"]["confirmation_id"] == (confirmation["id"] if pm else None)
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 3
        assert uow.session.scalar(select(func.count()).select_from(m.PMExecution)) == 0
        assert uow.session.scalar(select(func.count()).select_from(m.PMRun)) == 0


@pytest.mark.parametrize("configured", [("developer", "initial")], indirect=True)
@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_reports_have_one_committed_transition(configured, supervisor_llm, monkeypatch, same_key):
    from project_workflow.infrastructure.llm import OpenAICompatibleClient

    protocol.enroll(configured)
    supervisor_llm("PASS")
    evaluate = OpenAICompatibleClient.chat
    barrier = Barrier(2)

    def chat(*args, **kwargs):
        barrier.wait(timeout=15)
        return evaluate(*args, **kwargs)

    monkeypatch.setattr(OpenAICompatibleClient, "chat", chat)

    def submit(index):
        return protocol.step(configured, report="One exact report", expected_version=1,
                             operation_key="same" if same_key else f"distinct-{index}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, (1, 2)))
    assert sorted(row.status_code for row in responses) == ([200, 200] if same_key else [200, 409])
    if same_key:
        assert responses[0].json() == responses[1].json()
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 1
    assert protocol.step(configured).json()["result"]["version"] == 2


@pytest.mark.parametrize("configured", [("developer", "initial")], indirect=True)
def test_assignment_changed_during_evaluation_cannot_publish_old_report(configured, supervisor_llm, monkeypatch):
    from project_workflow.infrastructure.llm import OpenAICompatibleClient

    protocol.enroll(configured)
    supervisor_llm("PASS")
    evaluate = OpenAICompatibleClient.chat
    entered, release = Event(), Event()

    def chat(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=15)
        return evaluate(*args, **kwargs)

    monkeypatch.setattr(OpenAICompatibleClient, "chat", chat)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(protocol.step, configured, report="Old assignment report",
                             operation_key="old-report", expected_version=1)
        try:
            assert entered.wait(timeout=15)
            replacement = {
                **configured[1], "assignment_ref": str(uuid4()), "tracker_execution_id": str(uuid4()),
                "assignment_version": 2, "operation_key": "pg-replacement", "expected_version": 1,
            }
            response = configured[0].post("/internal/runtime/assign", headers=protocol.WRITER, json=replacement)
            assert response.status_code == 200, response.text
        finally:
            release.set()
        old = future.result(timeout=15)
    assert old.status_code == 409, old.text
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 0
    current = protocol.step(configured).json()["result"]
    assert current["version"] == 2 and current["assignment_ref"] == replacement["assignment_ref"]


@pytest.fixture
def cli_server(configured):
    import socket
    import time
    from threading import Thread

    import uvicorn

    # The existing TestClient owns application startup and the disposable PG
    # fixture. Serve that actual app over HTTP without a second startup/reset.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(configured[0].app, log_level="error", lifespan="off"))
    thread = Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "Actual configured API server did not start"
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive(), "Configured API test server did not stop"


@pytest.mark.parametrize("configured", [("project_manager", "draft"), ("developer", "rework")], indirect=True)
def test_cli_process_http_and_postgres_keep_one_report_and_no_workflow_files(
    configured, cli_server, supervisor_llm, monkeypatch, tmp_path,
):
    import importlib.util
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    assert importlib.util.find_spec("pdlc_cli_core"), "Install the qualified Base cli-core package before this gate"
    initial = protocol.enroll(configured)
    supervisor_llm("PASS")
    confirmation = {"id": str(uuid4()), "task_id": protocol.TRACKER_TASK, "revision": 7,
                    "content_hash": "a" * 64, "owner_subject": protocol.OWNER, "stage": "Draft"}
    monkeypatch.setattr(configured_cli, "confirmation", lambda _: confirmation)
    environment = {**os.environ, "PROJECT_WORKFLOW_URL": cli_server,
                   "PROJECT_WORKFLOW_API_TOKEN": protocol.MACHINE["Authorization"].removeprefix("Bearer "),
                   "FLEET_AGENT_ID": protocol.AGENT,
                   "PROJECT_WORKFLOW_NAMESPACE_ID": str(configured[1]["namespace_id"]),
                   "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
    for key in ("DATABASE_URL", "TASK_WORKFLOW_DB", "PROJECT_WORKFLOW_DATABASE_URL"):
        environment.pop(key, None)
    before = set(tmp_path.rglob("*"))

    def cli(*arguments, report=None):
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "project_workflow.interfaces.cli", "--json", *arguments],
            input=report, cwd=Path(__file__).resolve().parents[1], env=environment,
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
        )
        assert completed.returncode == 0, (completed.stdout, completed.stderr)
        return json.loads(completed.stdout)

    base = ["--task", configured[1]["task"]]
    assert cli("step", *base)["version"] == 1
    for version in (1, 2, 3):
        arguments = ["step", *base, "--report", "-", "--operation-key", f"cli-pg-{version}",
                     "--expected-version", str(version)]
        if configured[1]["role_key"] == "project_manager" and version == 3:
            arguments += ["--requirements-revision", "7", "--requirements-sha256", "a" * 64]
        accepted = cli(*arguments, report=f"Отчёт subprocess №{version}")
        assert cli(*arguments, report=f"Отчёт subprocess №{version}") == accepted
    assert accepted["complete"] is True
    assert accepted["execution_ref"] == initial["execution_ref"]
    records = cli("history", *base)["records"]
    assert len(records) == 3
    assert set(tmp_path.rglob("*")) == before
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 3
        assert list(uow.session.scalars(
            select(m.TaskStepHistoryEntry.worker_report).order_by(m.TaskStepHistoryEntry.id)
        )) == [f"Отчёт subprocess №{version}" for version in (1, 2, 3)]
        assert uow.session.scalar(select(func.count()).select_from(m.PMRun)) == 0
