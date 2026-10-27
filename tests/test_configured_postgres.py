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
