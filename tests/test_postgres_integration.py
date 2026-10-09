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
from threading import Barrier, Event, Thread, local
from unittest.mock import patch
from urllib.request import urlopen

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import close_all_sessions

from project_workflow import config as config_module
from project_workflow.application.agent import AgentService
from project_workflow.application.instruction_service import InstructionService
from project_workflow.application.phase import PhaseServiceApp
from project_workflow.application.phase_service import PhaseService
from project_workflow.application.project import ProjectService
from project_workflow.application.task import TaskService
from project_workflow.application.workflow import WorkflowService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db.managed_catalog import (
    ensure_managed_catalog,
    validate_managed_catalog_state,
)
from project_workflow.infrastructure.db.session import (
    database_revisions,
    ensure_migrated,
    ensure_schema,
    get_engine,
    reset_engine,
    run_alembic_command,
    schema_is_ready,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.infrastructure.pm_readback import observe_run as http_observe_pm_run
from project_workflow.interfaces.ui.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def pm_postgres(pg_url, monkeypatch):
    from tests.test_pm_execution import prepare_pm

    ensure_migrated(get_engine(pg_url))
    yield from prepare_pm(monkeypatch)


@pytest.mark.integration
def test_pm_postgres_concurrent_replay_and_restart_readback(pm_postgres):
    from project_workflow.infrastructure.db import models as m
    from tests.test_pm_execution import ADAPTER, BASE, NEW_RUN, OLD_RUN, bind_pm

    client, runtime, checkpoint, observations, _ = bind_pm(pm_postgres)
    barrier = Barrier(2)

    def send_checkpoint():
        barrier.wait(timeout=10)
        return client.post(BASE + "/checkpoint", headers=runtime, json=checkpoint)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: send_checkpoint(), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    resume = {
        **checkpoint, "operation_key": "resume:1", "expected_version": 2,
        "answer_event_ref": "answer:one", "new_session_run_id": NEW_RUN,
    }
    observations[OLD_RUN]["status"] = "stopped"
    barrier = Barrier(2)

    def send_resume():
        barrier.wait(timeout=10)
        return client.post(BASE + "/resume", headers=ADAPTER, json=resume)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: send_resume(), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    # Recreate the HTTP application and DB connections; acceptance lives in PostgreSQL.
    restarted = TestClient(create_app())
    try:
        read = restarted.post(BASE + "/readback", headers=ADAPTER,
                              json={**pm_postgres[1], "operation_key": "resume:1"})
        assert read.status_code == 200, read.text
        assert read.json()["result"]["state"] == "resume_pending"
        assert read.json()["result"]["operation"]["result"] == responses[0].json()["result"]
    finally:
        restarted.close()
    with SAUnitOfWork() as uow:
        assert len(list(uow.session.query(m.PMOperation))) == 3
        assert len(list(uow.session.query(m.PMRun))) == 1


@pytest.mark.integration
@pytest.mark.parametrize("winner", ["provision", "bind"])
def test_pm_ownership_enrollment_race_orders(pg_url, monkeypatch, winner):
    from project_workflow.application.namespace_ownership import NamespaceOwnershipService
    from project_workflow.application.pm_execution import PMExecutionService
    from project_workflow.domain.namespace_ownership import NamespaceOwnershipRequest
    from project_workflow.domain.pm_execution import PMIdentity
    from project_workflow.infrastructure.db import models as m
    from project_workflow.infrastructure.db.repositories.project import SAProjectRepository
    from project_workflow.infrastructure.namespace_auth import NamespacePrincipal
    from tests.test_pm_execution import ADAPTER, BASE, PROJECT_REF, prepare_pm

    ensure_migrated(get_engine(pg_url))
    fixture = prepare_pm(monkeypatch, ownership=False)
    pm = next(fixture)
    client = pm[0]
    with SAUnitOfWork() as uow:
        namespace_id = uow.projects.get_by_cli_command("workflow-project_manager").id
    request = NamespaceOwnershipRequest(contract_version=1, tracker_instance_ref="tracker:one",
                                        tracker_project_ref=PROJECT_REF)
    principal = NamespacePrincipal("http://auth.test", "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
    held, waiting, release = Event(), Event(), Event()
    original_lock = SAProjectRepository.lock_pm_namespace
    def pause_project_lock(self, project_id):
        if held.is_set():
            waiting.set()
            return original_lock(self, project_id)
        result = original_lock(self, project_id)
        held.set()
        assert release.wait(timeout=15)
        return result

    monkeypatch.setattr(SAProjectRepository, "lock_pm_namespace", pause_project_lock)

    def provision():
        with SAUnitOfWork() as uow:
            return NamespaceOwnershipService(uow).provision(namespace_id, request, principal)

    def bind():
        return client.post(BASE + "/bind", headers=ADAPTER, json=pm[2])

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(provision if winner == "provision" else bind)
            try:
                assert held.wait(timeout=10)
                second = pool.submit(bind if winner == "provision" else provision)
                assert waiting.wait(timeout=10)
            finally:
                release.set()
            first_result, second_result = first.result(timeout=20), second.result(timeout=20)
        assert (second_result if winner == "provision" else first_result).status_code == (
            200 if winner == "provision" else 409
        )
        monkeypatch.setattr(SAProjectRepository, "lock_pm_namespace", original_lock)
        if winner == "bind":
            with SAUnitOfWork() as uow:
                assert uow.session.query(m.PMExecution).count() == 0
            assert bind().status_code == 200
        with SAUnitOfWork() as uow:
            assert uow.session.query(m.PMExecution).count() == 1
            assert uow.session.query(m.PMNamespaceOwnership).count() == 1
            assert PMExecutionService(uow).readback(
                PMIdentity.model_validate(pm[1]), namespace_id, None,
            )["identity"]["tracker_project_ref"] == PROJECT_REF
    finally:
        fixture.close()


@pytest.mark.integration
def test_pm_ownership_concurrent_provision_replay_and_db_immutability(pm_postgres):
    from sqlalchemy import select
    from sqlalchemy.exc import DBAPIError

    from project_workflow.application.namespace_ownership import NamespaceOwnershipService
    from project_workflow.domain.namespace_ownership import NamespaceOwnershipRequest
    from project_workflow.infrastructure.db import models as m
    from project_workflow.infrastructure.namespace_auth import NamespacePrincipal
    from tests.test_pm_execution import PROJECT_REF

    with SAUnitOfWork() as uow:
        namespace_id = uow.projects.get_by_cli_command("workflow-project_manager").id
        before = dict(uow.projects.get_pm_ownership(namespace_id))
    request = NamespaceOwnershipRequest(contract_version=1, tracker_instance_ref="tracker:one",
                                        tracker_project_ref=PROJECT_REF)
    principal = NamespacePrincipal("http://auth.test", "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
    barrier = Barrier(2)

    def provision(project_ref):
        barrier.wait(timeout=10)
        with SAUnitOfWork() as uow:
            try:
                return NamespaceOwnershipService(uow).provision(namespace_id, request.model_copy(update={
                    "tracker_project_ref": project_ref,
                }), principal)
            except ConflictError:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        same, foreign = list(pool.map(provision, [PROJECT_REF, "ffffffff-ffff-4fff-8fff-ffffffffffff"]))
    assert same[0].model_dump() == before and same[1] is False and foreign == "conflict"
    with SAUnitOfWork() as uow:
        assert dict(uow.projects.get_pm_ownership(namespace_id)) == before
        row = uow.session.scalar(select(m.PMNamespaceOwnership))
        for statement in [
            "UPDATE pm_namespace_ownership SET tracker_instance_ref='other'",
            "DELETE FROM pm_namespace_ownership",
        ]:
            with pytest.raises(DBAPIError, match="ownership is immutable"):
                uow.session.execute(text(statement))
            uow.rollback()
        with pytest.raises(IntegrityError):
            uow.projects.delete(namespace_id)
            uow.session.flush()
        uow.rollback()
        assert uow.session.get(m.PMNamespaceOwnership, row.ownership_ref) is not None


@pytest.mark.integration
@pytest.mark.parametrize("winner", ["bootstrap", "provision"])
def test_pm_ownership_catalog_lock_order_and_stale_0007(pg_url, winner):
    from project_workflow.application.namespace_ownership import NamespaceOwnershipService
    from project_workflow.domain.namespace_ownership import NamespaceOwnershipRequest
    from project_workflow.infrastructure.db.session import DatabaseRecreateRequired
    from project_workflow.infrastructure.namespace_auth import NamespacePrincipal

    engine = get_engine(pg_url)
    run_alembic_command("upgrade", engine, "0006_versioned_mode_catalog")
    with SAUnitOfWork(engine) as uow:
        ensure_managed_catalog(uow)
        namespace_id = uow.projects.get_by_cli_command("workflow-project_manager").id
    ensure_migrated(engine)
    held, waiting, release = Event(), Event(), Event()

    def bootstrap():
        with SAUnitOfWork(engine) as uow:
            if winner == "bootstrap":
                uow.lock_catalog_state()
                held.set()
                assert release.wait(timeout=15)
            else:
                waiting.set()
            ensure_managed_catalog(uow)

    def provision():
        with SAUnitOfWork(engine) as uow:
            if winner == "provision":
                uow.lock_catalog_state(shared=True)
                uow.projects.lock_pm_namespace(namespace_id)
                held.set()
                assert release.wait(timeout=15)
            else:
                waiting.set()
            return NamespaceOwnershipService(uow).provision(namespace_id, NamespaceOwnershipRequest(
                contract_version=1, tracker_instance_ref="tracker:one",
                tracker_project_ref="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            ), NamespacePrincipal("http://auth.test", "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(bootstrap if winner == "bootstrap" else provision)
        try:
            assert held.wait(timeout=10)
            second = pool.submit(provision if winner == "bootstrap" else bootstrap)
            assert waiting.wait(timeout=10)
        finally:
            release.set()
        first_result, second_result = first.result(timeout=20), second.result(timeout=20)
        assert (second_result if winner == "bootstrap" else first_result)[1] is True
    with SAUnitOfWork(engine) as uow:
        assert validate_managed_catalog_state(uow) is True
    assert schema_is_ready(engine)
    # An old pending head is not silently repaired or stamped as the expanded head.
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE pm_namespace_ownership"))
    assert not schema_is_ready(engine)
    with pytest.raises(DatabaseRecreateRequired):
        ensure_migrated(engine)
    assert database_revisions(engine) == {"0008_pm_execution"}


@pytest.mark.integration
def test_pm_ownership_postgres_actual_bounded_auth_and_readback(pg_url, monkeypatch):
    from tests.test_namespace_ownership import SUBJECT
    from tests.test_runtime_api import _namespace

    ensure_migrated(get_engine(pg_url))
    _namespace("PM", "workflow-project_manager", "PM")
    with SAUnitOfWork() as uow:
        namespace_id = uow.projects.get_by_cli_command("workflow-project_manager").id
    probes = []
    status = [200]
    scopes = [
        "project-workflow:read", "project-workflow:write",
        f"project-workflow:namespace-owner:provision:{namespace_id}",
        f"project-workflow:namespace-owner:read:{namespace_id}",
    ]

    class Auth(BaseHTTPRequestHandler):
        def do_GET(self):
            probes.append((self.path, self.headers.get("Authorization"), self.headers.get("Accept-Encoding")))
            body = json.dumps({"sub": SUBJECT, "email": "provisioner@test", "scopes": scopes}).encode()
            self.send_response(status[0])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Auth)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("AUTH_ISSUER", root)
    monkeypatch.setenv("AUTH_INTERNAL_BASE_URL", root)
    monkeypatch.setenv("AUTH_SESSION_SECRET", "x" * 40)
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_PROVISIONER_SUBJECT", SUBJECT)
    config_module.get_settings.cache_clear()
    client = TestClient(create_app())
    headers = {"Authorization": "Bearer sdlc_pat_owned-qa-test-only"}
    payload = {"contract_version": 1, "tracker_instance_ref": "tracker:one",
               "tracker_project_ref": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"}
    url = f"/api/pm/namespace-ownership/{namespace_id}"
    try:
        from project_workflow.infrastructure.db import models as m

        rejected = client.put(url, headers=headers, json={**payload, "tracker_instance_ref": "\u0416" * 65})
        assert rejected.status_code == 422 and probes == []
        unsupported = client.put(url, headers=headers, json=payload)
        assert unsupported.status_code == 403
        with SAUnitOfWork() as uow:
            assert uow.session.query(m.PMNamespaceOwnership).count() == 0
        scopes[:] = ["project-workflow:read", "project-workflow:write"]
        first = client.put(url, headers=headers, json=payload)
        assert first.status_code == 201, first.text
        assert first.json()["result"]["authority_issuer"] == root
        assert client.put(url, headers=headers, json=payload).json() == first.json()
        assert client.get(url, headers=headers).json() == first.json()
        status[0] = 401
        denied = client.get(url, headers=headers)
        assert denied.status_code == 401 and "sdlc_pat_" not in denied.text and root not in denied.text
        assert probes == [("/auth/tokens/introspect", headers["Authorization"], "identity")] * 5
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.integration
def test_pm_postgres_concurrent_concrete_binding_has_one_immutable_winner(pm_postgres):
    from sqlalchemy import select

    from project_workflow.infrastructure.db import models as m
    from tests.test_pm_execution import ADAPTER, AGENT_REF, OTHER_AGENT_REF
    from tests.test_runtime_api import _assignment, _bind_payload

    client = pm_postgres[0]
    assigned = client.post("/internal/runtime/assign", headers=ADAPTER,
                           json=_assignment("PM-2", "assign:pm:2", "project_manager")).json()["result"]
    barrier = Barrier(2)

    def bind(agent_ref):
        barrier.wait(timeout=10)
        return client.post("/internal/runtime/bind", headers=ADAPTER, json={
            **_bind_payload(assigned), "concrete_agent_ref": agent_ref,
        })

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(bind, [AGENT_REF, OTHER_AGENT_REF]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response for response in responses if response.status_code == 200).json()["result"]
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
            m.TaskRuntimeAssignment.operation_key == "assign:pm:2",
        ))
        assert row.concrete_agent_ref == winner["concrete_agent_ref"]
    replay = client.post("/internal/runtime/bind", headers=ADAPTER, json={
        **_bind_payload(assigned), "concrete_agent_ref": winner["concrete_agent_ref"],
    })
    assert replay.status_code == 200
    assert replay.json()["result"] == winner


@pytest.mark.integration
@pytest.mark.parametrize("mapping", [
    None, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "00000000-0000-0000-0000-000000000000",
])
def test_pm_postgres_missing_or_tampered_mapping_fences_continuation(pm_postgres, mapping):
    from tests.test_concrete_agent_mapping import (
        test_resume_rechecks_mapping_before_trusted_terminal_probe as verify_mapping,
    )

    verify_mapping(pm_postgres, mapping)


@pytest.mark.integration
@pytest.mark.parametrize("winner", ["pm", "generic"])
def test_pm_enrollment_and_generic_continuation_share_owner_lock(pm_postgres, monkeypatch, winner):
    from project_workflow.application.pm_execution import PMExecutionService
    from project_workflow.infrastructure.db.repositories.task import SATaskRepository
    from tests.test_pm_execution import ADAPTER, BASE
    from tests.test_pm_generic_continuation import continuation, persisted_state

    client = pm_postgres[0]
    held, contender_started, release = Event(), Event(), Event()
    original_proof = PMExecutionService._proof
    original_enrollment = SATaskRepository.assignment_has_pm_execution
    original_pm_lock = PMExecutionService._lock_identity
    original_generic_lock = SATaskRepository.lock

    def pause_proof(*args, **kwargs):
        held.set()
        assert release.wait(timeout=20)
        return original_proof(*args, **kwargs)

    def pause_enrollment(self, *args):
        result = original_enrollment(self, *args)
        held.set()
        assert release.wait(timeout=20)
        return result

    def notify_pm_lock(self, *args):
        contender_started.set()
        return original_pm_lock(self, *args)

    def notify_generic_lock(self, *args):
        contender_started.set()
        return original_generic_lock(self, *args)

    if winner == "pm":
        monkeypatch.setattr(PMExecutionService, "_proof", staticmethod(pause_proof))
        monkeypatch.setattr(SATaskRepository, "lock", notify_generic_lock)
    else:
        monkeypatch.setattr(SATaskRepository, "assignment_has_pm_execution", pause_enrollment)
        monkeypatch.setattr(PMExecutionService, "_lock_identity", notify_pm_lock)

    def enroll():
        return client.post(BASE + "/bind", headers=ADAPTER, json=pm_postgres[2])

    def continue_generic():
        return client.post("/internal/runtime/rebind", headers=ADAPTER, json=continuation(pm_postgres[4]))

    before = persisted_state()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(enroll if winner == "pm" else continue_generic)
        try:
            assert held.wait(timeout=10)
            second = pool.submit(continue_generic if winner == "pm" else enroll)
            assert contender_started.wait(timeout=10)
        finally:
            release.set()
        accepted, rejected = first.result(timeout=20), second.result(timeout=20)
    assert accepted.status_code == 200, accepted.text
    assert rejected.status_code == 409, rejected.text
    after = persisted_state()
    assert after[2:5] == before[2:5]
    if winner == "pm":
        assert "Enrolled PM assignment requires PM resume/rebind" in rejected.text
        assert after[:2] == before[:2]
        assert after[5] == (1, 0, 1, 1, 1)
    else:
        assert rejected.json()["error_code"] == "conflict"
        assert after[0] == before[0] + 1
        assert after[5] == (2, 0, 0, 0, 0)


@pytest.mark.integration
@pytest.mark.parametrize("cycle_number", [0, 1])
def test_pm_postgres_normal_done_rejects_new_generic_assignment(pm_postgres, supervisor_llm, cycle_number):
    from tests.test_pm_assignment_guard import (
        test_normal_scoped_pass_cannot_replace_running_pm_assignment as verify_denial,
    )

    verify_denial(pm_postgres, supervisor_llm, cycle_number)


@pytest.mark.integration
def test_pm_postgres_done_assignment_replay_races_new_assignment(pm_postgres, supervisor_llm):
    from tests.test_pm_assignment_guard import persisted_assignment_state, replacement
    from tests.test_pm_execution import ADAPTER
    from tests.test_pm_execution_edges import (
        test_resumed_supervisor_report_is_persistent_and_replayable as verify_done,
    )
    from tests.test_runtime_api import _assignment

    verify_done(pm_postgres, supervisor_llm)
    client = pm_postgres[0]
    barrier = Barrier(2)
    before = persisted_assignment_state()

    def assign(request):
        barrier.wait(timeout=10)
        return client.post("/internal/runtime/assign", headers=ADAPTER, json=request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        replay = pool.submit(assign, _assignment("PM-1", "assign:pm:1", "project_manager"))
        rejected = pool.submit(assign, replacement())
        replay_response, rejected_response = replay.result(timeout=20), rejected.result(timeout=20)
    assert replay_response.status_code == 200, replay_response.text
    assert replay_response.json()["result"]["assignment_revision"] == 1
    assert rejected_response.status_code == 409, rejected_response.text
    assert rejected_response.json()["ok"] is False
    assert "Enrolled PM task requires terminal/quiescent replacement admission" in rejected_response.text
    assert persisted_assignment_state() == before


@pytest.mark.integration
@pytest.mark.parametrize("winner", ["pm", "generic"])
def test_pm_enrollment_and_new_assignment_share_owner_lock(pm_postgres, supervisor_llm, monkeypatch, winner):
    from project_workflow.application.pm_execution import PMExecutionService
    from project_workflow.infrastructure.db.repositories.project import SAProjectRepository
    from project_workflow.infrastructure.db.repositories.task import SATaskRepository
    from tests.test_pm_assignment_guard import complete_unenrolled_assignment, persisted_assignment_state, replacement
    from tests.test_pm_execution import ADAPTER, BASE

    client = pm_postgres[0]
    held, contender_started, release = Event(), Event(), Event()
    original_proof = PMExecutionService._proof
    original_lock = SAProjectRepository.lock
    original_pm_project_lock = SAProjectRepository.lock_pm_namespace
    original_enrollment = SATaskRepository.task_has_pm_execution

    def pause_proof(*args, **kwargs):
        held.set()
        assert release.wait(timeout=20)
        return original_proof(*args, **kwargs)

    def notify_lock(self, project_id):
        if held.is_set():
            contender_started.set()
        return original_lock(self, project_id)

    def notify_pm_project_lock(self, project_id):
        if held.is_set():
            contender_started.set()
        return original_pm_project_lock(self, project_id)

    def pause_enrollment(self, task_id):
        enrolled = original_enrollment(self, task_id)
        held.set()
        assert release.wait(timeout=20)
        return enrolled

    monkeypatch.setattr(SAProjectRepository, "lock", notify_lock)
    monkeypatch.setattr(SAProjectRepository, "lock_pm_namespace", notify_pm_project_lock)
    if winner == "pm":
        monkeypatch.setattr(PMExecutionService, "_proof", staticmethod(pause_proof))
    else:
        complete_unenrolled_assignment(pm_postgres, supervisor_llm)
        monkeypatch.setattr(SATaskRepository, "task_has_pm_execution", pause_enrollment)

    def enroll():
        return client.post(BASE + "/bind", headers=ADAPTER, json=pm_postgres[2])

    def assign():
        return client.post("/internal/runtime/assign", headers=ADAPTER, json=replacement())

    before = persisted_assignment_state()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(enroll if winner == "pm" else assign)
        try:
            assert held.wait(timeout=10)
            second = pool.submit(assign if winner == "pm" else enroll)
            assert contender_started.wait(timeout=10)
        finally:
            release.set()
        accepted, rejected = first.result(timeout=20), second.result(timeout=20)
    assert accepted.status_code == 200, accepted.text
    assert rejected.status_code == 409, rejected.text
    after = persisted_assignment_state()
    if winner == "pm":
        assert "Enrolled PM task requires terminal/quiescent replacement admission" in rejected.text
        assert after[:4] == before[:4]
        assert tuple(len(rows) for rows in after[4:]) == (1, 1, 1)
    else:
        assert rejected.json()["error_code"] == "conflict"
        assert accepted.json()["result"]["assignment_revision"] == 2
        assert after[1][0] == before[1][0] and len(after[1]) == 2
        assert after[3] == before[3]
        assert tuple(len(rows) for rows in after[4:]) == (0, 0, 0)


@pytest.mark.integration
def test_pm_postgres_actual_http_callback_and_new_run_binding(pm_postgres, monkeypatch):
    from project_workflow.infrastructure import pm_readback
    from tests.test_pm_execution import (
        NEW_RUN,
        OLD_RUN,
        test_wait_resume_new_run_survives_sessions_and_replays,
    )

    probes: list[str] = []
    observations = pm_postgres[3]

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            probes.append(self.path)
            run_uuid = self.path.removeprefix("/runs/")
            if self.headers.get("Authorization") != "Bearer " + "p" * 40 or run_uuid not in observations:
                self.send_error(503)
                return
            body = json.dumps(observations[run_uuid]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Callback)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_URL", f"http://127.0.0.1:{server.server_port}/runs")
    config_module.get_settings.cache_clear()
    monkeypatch.setattr(pm_readback, "observe_run", http_observe_pm_run)
    try:
        test_wait_resume_new_run_survives_sessions_and_replays(pm_postgres)
        assert probes == ["/runs/" + OLD_RUN] * 3 + ["/runs/" + NEW_RUN]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

PG_HOST = os.environ.get("PGHOST", "127.0.0.1")
PG_PORT = int(os.environ.get("PGPORT", "5432"))
PG_USER = os.environ.get("PGUSER", "project_workflow")
PG_PASSWORD = os.environ.get("PGPASSWORD", "project_workflow")
PG_ADMIN_DB = os.environ.get("PGDATABASE", "project_workflow")
PG_CONNECT_TIMEOUT = int(os.environ.get("PGCONNECT_TIMEOUT", "10"))


@pytest.fixture(autouse=True)
def packaged_pg_test_runtime(monkeypatch):
    from project_workflow import build_provenance
    from tests.test_runtime_assignment_contract import TEST_RUNTIME_COMPATIBILITY
    monkeypatch.setattr(build_provenance, "runtime_compatibility_descriptor", lambda: dict(TEST_RUNTIME_COMPATIBILITY))


def _runtime_binding(operation_key: str) -> dict[str, object]:
    from tests.test_runtime_assignment_contract import TEST_RUNTIME_COMPATIBILITY
    return {
        "runtime_compatibility": dict(TEST_RUNTIME_COMPATIBILITY),
        "workflow_key": "hermes-sdlc:developer",
        "role_key": "developer",
        "stage_key": "development",
        "execution_scope": "delivery",
        "attempt_number": 1,
        "business_task_ref": f"business-task:{operation_key}",
        "root_task_ref": "business-task:root",
        "work_item_ref": f"work-item:{operation_key}",
        "work_item_revision": 1,
        "queue_item_ref": f"queue-item:{operation_key}",
        "task_workspace_ref": "task-workspace:root",
        "workspace_revision": 1,
        "tech_execution_workspace_ref": f"tech-workspace:{operation_key}",
        "tech_execution_attempt_ref": f"tech-attempt:{operation_key}",
        "decomposition_revision_ref": "decomposition:1",
        "stage_revision": "developer:1",
        "assignment_ref": f"assignment:{operation_key}",
        "workspace_generation": 1,
        "lease_generation": 1,
        "exact_input_refs": [
            {"kind": "business_task", "ref": f"business-task:{operation_key}", "revision": "1"}
        ],
    }


def _bind_runtime_assignment(
    uow: SAUnitOfWork, project_id: int, assignment: dict[str, object]
) -> dict[str, object]:
    operation_key = str(assignment["assignment_operation_key"])
    return TaskService(uow).bind_runtime_assignment(
        project_id=project_id,
        task_key=str(assignment["task_key"]),
        role_key=str(assignment["role_key"]),
        bind_operation_key=f"bind:{operation_key}",
        assignment_operation_key=operation_key,
        assignment_revision=int(assignment["assignment_revision"]),
        assignment_ref=str(assignment["assignment_ref"]),
        binding_ref=f"binding:{operation_key}",
        hermes_run_ref=f"hermes-run:{operation_key}",
        mode_key=str(assignment["mode_key"]),
        cycle_number=int(assignment["cycle_number"]),
        attempt_number=int(assignment["attempt_number"]),
        expected_binding_state="unbound",
    )


def _fixture_default_mode(connection, workflow_id: int) -> int:
    """Build a valid head-schema mode for tests exercising raw SQL constraints."""
    return int(
        connection.execute(
            text(
                "INSERT INTO project_workflow.workflow_modes "
                "(workflow_id, key, name, mode_order) "
                "VALUES (:workflow_id, 'default', 'Default', 1) RETURNING id"
            ),
            {"workflow_id": workflow_id},
        ).scalar_one()
    )



@pytest.fixture(scope="function")
def pg_url(monkeypatch):
    """Create a fresh PostgreSQL database and yield a SQLAlchemy URL for it."""
    if not PG_PASSWORD:
        pytest.skip("PGPASSWORD is not set")
    pid = os.getpid()
    db_name = f"project_workflow_test_{pid}"
    base_url = f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{db_name}"

    admin_conn = psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_ADMIN_DB,
        user=PG_USER,
        password=PG_PASSWORD,
        connect_timeout=PG_CONNECT_TIMEOUT,
    )
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
    yield base_url

    # The autouse UoW tracker tears down after this fixture. Close active
    # sessions before DROP DATABASE so its cleanup never sees AdminShutdown.
    close_all_sessions()
    reset_engine()
    admin_conn = psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_ADMIN_DB,
        user=PG_USER,
        password=PG_PASSWORD,
        connect_timeout=PG_CONNECT_TIMEOUT,
    )
    admin_conn.autocommit = True
    with admin_conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
    admin_conn.close()


@pytest.mark.integration
class TestPostgresInitialMigration:
    def test_get_engine_postgresql(self, pg_url):
        engine = get_engine(pg_url)
        assert engine.dialect.name == "postgresql"
        assert engine.url.database == pg_url.rsplit("/", 1)[-1]

    def test_fresh_upgrade_matches_orm_metadata(self, pg_url):
        from project_workflow.infrastructure.db.models import Base
        from project_workflow.infrastructure.db.session import migration_head, schema_is_ready

        engine = get_engine(pg_url)
        ensure_migrated(engine)
        ensure_migrated(engine)

        inspector = inspect(engine)
        actual_tables = set(inspector.get_table_names(schema="project_workflow"))
        assert actual_tables - {"alembic_version"} == set(Base.metadata.tables)
        for table_name, table in Base.metadata.tables.items():
            actual_columns = {
                column["name"] for column in inspector.get_columns(table_name, schema="project_workflow")
            }
            assert actual_columns == set(table.columns.keys()), table_name

        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn,
                opts={"compare_type": True, "compare_server_default": True},
            )
            assert compare_metadata(context, Base.metadata) == []

        with engine.connect() as conn:
            version = conn.execute(
                text("SELECT version_num FROM project_workflow.alembic_version")
            ).scalar_one()
        assert version == migration_head() == "0008_pm_execution"
        assert schema_is_ready(engine) is True

    def test_managed_bootstrap_lock_closes_public_mutation_race(self, pg_url):
        engine = get_engine(pg_url)
        ensure_migrated(engine)
        bootstrap_locked = Event()
        mutation_started = Event()

        def bootstrap() -> None:
            with SAUnitOfWork(engine) as uow:
                uow.lock_catalog_state()
                bootstrap_locked.set()
                assert mutation_started.wait(timeout=10)
                ensure_managed_catalog(uow)

        def create_foreign_workflow() -> str:
            assert bootstrap_locked.wait(timeout=10)
            mutation_started.set()
            with SAUnitOfWork(engine) as uow:
                try:
                    WorkflowService(uow).create_workflow(
                        {"name": "TEST TRASH WORKFLOW"}
                    )
                except ConflictError as exc:
                    return str(exc)
            return "unexpected-success"

        with ThreadPoolExecutor(max_workers=2) as pool:
            bootstrap_future = pool.submit(bootstrap)
            mutation_future = pool.submit(create_foreign_workflow)
            bootstrap_future.result(timeout=30)
            mutation_result = mutation_future.result(timeout=30)

        assert "Managed workflow catalog is immutable" in mutation_result
        with SAUnitOfWork(engine) as uow:
            assert validate_managed_catalog_state(uow) is True
            assert all(
                workflow.name != "TEST TRASH WORKFLOW"
                for workflow in uow.workflows.list()
            )

    def test_public_catalog_mutation_blocks_managed_bootstrap_until_commit(self, pg_url):
        engine = get_engine(pg_url)
        ensure_migrated(engine)
        mutation_locked = Event()
        bootstrap_started = Event()
        bootstrap_finished = Event()
        release_mutation = Event()

        def mutate() -> str:
            with SAUnitOfWork(engine) as uow:
                original_create = uow.workflows.create

                def paused_create(data):
                    workflow_id = original_create(data)
                    mutation_locked.set()
                    assert release_mutation.wait(timeout=10)
                    return workflow_id

                uow.workflows.create = paused_create
                WorkflowService(uow).create_workflow({"name": "Existing unmanaged workflow"})
            return "committed"

        def bootstrap() -> str:
            assert mutation_locked.wait(timeout=10)
            with SAUnitOfWork(engine) as uow:
                original_lock = uow.lock_catalog_state

                def observed_lock(*, shared=False):
                    bootstrap_started.set()
                    return original_lock(shared=shared)

                uow.lock_catalog_state = observed_lock
                try:
                    ensure_managed_catalog(uow)
                except ValueError:
                    return "foreign-catalog-rejected"
                finally:
                    bootstrap_finished.set()
            return "unexpected-success"

        with ThreadPoolExecutor(max_workers=2) as pool:
            mutation_future = pool.submit(mutate)
            bootstrap_future = pool.submit(bootstrap)
            try:
                assert bootstrap_started.wait(timeout=10)
                assert not bootstrap_finished.wait(timeout=0.2)
            finally:
                release_mutation.set()
            assert mutation_future.result(timeout=20) == "committed"
            assert bootstrap_future.result(timeout=20) == "foreign-catalog-rejected"

        with SAUnitOfWork(engine) as uow:
            assert [workflow.name for workflow in uow.workflows.list()] == ["Existing unmanaged workflow"]
            assert validate_managed_catalog_state(uow) is False

    @pytest.mark.parametrize("revision,message", [
        ("0003_runtime_assignment_bind", "Downgrade from runtime assignment bind"),
        ("0004_wide_work_item_revision", "Downgrade from wide Business revisions"),
        ("0008_pm_execution", "PM execution downgrade refused"),
    ])
    def test_downgrade_refuses_lossy_mode_collapse(self, pg_url, revision, message):
        engine = get_engine(pg_url)
        run_alembic_command("upgrade", engine, revision)
        with pytest.raises(RuntimeError, match=message):
            run_alembic_command("downgrade", engine, "base")
        assert database_revisions(engine) == {revision}
        assert schema_is_ready(engine) is (revision == "0008_pm_execution")

    def test_populated_0001_upgrade_preserves_rows_and_backfills_per_workflow(self, pg_url):
        engine = get_engine(pg_url)
        run_alembic_command("upgrade", engine, "0001_initial")
        with engine.begin() as conn:
            workflow_ids = [
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.workflows (name, description, is_default) "
                        "VALUES (:name, '', 0) RETURNING id"
                    ),
                    {"name": f"Legacy PG {suffix}"},
                ).scalar_one()
                for suffix in ("A", "B")
            ]
            for index, workflow_id in enumerate(workflow_ids, 1):
                phase_id = conn.execute(
                    text(
                        "INSERT INTO project_workflow.phases "
                        "(workflow_id, code, name, phase_order, execution_type) "
                        "VALUES (:workflow_id, :code, 'Legacy', 1, 'sync') RETURNING id"
                    ),
                    {"workflow_id": workflow_id, "code": f"legacy-{index}"},
                ).scalar_one()
                project_id = conn.execute(
                    text(
                        "INSERT INTO project_workflow.projects "
                        "(workflow_id, code, name, description, theme_icon, theme_color, cli_command, key_prefixes) "
                        "VALUES (:workflow_id, :code, 'Legacy', '', 'folder', '#5E6AD2', :cli, '[]') RETURNING id"
                    ),
                    {"workflow_id": workflow_id, "code": f"LPG{index}", "cli": f"legacy-pg-{index}"},
                ).scalar_one()
                task_id = conn.execute(
                    text(
                        "INSERT INTO project_workflow.tasks "
                        "(project_id, workflow_id, task_key, title, current_phase_id, status) "
                        "VALUES (:project_id, :workflow_id, :task_key, 'Legacy', :phase_id, 'active') RETURNING id"
                    ),
                    {
                        "project_id": project_id,
                        "workflow_id": workflow_id,
                        "task_key": f"LPG{index}-1",
                        "phase_id": phase_id,
                    },
                ).scalar_one()
                history_id = conn.execute(
                    text(
                        "INSERT INTO project_workflow.task_step_history "
                        "(task_id, workflow_id, phase_id, verdict, replay_fingerprint) "
                        "VALUES (:task_id, :workflow_id, :phase_id, 'partial', :fingerprint) RETURNING id"
                    ),
                    {
                        "task_id": task_id,
                        "workflow_id": workflow_id,
                        "phase_id": phase_id,
                        "fingerprint": f"legacy-pg-{index}",
                    },
                ).scalar_one()
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.task_phase_events "
                        "(task_id, workflow_id, phase_id, step_history_id, event_type) "
                        "VALUES (:task_id, :workflow_id, :phase_id, :history_id, 'entered')"
                    ),
                    {"task_id": task_id, "workflow_id": workflow_id, "phase_id": phase_id, "history_id": history_id},
                )

        run_alembic_command("upgrade", engine)
        with engine.connect() as conn:
            mode_rows = conn.execute(
                text(
                    "SELECT workflow_id, id FROM project_workflow.workflow_modes "
                    "WHERE key = 'default' ORDER BY workflow_id"
                )
            ).all()
            assert len(mode_rows) == 2 and mode_rows[0].id != mode_rows[1].id
            assert conn.execute(text("SELECT count(*) FROM project_workflow.tasks")).scalar_one() == 2
            assert conn.execute(text("SELECT count(*) FROM project_workflow.task_step_history")).scalar_one() == 2
            assert conn.execute(text("SELECT count(*) FROM project_workflow.task_phase_events")).scalar_one() == 2

    def test_head_preserves_nullable_legacy_assignment_shape(self, pg_url):
        engine = get_engine(pg_url)
        run_alembic_command("upgrade", engine, "0001_initial")
        with engine.begin() as conn:
            workflow_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.workflows (name, description, is_default) "
                    "VALUES ('Legacy 0002', '', 0) RETURNING id"
                )
            ).scalar_one()
            phase_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.phases "
                    "(workflow_id, code, name, phase_order, execution_type) "
                    "VALUES (:workflow_id, 'legacy', 'Legacy', 1, 'sync') RETURNING id"
                ),
                {"workflow_id": workflow_id},
            ).scalar_one()
            project_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.projects "
                    "(workflow_id, code, name, description, theme_icon, theme_color, cli_command, key_prefixes) "
                    "VALUES (:workflow_id, 'L2', 'Legacy', '', 'folder', '#5E6AD2', 'legacy-2', '[]') "
                    "RETURNING id"
                ),
                {"workflow_id": workflow_id},
            ).scalar_one()
            task_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.tasks "
                    "(project_id, workflow_id, task_key, current_phase_id, status) "
                    "VALUES (:project_id, :workflow_id, 'L2-1', :phase_id, 'active') RETURNING id"
                ),
                {"project_id": project_id, "workflow_id": workflow_id, "phase_id": phase_id},
            ).scalar_one()

        run_alembic_command("upgrade", engine, "0002_workflow_modes")
        with engine.begin() as conn:
            mode_id = conn.execute(
                text(
                    "SELECT id FROM project_workflow.workflow_modes "
                    "WHERE workflow_id = :workflow_id AND key = 'default'"
                ),
                {"workflow_id": workflow_id},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO project_workflow.task_runtime_assignments "
                    "(operation_key, task_id, project_id, workflow_id, mode_id, cycle_number, "
                    "assignment_revision, payload) VALUES "
                    "('legacy-0002-op', :task_id, :project_id, :workflow_id, :mode_id, 0, 1, "
                    ":legacy_payload)"
                ),
                {
                    "task_id": task_id,
                    "project_id": project_id,
                    "workflow_id": workflow_id,
                    "mode_id": mode_id,
                    "legacy_payload": '{"legacy":true}',
                },
            )
            workflow_key = conn.execute(
                text(
                    "SELECT key FROM project_workflow.workflows WHERE id = :workflow_id"
                ),
                {"workflow_id": workflow_id},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO project_workflow.task_runtime_assignments "
                    "(operation_key, task_id, project_id, workflow_id, mode_id, cycle_number, "
                    "assignment_revision, workflow_key, role_key, execution_scope, stage_key, "
                    "attempt_number, business_task_ref, root_task_ref, work_item_ref, "
                    "work_item_revision, queue_item_ref, task_workspace_ref, workspace_revision, "
                    "tech_execution_workspace_ref, tech_execution_attempt_ref, "
                    "decomposition_revision_ref, stage_revision, assignment_ref, binding_ref, "
                    "hermes_run_ref, workspace_generation, lease_generation, exact_input_refs, "
                    "payload_sha256, payload) VALUES "
                    "('legacy-0002-bound', :task_id, :project_id, :workflow_id, :mode_id, 0, 2, "
                    ":workflow_key, 'developer', 'delivery', 'development', 1, 'business:1', "
                    "'business:root', 'business:item', 1, 'queue:1', 'task-workspace:1', 1, "
                    "'tech-workspace:1', 'tech-attempt:1', 'decomposition:1', 'stage:1', "
                    "'assignment:1', 'binding:legacy', 'hermes-run:legacy', 1, 1, '[]', "
                    ":payload_sha256, :bound_payload)"
                ),
                {
                    "task_id": task_id,
                    "project_id": project_id,
                    "workflow_id": workflow_id,
                    "mode_id": mode_id,
                    "workflow_key": workflow_key,
                    "payload_sha256": "a" * 64,
                    "bound_payload": '{"bound":true}',
                },
            )

        ensure_migrated(engine)

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT operation_key, binding_ref, hermes_run_ref, bind_operation_key, "
                    "bind_request_sha256, payload FROM project_workflow.task_runtime_assignments "
                    "WHERE operation_key IN ('legacy-0002-op', 'legacy-0002-bound') "
                    "ORDER BY operation_key"
                )
            ).all()
        assert rows == [
            (
                "legacy-0002-bound",
                "binding:legacy",
                "hermes-run:legacy",
                None,
                None,
                '{"bound":true}',
            ),
            ("legacy-0002-op", None, None, None, None, '{"legacy":true}'),
        ]
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE project_workflow.task_runtime_assignments "
                        "SET bind_operation_key = 'partial-bind' "
                        "WHERE operation_key = 'legacy-0002-bound'"
                    )
                )

    def test_legacy_revision_is_refused_without_mutation(self, pg_url):
        from project_workflow.infrastructure.db.session import (
            DatabaseRecreateRequired,
            database_revisions,
        )

        engine = get_engine(pg_url)
        with engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA project_workflow"))
            conn.execute(
                text(
                    "CREATE TABLE project_workflow.alembic_version "
                    "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO project_workflow.alembic_version(version_num) "
                    "VALUES ('e6a4c2d8b901')"
                )
            )
            conn.execute(text("CREATE TABLE project_workflow.keep_me (id INTEGER PRIMARY KEY)"))

        with pytest.raises(DatabaseRecreateRequired, match="Несовместимую базу данных необходимо пересоздать"):
            ensure_migrated(engine)

        assert database_revisions(engine) == {"e6a4c2d8b901"}
        assert inspect(engine).has_table("keep_me", schema="project_workflow")

    def test_head_with_column_drift_is_not_ready(self, pg_url):
        from project_workflow.infrastructure.db.session import DatabaseRecreateRequired, schema_is_ready

        engine = get_engine(pg_url)
        ensure_migrated(engine)
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE project_workflow.projects ADD COLUMN unexpected_column TEXT"))

        assert schema_is_ready(engine) is False
        with pytest.raises(DatabaseRecreateRequired):
            ensure_migrated(engine)

    def test_initial_constraints_and_phase_scoped_fingerprint(self, pg_url):
        engine = get_engine(pg_url)
        ensure_migrated(engine)
        with engine.begin() as conn:
            workflow_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.workflows "
                    "(key, name, description, is_default) VALUES ('fixture:w', 'W', '', 1) RETURNING id"
                )
            ).scalar_one()
            mode_id = _fixture_default_mode(conn, workflow_id)
            project_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.projects "
                    "(workflow_id, code, name, description, key_prefixes, cli_command) "
                    "VALUES (:workflow_id, 'P', 'Project', 'persisted', '[\"P\"]', 'workflow-p') RETURNING id"
                ),
                {"workflow_id": workflow_id, "mode_id": mode_id},
            ).scalar_one()
            phase_ids = [
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.phases "
                        "(workflow_id, mode_id, code, name, phase_order) "
                        "VALUES (:workflow_id, :mode_id, :code, :name, :phase_order) RETURNING id"
                    ),
                    {
                        "workflow_id": workflow_id,
                        "mode_id": mode_id,
                        "code": str(order),
                        "name": f"Phase {order}",
                        "phase_order": order,
                    },
                ).scalar_one()
                for order in (1, 2)
            ]
            task_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.tasks "
                    "(project_id, workflow_id, mode_id, task_key, current_phase_id, status) "
                    "VALUES (:project_id, :workflow_id, :mode_id, 'P-1', :phase_id, 'active') RETURNING id"
                ),
                {
                    "project_id": project_id,
                    "workflow_id": workflow_id,
                    "mode_id": mode_id,
                    "phase_id": phase_ids[0],
                },
            ).scalar_one()
            for phase_id in phase_ids:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.task_step_history "
                        "(task_id, workflow_id, mode_id, phase_id, verdict, replay_fingerprint) "
                        "VALUES (:task_id, :workflow_id, :mode_id, :phase_id, 'partial', 'same')"
                    ),
                    {"task_id": task_id, "workflow_id": workflow_id, "mode_id": mode_id, "phase_id": phase_id},
                )

        with engine.connect() as conn:
            description = conn.execute(
                text("SELECT description FROM project_workflow.projects WHERE id = :id"),
                {"id": project_id},
            ).scalar_one()
        assert description == "persisted"

        with pytest.raises(IntegrityError, match="ck_phases_phase_order_positive"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.phases "
                        "(workflow_id, mode_id, code, name, phase_order) "
                        "VALUES (:workflow_id, :mode_id, 'bad', 'Bad', 0)"
                    ),
                    {"workflow_id": workflow_id, "mode_id": mode_id},
                )
        with pytest.raises(IntegrityError, match="ck_phase_instructions_step_num_positive"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.phase_instructions "
                        "(phase_id, step_num, description) VALUES (:phase_id, 0, 'Bad')"
                    ),
                    {"phase_id": phase_ids[0]},
                )
        with pytest.raises(IntegrityError, match="uq_task_step_history_replay"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.task_step_history "
                        "(task_id, workflow_id, mode_id, phase_id, verdict, replay_fingerprint) "
                        "VALUES (:task_id, :workflow_id, :mode_id, :phase_id, 'partial', 'same')"
                    ),
                    {"task_id": task_id, "workflow_id": workflow_id, "mode_id": mode_id, "phase_id": phase_ids[0]},
                )
        with pytest.raises(IntegrityError, match="fk_tasks_current_phase_workflow"):
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM project_workflow.phases WHERE id = :phase_id"),
                    {"phase_id": phase_ids[0]},
                )

    def test_database_enforces_task_and_audit_ownership(self, pg_url):
        engine = get_engine(pg_url)
        ensure_migrated(engine)

        with engine.begin() as conn:
            workflow_ids: list[int] = []
            project_ids: list[int] = []
            mode_ids: list[int] = []
            phase_ids: list[int] = []
            for suffix in ("A", "B"):
                workflow_id = conn.execute(
                    text(
                        "INSERT INTO project_workflow.workflows (key, name, description, is_default) "
                        "VALUES (:key, :name, '', 0) RETURNING id"
                    ),
                    {"key": f"workflow-{suffix.lower()}", "name": f"Workflow {suffix}"},
                ).scalar_one()
                mode_id = _fixture_default_mode(conn, workflow_id)
                project_id = conn.execute(
                    text(
                        "INSERT INTO project_workflow.projects "
                        "(workflow_id, code, name, description, key_prefixes, cli_command) "
                        "VALUES (:workflow_id, :code, :name, '', :prefixes, :cli_command) RETURNING id"
                    ),
                    {
                        "workflow_id": workflow_id,
                        "mode_id": mode_id,
                        "code": f"P{suffix}",
                        "name": f"Project {suffix}",
                        "prefixes": f'["P{suffix}"]',
                        "cli_command": f"workflow-p{suffix.lower()}",
                    },
                ).scalar_one()
                phase_id = conn.execute(
                    text(
                        "INSERT INTO project_workflow.phases "
                        "(workflow_id, mode_id, code, name, phase_order) "
                        "VALUES (:workflow_id, :mode_id, :code, :name, 1) RETURNING id"
                    ),
                    {"workflow_id": workflow_id, "mode_id": mode_id, "code": suffix, "name": f"Phase {suffix}"},
                ).scalar_one()
                workflow_ids.append(workflow_id)
                mode_ids.append(mode_id)
                project_ids.append(project_id)
                phase_ids.append(phase_id)

        with pytest.raises(IntegrityError, match="fk_tasks_project_workflow"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.tasks "
                        "(project_id, workflow_id, mode_id, task_key, current_phase_id, status) "
                        "VALUES (:project_id, :workflow_id, :mode_id, 'PA-BAD', :phase_id, 'active')"
                    ),
                    {
                        "project_id": project_ids[0],
                        "workflow_id": workflow_ids[1],
                        "mode_id": mode_ids[1],
                        "phase_id": phase_ids[1],
                    },
                )

        with engine.begin() as conn:
            task_ids = [
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.tasks "
                        "(project_id, workflow_id, mode_id, task_key, current_phase_id, status) "
                        "VALUES (:project_id, :workflow_id, :mode_id, :task_key, :phase_id, 'active') RETURNING id"
                    ),
                    {
                        "project_id": project_ids[index],
                        "workflow_id": workflow_ids[index],
                        "mode_id": mode_ids[index],
                        "task_key": f"P{suffix}-1",
                        "phase_id": phase_ids[index],
                    },
                ).scalar_one()
                for index, suffix in enumerate(("A", "B"))
            ]

        with pytest.raises(IntegrityError, match="fk_task_step_history_phase_workflow"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.task_step_history "
                        "(task_id, workflow_id, mode_id, phase_id, verdict) "
                        "VALUES (:task_id, :workflow_id, :mode_id, :phase_id, 'partial')"
                    ),
                    {
                        "task_id": task_ids[0],
                        "workflow_id": workflow_ids[0],
                        "mode_id": mode_ids[0],
                        "phase_id": phase_ids[1],
                    },
                )

        with pytest.raises(IntegrityError, match="fk_task_phase_events_phase_workflow"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.task_phase_events "
                        "(task_id, workflow_id, mode_id, phase_id, event_type) "
                        "VALUES (:task_id, :workflow_id, :mode_id, :phase_id, 'entered')"
                    ),
                    {
                        "task_id": task_ids[0],
                        "workflow_id": workflow_ids[0],
                        "mode_id": mode_ids[0],
                        "phase_id": phase_ids[1],
                    },
                )

        with engine.begin() as conn:
            step_history_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.task_step_history "
                    "(task_id, workflow_id, mode_id, phase_id, verdict) "
                    "VALUES (:task_id, :workflow_id, :mode_id, :phase_id, 'partial') RETURNING id"
                ),
                {
                    "task_id": task_ids[0],
                    "workflow_id": workflow_ids[0],
                    "mode_id": mode_ids[0],
                    "phase_id": phase_ids[0],
                },
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO project_workflow.task_phase_events "
                    "(task_id, workflow_id, mode_id, phase_id, event_type) "
                    "VALUES (:task_id, :workflow_id, :mode_id, :phase_id, 'entered')"
                ),
                {
                    "task_id": task_ids[0],
                    "workflow_id": workflow_ids[0],
                    "mode_id": mode_ids[0],
                    "phase_id": phase_ids[0],
                },
            )

        with pytest.raises(IntegrityError, match="fk_task_phase_events_step_task_execution"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.task_phase_events "
                        "(task_id, workflow_id, mode_id, phase_id, step_history_id, event_type) "
                        "VALUES (:task_id, :workflow_id, :mode_id, :phase_id, :step_history_id, 'entered')"
                    ),
                    {
                        "task_id": task_ids[1],
                        "workflow_id": workflow_ids[1],
                        "mode_id": mode_ids[1],
                        "phase_id": phase_ids[1],
                        "step_history_id": step_history_id,
                    },
                )

        with pytest.raises(IntegrityError, match="fk_task_step_history_task_workflow"):
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM project_workflow.tasks WHERE id = :task_id"),
                    {"task_id": task_ids[0]},
                )

    def test_bootstrap_is_idempotent(self, pg_url):
        from scripts.init_db import main

        assert main() == 0
        assert main() == 0

        engine = get_engine(pg_url)
        with engine.connect() as conn:
            counts = {
                table: conn.execute(
                    text(f"SELECT count(*) FROM project_workflow.{table}")
                ).scalar_one()
                for table in ("workflows", "projects", "agents", "phases")
            }
        assert counts == {"workflows": 7, "projects": 7, "agents": 7, "phases": 33}

    def test_two_concurrent_init_processes_are_idempotent(self, pg_url):
        env = os.environ.copy()
        env.update(
            {
                "DATABASE_URL": pg_url,
                "DB_SCHEMA": "project_workflow",
                "PYTHONUTF8": "1",
            }
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: _run_process(["-m", "scripts.init_db"], env), range(2)))
        assert [result.returncode for result in results] == [0, 0], [
            result.stderr or result.stdout for result in results
        ]

        uow = SAUnitOfWork(pg_url)
        assert {project.cli_command for project in uow.projects.list()} == {
            "workflow-project_manager",
            "workflow-analyst",
            "workflow-architect",
            "workflow-developer",
            "workflow-reviewer",
            "workflow-tester",
            "workflow-devops",
        }
        assert len([workflow for workflow in uow.workflows.list() if workflow.is_default]) == 1
        uow.close()

    def test_supervisor_concurrent_get_or_create_returns_one_task(self, pg_url):
        from project_workflow.supervisor import SupervisorEngine

        _initialize_legacy_database(pg_url)
        barrier = Barrier(2)
        thread_state = local()
        original_get = TaskService.get_task_by_key

        def synchronized_first_get(service, task_key, workflow_id=None, project_id=None):
            if not getattr(thread_state, "initial_lookup_done", False):
                thread_state.initial_lookup_done = True
                barrier.wait(timeout=10)
            return original_get(service, task_key, workflow_id=workflow_id, project_id=project_id)

        def create() -> int:
            uow = SAUnitOfWork(pg_url)
            try:
                return int(SupervisorEngine("RUN-90001", uow=uow).task["id"])
            finally:
                uow.close()

        with (
            patch.object(TaskService, "get_task_by_key", synchronized_first_get),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            task_ids = list(pool.map(lambda _: create(), range(2)))

        assert task_ids[0] == task_ids[1]
        verify = SAUnitOfWork(pg_url)
        assert len([task for task in verify.tasks.list() if task.task_key == "RUN-90001"]) == 1
        verify.close()

    def test_concurrent_runtime_assignment_reconciles_one_ledger_record(self, pg_url):
        ensure_migrated(get_engine(pg_url))
        setup = SAUnitOfWork(pg_url)
        workflow_id = setup.workflows.create(
            {"key": "hermes-sdlc:developer", "name": "Runtime assignment race",
             "active_catalog_version": 2, "create_default_mode": False}
        )
        initial_mode = setup.workflows.create_mode(
            {
                "workflow_id": workflow_id,
                "key": "initial",
                "name": "Initial",
                "mode_order": 1,
                "role_key": "developer",
                "catalog_version": 2,
                "execution_scopes": ["delivery", "aggregate"],
                "tech_workspace_policy": "required",
            }
        )
        project_id = setup.projects.create(
            {
                "workflow_id": workflow_id,
                "code": "RACE",
                "name": "Race",
                "cli_command": "race",
                "key_prefixes": ["RACE"],
            }
        )
        setup.phases.create(
            {
                "workflow_id": workflow_id,
                "mode_id": initial_mode,
                "code": "start",
                "name": "Start",
                "phase_order": 1,
            }
        )
        setup.commit()
        setup.close()
        barrier = Barrier(2)

        def assign() -> dict:
            uow = SAUnitOfWork(pg_url)
            barrier.wait(timeout=10)
            try:
                return TaskService(uow).assign_runtime_task(
                    project_id=project_id,
                    task_key="RACE-1",
                    mode_key="initial",
                    cycle_number=0,
                    operation_key="runtime-race-operation",
                    expected_revision=0,
                    expected_status="missing",
                    **_runtime_binding("runtime-race-operation"),
                )
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: assign(), range(2)))

        assert {result["id"] for result in results} == {results[0]["id"]}
        verify = SAUnitOfWork(pg_url)
        task = verify.tasks.get_by_key("RACE-1", project_id=project_id)
        assert task is not None
        assert [item.operation_key for item in verify.tasks.list_assignments(task.id)] == [
            "runtime-race-operation"
        ]
        verify.close()

    def test_concurrent_runtime_bind_reconciles_one_real_binding(self, pg_url):
        ensure_migrated(get_engine(pg_url))
        setup = SAUnitOfWork(pg_url)
        workflow_id = setup.workflows.create(
            {"key": "hermes-sdlc:developer", "name": "Runtime bind race",
             "active_catalog_version": 2, "create_default_mode": False}
        )
        mode_id = setup.workflows.create_mode(
            {
                "workflow_id": workflow_id,
                "key": "initial",
                "name": "Initial",
                "mode_order": 1,
                "role_key": "developer",
                "catalog_version": 2,
                "execution_scopes": ["delivery", "aggregate"],
                "tech_workspace_policy": "required",
            }
        )
        setup.phases.create(
            {
                "workflow_id": workflow_id,
                "mode_id": mode_id,
                "code": "start",
                "name": "Start",
                "phase_order": 1,
            }
        )
        project_id = setup.projects.create(
            {
                "workflow_id": workflow_id,
                "code": "BIND-RACE",
                "name": "Bind race",
                "cli_command": "bind-race",
                "key_prefixes": ["BIND"],
            }
        )
        accepted = TaskService(setup).assign_runtime_task(
            project_id=project_id,
            task_key="BIND-1",
            mode_key="initial",
            cycle_number=0,
            operation_key="assign-bind-race",
            expected_revision=0,
            expected_status="missing",
            **_runtime_binding("assign-bind-race"),
        )
        setup.close()
        barrier = Barrier(2)

        def bind() -> dict:
            uow = SAUnitOfWork(pg_url)
            barrier.wait(timeout=10)
            try:
                return _bind_runtime_assignment(uow, project_id, accepted)
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: bind(), range(2)))

        assert {result["binding_state"] for result in results} == {"bound"}
        assert {result["binding_ref"] for result in results} == {
            "binding:assign-bind-race"
        }
        verify = SAUnitOfWork(pg_url)
        task = verify.tasks.get_by_key("BIND-1", project_id=project_id)
        assert task is not None and task.id is not None
        assignments = verify.tasks.list_assignments(task.id)
        assert len(assignments) == 1
        assert assignments[0].bind_operation_key == "bind:assign-bind-race"
        verify.close()

    def test_concurrent_existing_task_assignment_rechecks_ledger_after_row_lock(self, pg_url):
        from project_workflow.infrastructure.db.repositories.project import SAProjectRepository
        from project_workflow.infrastructure.db.repositories.task import SATaskRepository

        ensure_migrated(get_engine(pg_url))
        setup = SAUnitOfWork(pg_url)
        workflow_id = setup.workflows.create(
            {"key": "hermes-sdlc:developer", "name": "Existing assignment race",
             "active_catalog_version": 2, "create_default_mode": False}
        )
        initial_mode = setup.workflows.create_mode(
            {
                "workflow_id": workflow_id,
                "key": "initial",
                "name": "Initial",
                "mode_order": 1,
                "role_key": "developer",
                "catalog_version": 2,
                "execution_scopes": ["delivery", "aggregate"],
                "tech_workspace_policy": "required",
            }
        )
        rework_id = setup.workflows.create_mode(
            {
                "workflow_id": workflow_id,
                "key": "rework",
                "name": "Rework",
                "mode_order": 2,
                "role_key": "developer",
                "catalog_version": 2,
                "execution_scopes": ["delivery", "aggregate"],
                "tech_workspace_policy": "required",
            }
        )
        setup.phases.create(
            {
                "workflow_id": workflow_id,
                "mode_id": initial_mode,
                "code": "start",
                "name": "Start",
                "phase_order": 1,
            }
        )
        setup.phases.create(
            {"workflow_id": workflow_id, "mode_id": rework_id, "code": "fix", "name": "Fix", "phase_order": 1}
        )
        project_id = setup.projects.create(
            {
                "workflow_id": workflow_id,
                "code": "EXISTING-RACE",
                "name": "Existing race",
                "cli_command": "existing-race",
                "key_prefixes": ["EXISTING"],
            }
        )
        initial = TaskService(setup).assign_runtime_task(
            project_id=project_id,
            task_key="EXISTING-1",
            mode_key="initial",
            cycle_number=0,
            operation_key="existing-race-a",
            expected_revision=0,
            expected_status="missing",
            **_runtime_binding("existing-race-a"),
        )
        setup.tasks.update(initial["id"], {"status": "done"})
        setup.commit()
        setup.close()

        lookup_started = Barrier(2)
        lookup_finished = Barrier(2)
        thread_state = local()
        original_project_get = SAProjectRepository.get_by_id
        original_assignment_get = SATaskRepository.get_assignment_by_operation_key

        def unlocked_project(repo, candidate_project_id):
            return original_project_get(repo, candidate_project_id)

        def synchronized_initial_lookup(repo, operation_key):
            if operation_key == "existing-race-b" and not getattr(thread_state, "looked_up", False):
                thread_state.looked_up = True
                lookup_started.wait(timeout=10)
                result = original_assignment_get(repo, operation_key)
                lookup_finished.wait(timeout=10)
                return result
            return original_assignment_get(repo, operation_key)

        def assign() -> dict:
            uow = SAUnitOfWork(pg_url)
            try:
                return TaskService(uow).assign_runtime_task(
                    project_id=project_id,
                    task_key="EXISTING-1",
                    mode_key="rework",
                    cycle_number=1,
                    operation_key="existing-race-b",
                    expected_revision=1,
                    expected_status="done",
                    expected_mode_key="initial",
                    expected_cycle_number=0,
                    **_runtime_binding("existing-race-b"),
                )
            finally:
                uow.close()

        with (
            patch.object(SAProjectRepository, "lock", unlocked_project),
            patch.object(
                SATaskRepository,
                "get_assignment_by_operation_key",
                synchronized_initial_lookup,
            ),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            results = list(pool.map(lambda _: assign(), range(2)))

        assert {result["assignment_revision"] for result in results} == {2}
        assert {result["assignment_operation_key"] for result in results} == {"existing-race-b"}
        assert {result["status"] for result in results} == {"active"}
        verify = SAUnitOfWork(pg_url)
        task = verify.tasks.get_by_key("EXISTING-1", project_id=project_id)
        assert task is not None
        assert task.mode_id == rework_id
        assert task.cycle_number == 1
        assert [item.operation_key for item in verify.tasks.list_assignments(task.id)] == [
            "existing-race-a",
            "existing-race-b",
        ]
        verify.close()

    def test_concurrent_runtime_steps_reconcile_global_operation_key(self, pg_url, monkeypatch):
        """Different task transactions cannot turn one global key race into a 500/503."""
        ensure_migrated(get_engine(pg_url))
        runtime_token = "runtime-developer-token-1234567890"
        monkeypatch.setenv(
            "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
            json.dumps({"developer": runtime_token}),
        )
        config_module.get_settings.cache_clear()

        setup = SAUnitOfWork(pg_url)
        ensure_managed_catalog(setup)
        project = setup.projects.get_by_cli_command("workflow-developer")
        assert project is not None and project.id is not None
        project_id = project.id
        assignments = []
        for number in (1, 2):
            operation_key = f"assign-runtime-race-{number}"
            accepted = TaskService(setup).assign_runtime_task(
                project_id=project_id,
                task_key=f"RACE-{number}",
                mode_key="initial",
                cycle_number=0,
                operation_key=operation_key,
                expected_revision=0,
                expected_status="missing",
                **_runtime_binding(operation_key),
            )
            assignments.append(_bind_runtime_assignment(setup, project_id, accepted))
        setup.commit()
        setup.close()

        common_step_key = "step:global-runtime-race"
        payloads = [
            {
                "task": assignment["task_key"],
                "report": "Готово",
                "step_operation_key": common_step_key,
                "assignment_revision": assignment["assignment_revision"],
                "assignment_ref": assignment["assignment_ref"],
                "binding_ref": assignment["binding_ref"],
                "hermes_run_ref": assignment["hermes_run_ref"],
                "mode_key": assignment["mode_key"],
                "cycle_number": assignment["cycle_number"],
                "attempt_number": assignment["attempt_number"],
                "expected_phase_code": assignment["current_phase_code"],
                "expected_status": assignment["status"],
            }
            for assignment in assignments
        ]
        provider_barrier = Barrier(2)

        def pass_after_both_transactions_started(*_args, **kwargs):
            provider_barrier.wait(timeout=10)
            return _pass_response(kwargs["user_prompt"])

        def submit(payload: dict[str, object]) -> tuple[int, dict[str, object]]:
            response = client.post(
                "/internal/runtime/step",
                headers={"Authorization": f"Bearer {runtime_token}"},
                json=payload,
            )
            return response.status_code, response.json()

        # Concurrent requests share one application lifetime, as in the server.
        # Separate clients would reset the shared engine during another request.
        with (
            TestClient(create_app()) as client,
            patch.object(OpenAICompatibleClient, "chat", side_effect=pass_after_both_transactions_started),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            responses = list(pool.map(submit, payloads))

        assert sorted(status for status, _ in responses) == [200, 409]
        assert all(status not in {500, 503} for status, _ in responses)
        assert any(
            body.get("error") == "step_operation_key уже использован для другого runtime step"
            for status, body in responses
            if status == 409
        )
        verify = SAUnitOfWork(pg_url)
        rows = [row for row in verify.step_history.list(limit=None) if row.step_operation_key == common_step_key]
        assert len(rows) == 1
        verify.close()

    def test_orm_create_all_is_rejected_for_postgresql(self, pg_url):
        engine = get_engine(pg_url)
        with pytest.raises(RuntimeError, match="изолированных тестах SQLite"):
            ensure_schema(engine)
    @pytest.mark.parametrize("work_item_revision", [1790840000123, (1 << 63) - 1])
    def test_upgrade_bound_assignment_preserves_rows_and_accepts_native_wide_revision(self, pg_url, work_item_revision):
        engine = get_engine(pg_url)
        run_alembic_command("upgrade", engine, "0003_runtime_assignment_bind")
        # Seed the exact pre-0004 shape with SQL; current ORM includes later catalog columns.
        with engine.begin() as connection:
            workflow_id = connection.execute(text(
                "INSERT INTO project_workflow.workflows(key,name,is_default) "
                "VALUES ('hermes-sdlc:developer','Legacy Developer',1) RETURNING id"
            )).scalar_one()
            mode_id = connection.execute(text(
                "INSERT INTO project_workflow.workflow_modes "
                "(workflow_id,key,name,mode_order,role_key,execution_scope,tech_workspace_policy) "
                "VALUES (:workflow,'initial','Initial',1,'developer','delivery','required') RETURNING id"
            ), {"workflow": workflow_id}).scalar_one()
            phase_id = connection.execute(text(
                "INSERT INTO project_workflow.phases(workflow_id,mode_id,code,name,phase_order) "
                "VALUES (:workflow,:mode,'DV-WIDE-OLD-01','Legacy intake',1) RETURNING id"
            ), {"workflow": workflow_id, "mode": mode_id}).scalar_one()
            project_id = connection.execute(text(
                "INSERT INTO project_workflow.projects(workflow_id,code,name,cli_command) "
                "VALUES (:workflow,'DEV','Developer','workflow-developer') RETURNING id"
            ), {"workflow": workflow_id}).scalar_one()
            task_id = connection.execute(text(
                "INSERT INTO project_workflow.tasks "
                "(project_id,workflow_id,mode_id,task_key,current_phase_id,"
                "assignment_revision,assignment_operation_key) "
                "VALUES (:project,:workflow,:mode,'WIDE-1',:phase,1,'wide-old-assignment') RETURNING id"
            ), {"project": project_id, "workflow": workflow_id, "mode": mode_id, "phase": phase_id}).scalar_one()
            legacy = {**_runtime_binding("wide-old-assignment"), "task_id": task_id, "project_id": project_id,
                "workflow_id": workflow_id, "mode_id": mode_id, "operation_key": "wide-old-assignment",
                "cycle_number": 0, "assignment_revision": 1, "binding_ref": "legacy-binding",
                "hermes_run_ref": "legacy-run", "bind_operation_key": "legacy-bind", "bind_request_sha256": "b" * 64,
                "payload_sha256": "a" * 64, "payload": "{}"}
            legacy.pop("runtime_compatibility")
            legacy["exact_input_refs"] = json.dumps(legacy["exact_input_refs"])
            columns = ",".join(legacy)
            parameters = ",".join(f":{key}" for key in legacy)
            connection.execute(text(
                f"INSERT INTO project_workflow.task_runtime_assignments ({columns}) VALUES ({parameters})"
            ), legacy)
        request = {"project_id": project_id, "task_key": "WIDE-1", "mode_key": "initial", "cycle_number": 0,
            "operation_key": "wide-old-assignment", "expected_revision": 0, "expected_status": "missing",
            **_runtime_binding("wide-old-assignment")}
        with engine.connect() as connection:
            before = connection.execute(text(
                "SELECT to_jsonb(t)::text FROM project_workflow.task_runtime_assignments t ORDER BY id"
            )).scalars().all()
        ensure_migrated(engine)
        with engine.connect() as connection:
            after = connection.execute(text(
                "SELECT to_jsonb(t)::text FROM project_workflow.task_runtime_assignments t ORDER BY id"
            )).scalars().all()
        assert [json.loads(row) for row in after] == [
            {**json.loads(row), "concrete_agent_ref": None} for row in before
        ]
        with SAUnitOfWork(engine) as uow:
            new_mode = uow.workflows.create_mode({"workflow_id": workflow_id, "key": "initial", "name": "Initial",
                "mode_order": 1, "role_key": "developer", "execution_scope": "delivery",
                "execution_scopes": ["delivery", "aggregate"], "tech_workspace_policy": "required",
                "catalog_version": 2})
            uow.phases.create({"workflow_id": workflow_id, "mode_id": new_mode, "code": "DV-WIDE-V2-01",
                "name": "V2 intake", "phase_order": 1})
            uow.workflows.update(workflow_id, {"active_catalog_version": 2})
            uow.commit()
            request.update(task_key="WIDE-2", operation_key="wide-native-assignment",
                           **_runtime_binding("wide-native-assignment"))
            request["work_item_revision"] = work_item_revision
            accepted = TaskService(uow).assign_runtime_task(**request)
            assert accepted["work_item_revision"] == work_item_revision
            assert TaskService(uow).assign_runtime_task(**request) == accepted
            bound = _bind_runtime_assignment(uow, project_id, accepted)
            assert bound["work_item_revision"] == work_item_revision
        ensure_migrated(engine)
        assert schema_is_ready(engine)
        with SAUnitOfWork(engine) as uow:
            assert uow.tasks.get_assignment_by_operation_key("wide-native-assignment").work_item_revision == (
                work_item_revision
            )


@pytest.mark.integration
class TestPostgresUoW:
    def test_create_and_read_workflow_project_task(self, pg_url):
        ensure_migrated(get_engine(pg_url))
        uow = SAUnitOfWork(pg_url)
        with uow:
            wf_id = uow.workflows.create({"name": "Test Workflow", "description": "Test", "is_default": True})
            workflows = {w.name: w.id for w in uow.workflows.list()}
            assert workflows.get("Test Workflow") == wf_id

            proj_id = uow.projects.create(
                {"workflow_id": wf_id, "code": "TST", "name": "Default", "key_prefixes": ["TST"]}
            )
            projects = {p.code: p.id for p in uow.projects.list()}
            assert projects.get("TST") == proj_id

            phase_id = uow.phases.create(
                {"workflow_id": wf_id, "code": "start", "name": "Start", "phase_order": 1}
            )
            task_id = uow.tasks.create(
                {
                    "project_id": proj_id,
                    "workflow_id": wf_id,
                    "task_key": "TST-1",
                    "title": "First task",
                    "current_phase_id": phase_id,
                }
            )
            tasks = {t.task_key: t.id for t in uow.tasks.list()}
            assert tasks.get("TST-1") == task_id
            uow.commit()

    def test_repository_list_reads_have_deterministic_id_order(self, pg_url):
        _initialize_legacy_database(pg_url)
        uow = SAUnitOfWork(pg_url)
        workflow = uow.workflows.get_default()
        assert workflow is not None and workflow.id is not None
        phase = uow.phases.get_by_code(int(workflow.id), "1.INTAKE")
        assert phase is not None and phase.id is not None
        project = uow.projects.list()[0]
        uow.projects.create(
            {
                "workflow_id": int(workflow.id),
                "code": "ORDERING",
                "name": "Ordering project",
                "description": "",
                "key_prefixes": ["ORD"],
            }
        )
        task_id = uow.tasks.create(
            {
                "project_id": int(project.id),
                "workflow_id": int(workflow.id),
                "task_key": "RUN-ORDER",
                "title": "Ordering test",
                "current_phase_id": phase.id,
            }
        )
        history_phases = list(uow.phases.list(int(workflow.id)))[:3]
        for history_phase in history_phases:
            assert history_phase.id is not None
            uow.tasks.record_phase_event(task_id, int(history_phase.id), "blocked")

        uow.session.execute(text("CREATE INDEX checks_desc_test_idx ON phase_checks (id DESC)"))
        uow.session.execute(text("CREATE INDEX evidence_desc_test_idx ON phase_evidence_requirements (id DESC)"))
        uow.session.execute(text("CREATE INDEX phase_events_desc_test_idx ON task_phase_events (id DESC)"))
        uow.session.execute(text("CREATE INDEX agents_desc_test_idx ON agents (id DESC)"))
        uow.session.execute(text("CREATE INDEX projects_desc_test_idx ON projects (id DESC)"))
        uow.commit()
        uow.session.execute(text("CLUSTER phase_checks USING checks_desc_test_idx"))
        uow.session.execute(text("CLUSTER phase_evidence_requirements USING evidence_desc_test_idx"))
        uow.session.execute(text("CLUSTER task_phase_events USING phase_events_desc_test_idx"))
        uow.session.execute(text("CLUSTER agents USING agents_desc_test_idx"))
        uow.session.execute(text("CLUSTER projects USING projects_desc_test_idx"))
        uow.commit()
        uow.session.execute(text("SET LOCAL enable_indexscan = off"))
        uow.session.execute(text("SET LOCAL enable_bitmapscan = off"))

        phase_checks = list(uow.phases.get_checks(int(phase.id)))
        phase_evidence = list(uow.phases.get_evidence(int(phase.id)))
        checks = list(uow.phase_checks.list(int(phase.id)))
        evidence = list(uow.phase_evidence_requirements.list(int(phase.id)))
        history = list(uow.tasks.list_phase_events(task_id))
        batch_history = list(uow.tasks.list_phase_events_batch([task_id])[task_id])
        agents = list(uow.agents.list())
        projects = list(uow.projects.list())

        assert [row["id"] for row in phase_checks] == sorted(row["id"] for row in phase_checks)
        assert [row["id"] for row in phase_evidence] == sorted(row["id"] for row in phase_evidence)
        assert [row["id"] for row in checks] == sorted(row["id"] for row in checks)
        assert [row["id"] for row in evidence] == sorted(row["id"] for row in evidence)
        assert [row.id for row in history] == sorted(row.id for row in history)
        assert [row.id for row in batch_history] == sorted(row.id for row in batch_history)
        assert [agent.id for agent in agents] == sorted(agent.id for agent in agents)
        assert [item.id for item in projects] == sorted(item.id for item in projects)
        uow.close()

    def test_ensure_phase_catalog_populates_an_empty_default_workflow(self, pg_url):
        from project_workflow.infrastructure.db import schema as schema_module

        ensure_migrated(get_engine(pg_url))
        uow = SAUnitOfWork(pg_url)
        with uow:
            default_wf_id = uow.workflows.create({"name": "Default", "description": "default", "is_default": True})
            uow.projects.create(
                {
                    "workflow_id": default_wf_id,
                    "code": "DEFAULT",
                    "name": "Default Project",
                    "key_prefixes": ["DEFAULT"],
                }
            )
            uow.commit()

        schema_module.ensure_phase_catalog(uow)
        with uow:
            default_wf = uow.workflows.get_default()
            phases = uow.phases.list(workflow_id=default_wf.id)
            assert [phase.code for phase in phases] == [
                phase.code for phase in schema_module.load_phases_from_seed()
            ]

    def test_uow_commit_and_rollback(self, pg_url):
        ensure_migrated(get_engine(pg_url))
        uow = SAUnitOfWork(pg_url)
        with uow:
            wf_id = uow.workflows.create({"name": "Rollback WF", "description": "rollback"})
            uow.rollback()

        with uow:
            ids = {w.id for w in uow.workflows.list()}
            assert wf_id not in ids

    def test_concurrent_task_and_legacy_prefix_update_can_both_commit(self, pg_url):
        _initialize_legacy_database(pg_url)
        setup = SAUnitOfWork(pg_url)
        workflow_id = setup.workflows.get_default().id
        project = ProjectService(setup).create_project(
            {
                "code": "RACE",
                "name": "Race",
                "key_prefixes": ["RACE"],
                "workflow_id": workflow_id,
            }
        )
        setup.close()
        barrier = Barrier(2)

        def create_task() -> str:
            uow = SAUnitOfWork(pg_url)
            barrier.wait()
            try:
                TaskService(uow).create_task(
                    {"project_id": project["id"], "task_key": "RACE-1", "title": "Race"}
                )
                return "created"
            except ConflictError:
                uow.rollback()
                return "rejected"
            finally:
                uow.close()

        def update_prefix() -> str:
            uow = SAUnitOfWork(pg_url)
            barrier.wait()
            try:
                ProjectService(uow).update_project(project["id"], {"key_prefixes": ["NEW"]})
                return "updated"
            except ConflictError:
                uow.rollback()
                return "rejected"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            task_result = pool.submit(create_task)
            update_result = pool.submit(update_prefix)
            outcomes = {task_result.result(), update_result.result()}
        assert outcomes == {"created", "updated"}

        verify = SAUnitOfWork(pg_url)
        stored_project = verify.projects.get_by_id(project["id"])
        stored_task = verify.tasks.get_by_key("RACE-1", project_id=project["id"])
        assert stored_project is not None
        assert stored_task is not None
        assert stored_project.key_prefixes == ["NEW"]
        verify.close()

    def test_concurrent_project_creates_allow_same_legacy_prefix(self, pg_url):
        _initialize_legacy_database(pg_url)
        setup = SAUnitOfWork(pg_url)
        workflow_id = setup.workflows.get_default().id
        setup.close()
        barrier = Barrier(2)

        def create(code: str) -> str:
            uow = SAUnitOfWork(pg_url)
            barrier.wait()
            try:
                ProjectService(uow).create_project(
                    {
                        "code": code,
                        "name": code,
                        "key_prefixes": ["SHARED"],
                        "workflow_id": workflow_id,
                    }
                )
                return "created"
            except ConflictError:
                uow.rollback()
                return "rejected"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(create, ["PREFIX-A", "PREFIX-B"]))
        assert sorted(outcomes) == ["created", "created"]

    def test_task_creation_serializes_with_phase_deletion(self, pg_url):
        ensure_migrated(get_engine(pg_url))
        setup = SAUnitOfWork(pg_url)
        workflow_id = setup.workflows.create({"name": "Phase race", "description": ""})
        first_id = setup.phases.create(
            {"workflow_id": workflow_id, "code": "race.first", "name": "First", "phase_order": 1}
        )
        setup.phases.create(
            {"workflow_id": workflow_id, "code": "race.second", "name": "Second", "phase_order": 2}
        )
        setup.commit()
        project = ProjectService(setup).create_project(
            {
                "workflow_id": workflow_id,
                "code": "PHASE-RACE",
                "name": "Phase race",
                "key_prefixes": ["PHASERACE"],
            }
        )
        setup.close()

        task_holds_workflow_lock = Event()
        delete_started_lock = Event()
        release_task = Event()

        def create_task() -> str:
            uow = SAUnitOfWork(pg_url)
            original_list = uow.phases.list

            def paused_list(workflow_id: int, *, mode_id: int | None = None):
                task_holds_workflow_lock.set()
                assert release_task.wait(10)
                return original_list(workflow_id, mode_id=mode_id)

            uow.phases.list = paused_list
            try:
                TaskService(uow).create_task(
                    {
                        "project_id": project["id"],
                        "task_key": "PHASERACE-1",
                        "current_phase_id": first_id,
                    }
                )
                return "created"
            finally:
                uow.close()

        def delete_phase() -> str:
            uow = SAUnitOfWork(pg_url)
            original_lock = uow.workflows.lock

            def observed_lock(workflow_id_arg: int):
                delete_started_lock.set()
                return original_lock(workflow_id_arg)

            uow.workflows.lock = observed_lock
            try:
                PhaseServiceApp(uow).delete_phase(first_id)
                return "deleted"
            except ConflictError:
                uow.rollback()
                return "rejected"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            task_result = pool.submit(create_task)
            assert task_holds_workflow_lock.wait(10)
            delete_result = pool.submit(delete_phase)
            assert delete_started_lock.wait(10)
            release_task.set()
            assert task_result.result(timeout=20) == "created"
            assert delete_result.result(timeout=20) == "rejected"

        verify = SAUnitOfWork(pg_url)
        assert verify.tasks.get_by_key("PHASERACE-1") is not None
        assert verify.phases.get_by_id(first_id) is not None
        verify.close()

    @pytest.mark.parametrize("operation", ["project", "phase"])
    def test_workflow_delete_serializes_with_dependent_creation(self, pg_url, operation):
        ensure_migrated(get_engine(pg_url))
        setup = SAUnitOfWork(pg_url)
        workflow = WorkflowService(setup).create_workflow({"name": f"Delete race {operation}"})
        workflow_id = int(workflow["id"])
        setup.close()

        creator_holds_workflow_lock = Event()
        delete_started_lock = Event()
        release_creator = Event()

        def create_dependent() -> str:
            uow = SAUnitOfWork(pg_url)
            original_lock = uow.workflows.lock

            def paused_lock(workflow_id_arg: int):
                locked = original_lock(workflow_id_arg)
                creator_holds_workflow_lock.set()
                assert release_creator.wait(10)
                return locked

            uow.workflows.lock = paused_lock
            try:
                if operation == "project":
                    ProjectService(uow).create_project(
                        {
                            "workflow_id": workflow_id,
                            "code": "DELETE-RACE",
                            "name": "Delete race",
                            "key_prefixes": ["DELETERACE"],
                        }
                    )
                else:
                    PhaseServiceApp(uow).create_phase(
                        {
                            "workflow_id": workflow_id,
                            "code": "delete.race.phase",
                            "name": "Delete race phase",
                            "phase_order": 2,
                        }
                    )
                return "created"
            finally:
                uow.close()

        def delete_workflow() -> str:
            uow = SAUnitOfWork(pg_url)
            original_lock = uow.workflows.lock

            def observed_lock(workflow_id_arg: int):
                delete_started_lock.set()
                return original_lock(workflow_id_arg)

            uow.workflows.lock = observed_lock
            try:
                WorkflowService(uow).delete_workflow(workflow_id)
                return "deleted"
            except ConflictError:
                uow.rollback()
                return "rejected"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            create_result = pool.submit(create_dependent)
            assert creator_holds_workflow_lock.wait(10)
            delete_result = pool.submit(delete_workflow)
            assert delete_started_lock.wait(10)
            release_creator.set()
            assert create_result.result(timeout=20) == "created"
            assert delete_result.result(timeout=20) == "rejected"

        verify = SAUnitOfWork(pg_url)
        assert verify.workflows.get_by_id(workflow_id) is not None
        if operation == "project":
            assert verify.projects.get_by_code("DELETE-RACE") is not None
        else:
            assert verify.phases.get_by_code(workflow_id, "delete.race.phase") is not None
        verify.close()

    def test_project_move_serializes_with_task_creation(self, pg_url):
        ensure_migrated(get_engine(pg_url))
        setup = SAUnitOfWork(pg_url)
        source = WorkflowService(setup).create_workflow({"name": "Move race source"})
        target = WorkflowService(setup).create_workflow({"name": "Move race target"})
        project = ProjectService(setup).create_project(
            {
                "workflow_id": source["id"],
                "code": "MOVE-RACE",
                "name": "Move race",
                "key_prefixes": ["MOVERACE"],
            }
        )
        setup.close()

        task_holds_workflow_lock = Event()
        move_started_lock = Event()
        release_task = Event()

        def create_task() -> str:
            uow = SAUnitOfWork(pg_url)
            original_project_lock = uow.projects.lock

            def paused_project_lock(project_id_arg: int):
                locked = original_project_lock(project_id_arg)
                task_holds_workflow_lock.set()
                assert release_task.wait(10)
                return locked

            uow.projects.lock = paused_project_lock
            try:
                TaskService(uow).create_task(
                    {"project_id": project["id"], "task_key": "MOVERACE-1"}
                )
                return "created"
            finally:
                uow.close()

        def move_project() -> str:
            uow = SAUnitOfWork(pg_url)
            original_lock = uow.workflows.lock

            def observed_lock(workflow_id_arg: int):
                move_started_lock.set()
                return original_lock(workflow_id_arg)

            uow.workflows.lock = observed_lock
            try:
                ProjectService(uow).update_project(
                    project["id"], {"workflow_id": target["id"]}
                )
                return "moved"
            except ConflictError:
                uow.rollback()
                return "rejected"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            task_result = pool.submit(create_task)
            assert task_holds_workflow_lock.wait(10)
            move_result = pool.submit(move_project)
            assert move_started_lock.wait(10)
            release_task.set()
            assert task_result.result(timeout=20) == "created"
            assert move_result.result(timeout=20) == "rejected"

        verify = SAUnitOfWork(pg_url)
        stored_project = verify.projects.get_by_id(project["id"])
        assert stored_project is not None and stored_project.workflow_id == source["id"]
        assert verify.tasks.get_by_key("MOVERACE-1") is not None
        verify.close()

    def test_agent_assignment_serializes_with_delete(self, pg_url):
        ensure_migrated(get_engine(pg_url))
        setup = SAUnitOfWork(pg_url)
        workflow = WorkflowService(setup).create_workflow({"name": "Agent assignment race"})
        phase = setup.phases.list(int(workflow["id"]))[0]
        agent = AgentService(setup).create_agent({"name": "Race agent"})
        setup.close()

        assignment_holds_agent = Event()
        delete_started = Event()
        release_assignment = Event()

        def assign() -> str:
            uow = SAUnitOfWork(pg_url)
            original_lock = uow.agents.lock

            def paused_lock(agent_id: int):
                locked = original_lock(agent_id)
                assignment_holds_agent.set()
                assert release_assignment.wait(10)
                return locked

            uow.agents.lock = paused_lock
            try:
                PhaseServiceApp(uow).update_phase(int(phase.id), {"agent_id": int(agent["id"])})
                return "assigned"
            finally:
                uow.close()

        def delete() -> str:
            uow = SAUnitOfWork(pg_url)
            original_lock = uow.agents.lock

            def observed_lock(agent_id: int):
                delete_started.set()
                return original_lock(agent_id)

            uow.agents.lock = observed_lock
            try:
                AgentService(uow).delete_agent(int(agent["id"]))
                return "deleted"
            except ConflictError:
                return "rejected"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            assignment_result = pool.submit(assign)
            assert assignment_holds_agent.wait(10)
            delete_result = pool.submit(delete)
            assert delete_started.wait(10)
            release_assignment.set()
            assert assignment_result.result(timeout=20) == "assigned"
            assert delete_result.result(timeout=20) == "rejected"

        verify = SAUnitOfWork(pg_url)
        assert verify.agents.get_by_id(int(agent["id"])) is not None
        assert verify.phases.get_by_id(int(phase.id)).agent_id == agent["id"]
        verify.close()

    @pytest.mark.parametrize("operation", ["create", "update"])
    def test_concurrent_hermes_profile_claim_is_domain_conflict(self, pg_url, operation):
        ensure_migrated(get_engine(pg_url))
        agent_ids: list[int] = []
        if operation == "update":
            setup = SAUnitOfWork(pg_url)
            agent_ids = [
                int(AgentService(setup).create_agent({"name": f"Profile owner {index}"})["id"])
                for index in range(2)
            ]
            setup.close()
        barrier = Barrier(2)

        def claim(index: int) -> str:
            uow = SAUnitOfWork(pg_url)
            repository_method = uow.agents.create if operation == "create" else uow.agents.update

            def synchronized_write(*args, **kwargs):
                barrier.wait(timeout=10)
                return repository_method(*args, **kwargs)

            if operation == "create":
                uow.agents.create = synchronized_write
            else:
                uow.agents.update = synchronized_write
            try:
                if operation == "create":
                    AgentService(uow).create_agent(
                        {"name": f"Concurrent profile {index}", "hermes_profile": "shared-race-profile"}
                    )
                else:
                    AgentService(uow).update_agent(
                        agent_ids[index], {"hermes_profile": "shared-race-profile"}
                    )
                return "saved"
            except ConflictError:
                return "conflict"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, range(2)))

        assert sorted(results) == ["conflict", "saved"]
        verify = SAUnitOfWork(pg_url)
        assert len([agent for agent in verify.agents.list() if agent.hermes_profile == "shared-race-profile"]) == 1
        verify.close()

    def test_concurrent_agent_name_claim_is_domain_conflict(self, pg_url):
        ensure_migrated(get_engine(pg_url))
        barrier = Barrier(2)

        def create(index: int) -> str:
            uow = SAUnitOfWork(pg_url)
            repository_method = uow.agents.create

            def synchronized_write(*args, **kwargs):
                barrier.wait(timeout=10)
                return repository_method(*args, **kwargs)

            uow.agents.create = synchronized_write
            try:
                AgentService(uow).create_agent(
                    {"name": "Shared reviewer", "description": f"attempt {index}"}
                )
                return "saved"
            except ConflictError:
                return "conflict"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, range(2)))

        assert sorted(results) == ["conflict", "saved"]
        verify = SAUnitOfWork(pg_url)
        assert len([agent for agent in verify.agents.list() if agent.name == "Shared reviewer"]) == 1
        verify.close()

    def test_catalog_mutation_during_supervisor_provider_call_fails_closed(self, pg_url):
        from project_workflow.infrastructure.llm import OpenAICompatibleClient
        from project_workflow.supervisor import SupervisorEngine

        _initialize_legacy_database(pg_url)
        provider_started = Event()
        release_provider = Event()

        def provider(*_args, **kwargs):
            provider_started.set()
            assert release_provider.wait(10)
            return _pass_response(str(kwargs["user"]))

        def evaluate() -> dict:
            uow = SAUnitOfWork(pg_url)
            try:
                with patch.object(OpenAICompatibleClient, "chat", side_effect=provider):
                    return SupervisorEngine("RUN-90002", uow=uow).evaluate("done")
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            result_future = pool.submit(evaluate)
            assert provider_started.wait(10)
            mutation = SAUnitOfWork(pg_url)
            workflow = mutation.workflows.get_default()
            assert workflow is not None and workflow.id is not None
            phase = mutation.phases.get_by_code(int(workflow.id), "1.INTAKE")
            assert phase is not None and phase.id is not None
            checks = [dict(row) for row in mutation.phases.get_checks(int(phase.id))]
            checks = [{"id": item["id"], "description": item["description"]} for item in checks]
            checks.append({"id": None, "description": "Concurrent PostgreSQL catalog check"})
            PhaseService(mutation).update_phase_detail(int(phase.id), {"checks": checks})
            mutation.close()
            release_provider.set()
            result = result_future.result(timeout=20)

        assert result["verdict"] == "BLOCKED"
        assert result["retryable"] is True
        verify = SAUnitOfWork(pg_url)
        task = verify.tasks.get_by_key("RUN-90002")
        assert task is not None and task.status == "blocked" and task.current_phase_code == "1.INTAKE"
        run = verify.step_history.list(task_key="RUN-90002", limit=1)[0]
        assert run.verdict == "blocked"
        assert run.replay_fingerprint is None
        verify.close()

    @pytest.mark.parametrize("field", ["checks", "evidence"])
    def test_phase_aggregate_swaps_nested_descriptions_without_replacing_ids(self, pg_url, field):
        _initialize_legacy_database(pg_url)
        uow = SAUnitOfWork(pg_url)
        workflow = uow.workflows.get_default()
        assert workflow is not None and workflow.id is not None
        phase = uow.phases.get_by_code(int(workflow.id), "2.REQUIREMENTS")
        assert phase is not None and phase.id is not None
        service = PhaseService(uow)
        before = service.get_phase_detail(int(phase.id))[field]
        assert len(before) >= 2
        first, second = before[:2]
        payload = [
            {"id": first["id"], "description": second["description"]},
            {"id": second["id"], "description": first["description"]},
            *[{"id": item["id"], "description": item["description"]} for item in before[2:]],
        ]

        result = service.update_phase_detail(int(phase.id), {field: payload})
        after = service.get_phase_detail(int(phase.id))[field]
        uow.close()

        assert result[field] == [item["id"] for item in before]
        assert after[0]["description"] == second["description"]
        assert after[1]["description"] == first["description"]

    def test_noop_catalog_save_during_provider_call_keeps_verdict_and_replay(self, pg_url):
        from project_workflow.infrastructure.llm import OpenAICompatibleClient
        from project_workflow.supervisor import SupervisorEngine

        _initialize_legacy_database(pg_url)
        provider_started = Event()
        release_provider = Event()

        def provider(*_args, **kwargs):
            provider_started.set()
            assert release_provider.wait(10)
            return _partial_response(str(kwargs["user"]))

        def evaluate() -> dict:
            uow = SAUnitOfWork(pg_url)
            try:
                with patch.object(OpenAICompatibleClient, "chat", side_effect=provider):
                    return SupervisorEngine("RUN-90003", uow=uow).evaluate("still working")
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            result_future = pool.submit(evaluate)
            assert provider_started.wait(10)
            mutation = SAUnitOfWork(pg_url)
            workflow = mutation.workflows.get_default()
            assert workflow is not None and workflow.id is not None
            phase = mutation.phases.get_by_code(int(workflow.id), "1.INTAKE")
            assert phase is not None and phase.id is not None
            detail = PhaseService(mutation).get_phase_detail(int(phase.id))
            PhaseService(mutation).update_phase_detail(
                int(phase.id),
                {
                    "instructions": [
                        {
                            "id": item["id"],
                            "description": item["description"],
                            "execution_type": item["execution_type"],
                            "skills": item["skills"],
                        }
                        for item in detail["instructions"]
                    ],
                    "checks": [
                        {"id": item["id"], "description": item["description"]}
                        for item in detail["checks"]
                    ],
                    "evidence": [
                        {"id": item["id"], "description": item["description"]}
                        for item in detail["evidence"]
                    ],
                },
            )
            mutation.close()
            release_provider.set()
            result = result_future.result(timeout=20)

        replay_uow = SAUnitOfWork(pg_url)
        try:
            with patch.object(OpenAICompatibleClient, "chat") as replay_provider:
                replay = SupervisorEngine("RUN-90003", uow=replay_uow).evaluate(
                    "still working"
                )
        finally:
            replay_uow.close()

        assert result["verdict"] == "PARTIAL"
        assert result["retryable"] is False
        assert replay["replayed"] is True
        replay_provider.assert_not_called()

    def test_assigned_agent_update_waits_for_supervisor_commit(self, pg_url):
        from project_workflow.infrastructure.llm import OpenAICompatibleClient
        from project_workflow.supervisor import SupervisorEngine

        _initialize_legacy_database(pg_url)
        setup = SAUnitOfWork(pg_url)
        workflow = setup.workflows.get_default()
        assert workflow is not None and workflow.id is not None
        phase = setup.phases.get_by_code(int(workflow.id), "1.INTAKE")
        assert phase is not None and phase.agent_id is not None
        agent_id = int(phase.agent_id)
        setup.close()

        evaluation_holds_workflow = Event()
        allow_evaluation_commit = Event()
        update_started = Event()
        update_finished = Event()

        def evaluate() -> dict:
            uow = SAUnitOfWork(pg_url)
            original_create_run = uow.record_step

            def paused_create_run(*args, **kwargs):
                evaluation_holds_workflow.set()
                assert allow_evaluation_commit.wait(10)
                return original_create_run(*args, **kwargs)

            uow.record_step = paused_create_run
            try:
                with patch.object(
                    OpenAICompatibleClient,
                    "chat",
                    side_effect=lambda *_args, **kwargs: _pass_response(str(kwargs["user"])),
                ):
                    return SupervisorEngine("RUN-90004", uow=uow).evaluate("done")
            finally:
                uow.close()

        def update_agent() -> str:
            uow = SAUnitOfWork(pg_url)
            try:
                update_started.set()
                AgentService(uow).update_agent(agent_id, {"name": "Обновлённый агент"})
                return "updated"
            finally:
                update_finished.set()
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            evaluation_result = pool.submit(evaluate)
            assert evaluation_holds_workflow.wait(10)
            update_result = pool.submit(update_agent)
            assert update_started.wait(10)
            update_was_serialized = not update_finished.wait(0.5)
            allow_evaluation_commit.set()
            evaluated = evaluation_result.result(timeout=20)
            updated = update_result.result(timeout=20)

        assert update_was_serialized
        assert evaluated["verdict"] == "PASS"
        assert updated == "updated"
        verify = SAUnitOfWork(pg_url)
        agent = verify.agents.get_by_id(agent_id)
        assert agent is not None and agent.name == "Обновлённый агент"
        verify.close()

    @pytest.mark.parametrize("operation", ["update", "delete", "reorder"])
    def test_instruction_mutation_serializes_with_phase_update(self, pg_url, operation):
        ensure_migrated(get_engine(pg_url))
        setup = SAUnitOfWork(pg_url)
        workflow = WorkflowService(setup).create_workflow({"name": f"Instruction race {operation}"})
        phase = setup.phases.list(int(workflow["id"]))[0]
        first = InstructionService(setup).create_instruction(int(phase.id), {"description": "first"})
        second = InstructionService(setup).create_instruction(int(phase.id), {"description": "second"})
        setup.close()

        instruction_holds_workflow = Event()
        phase_update_started = Event()
        release_instruction = Event()

        def mutate_instruction() -> str:
            uow = SAUnitOfWork(pg_url)
            repository_method = getattr(uow.phase_instructions, operation)

            def paused_write(*args, **kwargs):
                instruction_holds_workflow.set()
                assert release_instruction.wait(10)
                return repository_method(*args, **kwargs)

            setattr(uow.phase_instructions, operation, paused_write)
            try:
                service = InstructionService(uow)
                if operation == "update":
                    service.update_instruction(int(first["id"]), {"description": "updated"})
                elif operation == "delete":
                    service.delete_instruction(int(first["id"]))
                else:
                    service.reorder_instructions(
                        int(phase.id), [int(second["id"]), int(first["id"])]
                    )
                return "instruction-saved"
            finally:
                uow.close()

        def mutate_phase() -> str:
            uow = SAUnitOfWork(pg_url)
            original_lock = uow.workflows.lock

            def observed_lock(workflow_id: int):
                phase_update_started.set()
                return original_lock(workflow_id)

            uow.workflows.lock = observed_lock
            try:
                PhaseServiceApp(uow).update_phase(int(phase.id), {"name": f"Phase after {operation}"})
                return "phase-saved"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            instruction_result = pool.submit(mutate_instruction)
            assert instruction_holds_workflow.wait(10)
            phase_result = pool.submit(mutate_phase)
            assert phase_update_started.wait(10)
            release_instruction.set()
            assert instruction_result.result(timeout=20) == "instruction-saved"
            assert phase_result.result(timeout=20) == "phase-saved"

        verify = SAUnitOfWork(pg_url)
        assert verify.phases.get_by_id(int(phase.id)).name == f"Phase after {operation}"
        rows = list(verify.phase_instructions.list(int(phase.id)))
        if operation == "update":
            assert rows[0]["description"] == "updated"
        elif operation == "delete":
            assert [row["step_num"] for row in rows] == [1]
            assert rows[0]["id"] == second["id"]
        else:
            assert [row["id"] for row in rows] == [second["id"], first["id"]]
        verify.close()


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


def _partial_response(user_prompt: str) -> dict:
    response = _pass_response(user_prompt)
    response.update(
        {
            "verdict": "PARTIAL",
            "covered": [],
            "missing": response["covered"],
            "message": "work remains",
            "confidence": 0.5,
        }
    )
    return response


def _initialize_legacy_database(pg_url: str) -> None:
    """Create the explicit unmanaged compatibility catalog for legacy CLI tests."""
    from project_workflow.infrastructure.db import schema
    from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

    engine = get_engine(pg_url)
    ensure_migrated(engine)
    with SAUnitOfWork(engine) as uow:
        schema.ensure_phase_catalog(
            uow,
            seed_path=config_module.LEGACY_UNMANAGED_SEED_PATH,
        )
        bootstrap_default_project(uow)
        uow.commit()


def _prepare_concurrent_task(pg_url: str, task_key: str) -> None:
    from project_workflow.infrastructure.db import schema
    from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

    engine = get_engine(pg_url)
    ensure_migrated(engine)
    uow = SAUnitOfWork(engine)
    schema.ensure_phase_catalog(uow)
    bootstrap_default_project(uow)
    project = uow.projects.get_by_code("RUN")
    phase = uow.phases.list(workflow_id=project.workflow_id)[0]
    uow.tasks.create(
        {
            "project_id": project.id,
            "workflow_id": project.workflow_id,
            "task_key": task_key,
            "current_phase_id": phase.id,
        }
    )
    uow.commit()
    uow.close()


@pytest.mark.integration
@pytest.mark.parametrize("same_report", [True, False])
def test_concurrent_reports_create_one_transition_and_run(pg_url, same_report):
    from project_workflow.supervisor import SupervisorEngine

    task_key = "RUN-90005"
    _prepare_concurrent_task(pg_url, task_key)
    barrier = Barrier(2)

    def evaluate(report: str):
        uow = SAUnitOfWork(pg_url)
        engine = SupervisorEngine(task_key, uow=uow, create_if_missing=False)
        barrier.wait()
        try:
            return engine.evaluate(report)
        finally:
            uow.close()

    reports = ["same report", "same report" if same_report else "different report"]
    with (
        patch(
            "project_workflow.supervisor.evaluate.OpenAICompatibleClient.chat",
            side_effect=lambda *_args, **kwargs: _pass_response(kwargs["user"]),
        ),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = list(pool.map(evaluate, reports))

    uow = SAUnitOfWork(pg_url)
    task = uow.tasks.get_by_key(task_key)
    runs = uow.step_history.list(task_id=task.id)
    history = uow.tasks.list_phase_events(task.id)
    uow.close()

    assert len(runs) == 1
    assert history
    assert sum(result["verdict"] == "PASS" for result in results) == (2 if same_report else 1)
    if same_report:
        assert sum(result["replayed"] is True for result in results) == 1
    else:
        assert sum(result["verdict"] == "BLOCKED" and result["retryable"] is True for result in results) == 1


@pytest.mark.integration
def test_concurrent_distinct_partial_reports_do_not_apply_stale_snapshot(pg_url):
    from project_workflow.supervisor import SupervisorEngine

    task_key = "RUN-90006"
    _prepare_concurrent_task(pg_url, task_key)
    start = Barrier(2)
    providers = Barrier(2)

    def partial_response(user_prompt: str) -> dict:
        response = _pass_response(user_prompt)
        response["verdict"] = "PARTIAL"
        response["missing"] = response.pop("covered")
        response["covered"] = []
        response["message"] = "partial"
        return response

    def provider(*_args, **kwargs):
        providers.wait(timeout=10)
        return partial_response(str(kwargs["user"]))

    def evaluate(report: str) -> dict:
        uow = SAUnitOfWork(pg_url)
        try:
            engine = SupervisorEngine(task_key, uow=uow, create_if_missing=False)
            start.wait(timeout=10)
            return engine.evaluate(report)
        finally:
            uow.close()

    with (
        patch("project_workflow.supervisor.evaluate.OpenAICompatibleClient.chat", side_effect=provider),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = list(pool.map(evaluate, ["first partial", "second partial"]))

    assert sorted(result["verdict"] for result in results) == ["BLOCKED", "PARTIAL"]
    blocked = next(result for result in results if result["verdict"] == "BLOCKED")
    assert blocked["retryable"] is True
    verify = SAUnitOfWork(pg_url)
    task = verify.tasks.get_by_key(task_key)
    assert task is not None
    assert len(verify.step_history.list(task_id=task.id)) == 1
    assert len(verify.tasks.list_phase_events(task.id)) == 1
    verify.close()


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
        timeout=60,
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
    # This test exercises the explicitly unmanaged legacy CLI/Supervisor flow.
    # Production init_db bootstraps the managed Hermes catalog instead.
    from project_workflow.infrastructure.db import schema
    from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

    engine = get_engine(env["DATABASE_URL"])
    ensure_migrated(engine)
    with SAUnitOfWork(engine) as uow:
        schema.ensure_phase_catalog(
            uow,
            seed_path=config_module.LEGACY_UNMANAGED_SEED_PATH,
        )
        bootstrap_default_project(uow)
        uow.commit()


def _step(env: dict[str, str], task_key: str, report: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    return _run_cli(env, "--json", "step", "--task", task_key, "--report", report)


@pytest.mark.integration
@pytest.mark.timeout(240)
def test_full_supervisor_runtime_through_cli_postgres_and_http(pg_url):
    expected_phases = [
        "1.INTAKE",
        "2.REQUIREMENTS",
        "3.DOR_GATE",
        "4.START",
        "5.RESEARCH",
        "6.SOLUTION",
        "7.PLAN_GATE",
        "8.IMPLEMENT",
        "9.PR",
        "10.REVIEW",
        "11.RUNTIME",
        "12.RELEASE_GATE",
        "13.DELIVERY",
        "14.CLOSE",
        "15.RETRO",
    ]
    expected_groups = {
        "5.RESEARCH": ["5.RESEARCH", "5.PREFLIGHT"],
        "6.SOLUTION": ["6.SOLUTION", "6.TEST_PLAN"],
        "10.REVIEW": ["10.REVIEW", "10.QA", "10.DATAFLOW"],
    }
    task_key = "RUN-82001"

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
            assert [project.code for project in projects] == ["RUN"]
            assert len(bootstrap_uow.phases.list(workflow_id=workflows[0].id)) == 19
        finally:
            bootstrap_uow.close()

        assignment_result, assignment = _run_cli(env, "--json", "step", "--task", task_key)
        assert assignment_result.returncode == 0
        assert assignment["prompt"]
        assignment_contract = assignment["phase_contract"]
        assert assignment_contract["phase_code"] == "1.INTAKE"
        assert assignment_contract["phase_name"] == "Приём задачи"
        assert assignment_contract["workflow_revision"] == "sdlc-business-tech-v1"
        assert assignment_contract["actor"] == "hermes"
        assert assignment_contract["skills"] == [
            "project-workflow-executor",
            "relevanter-business-operator",
        ]
        assert assignment_contract["execution_type"] == "sync"
        assert assignment_contract["delegate_agent"] == "orchestrator"
        assert assignment_contract["hermes_profile"] == "sdlc-orchestrator"
        assert assignment_contract["group_phases"] is None

        first_report = "E2E report 1 for phase 1.INTAKE"
        for index, expected_phase in enumerate(expected_phases, start=1):
            report = first_report if index == 1 else f"E2E report {index} for phase {expected_phase}"
            result, payload = _step(env, task_key, report)
            assert result.returncode == 0, result.stderr or result.stdout
            assert payload["verdict"] == "PASS"
            assert payload["phase_code"] == expected_phase
            assert payload["group_phases"] == expected_groups.get(expected_phase)

            if expected_phase == "5.RESEARCH":
                assert payload["next_phase_code"] == "6.SOLUTION"
                assert payload["next_phase_contract"]["group_phases"] == [
                    "6.SOLUTION",
                    "6.TEST_PLAN",
                ]
                assert [
                    detail["hermes_profile"]
                    for detail in payload["next_phase_contract"]["group_details"]
                ] == ["sdlc-orchestrator", "sdlc-critic"]
                assert "workflow-writing-plans" in payload["next_phase_contract"]["skills"]
                assert any(
                    "workflow-code-intelligence" in instruction
                    for instruction in payload["next_phase_contract"]["instructions"]
                )
                uow = SAUnitOfWork(pg_url)
                task = uow.tasks.get_by_key(task_key)
                assert task is not None
                phases = {phase.id: phase.code for phase in uow.phases.list(workflow_id=task.workflow_id)}
                events = [row.to_dict() for row in uow.tasks.list_phase_events(task.id)]
                event_types = {
                    phases[row["phase_id"]]: row["event_type"] for row in events
                }
                assert task.current_phase_code == "6.SOLUTION"
                assert event_types["6.SOLUTION"] == "entered"
                assert event_types.get("6.TEST_PLAN") != "completed"
                uow.close()

            if expected_phase == "6.SOLUTION":
                assert payload["next_phase_code"] == "7.PLAN_GATE"

            if expected_phase == "7.PLAN_GATE":
                assert payload["next_phase_contract"]["group_phases"] is None
                assert any(
                    "test-driven-development" in instruction
                    for instruction in payload["next_phase_contract"]["instructions"]
                )

        terminal_result, terminal = _run_cli(env, "--json", "step", "--task", task_key)
        history_result, history_payload = _run_cli(env, "--json", "history", "--task", task_key)
        assert terminal_result.returncode == history_result.returncode == 0
        assert terminal["phase_code"] == "15.RETRO"
        assert terminal["next_phase_code"] is None
        assert terminal["phase_contract"]["hermes_profile"] == "sdlc-critic"
        assert terminal["status"] == "done"
        assert history_payload["count"] == 15

        completed_request_count = len(provider_state.chat_requests)
        completed_result, completed = _step(env, task_key, "New report after workflow completion")
        assert completed_result.returncode == 0
        assert completed["verdict"] == "PASS"
        assert completed["status"] == "done"
        assert completed["next_phase_code"] is None
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
        assert "Улучшения" in human_step.stdout
        assert "UnicodeEncodeError" not in human_step.stderr

        assert provider_state.model_requests == 1
        assert len(provider_state.chat_requests) == 15
        assert provider_state.chat_phases == expected_phases
        assert all(request["model"] == "e2e-contract-model" for request in provider_state.chat_requests)
        assert all(
            request["response_format"] == {"type": "json_object"}
            for request in provider_state.chat_requests
        )

    uow = SAUnitOfWork(pg_url)
    task = uow.tasks.get_by_key(task_key)
    runs = list(uow.step_history.list(task_id=task.id, limit=100))
    phase_events = list(uow.tasks.list_phase_events(task.id))
    assert task.current_phase_code == "15.RETRO"
    assert task.status == "done"
    assert len(runs) == 15
    assert phase_events[0].event_type == "entered"
    assert phase_events[0].step_history_id is None
    completed_phase_ids = {
        event.phase_id for event in phase_events if event.event_type == "completed"
    }
    assert completed_phase_ids == {
        int(phase.id) for phase in uow.phases.list(workflow_id=task.workflow_id)
    }
    assert all(
        event.step_history_id is not None
        for event in phase_events[1:]
        if event.event_type in {"completed", "blocked", "resumed", "rolled_back"}
    )
    fingerprints = [run.replay_fingerprint for run in runs]
    assert all(fingerprints)
    assert len(set(fingerprints)) == 15
    assert all(run.evaluation_snapshot["model"] == "e2e-contract-model" for run in runs)
    assert all(run.evaluation_snapshot["endpoint_mode"] == "openai-compatible" for run in runs)
    assert all(run.evaluation_snapshot["prompt_version"] == "supervisor-evaluator-v8" for run in runs)
    assert all(run.evaluation_snapshot["contract_snapshot"]["evaluation_items"] for run in runs)
    assert all(run.evaluation_snapshot["raw_evaluator"]["verdict"] == "PASS" for run in runs)
    uow.close()


def _advance_to_phase(env: dict[str, str], task_key: str, phases: list[str]) -> None:
    for index, phase in enumerate(phases, start=1):
        result, payload = _step(env, task_key, f"Advance {index} through {phase}")
        assert result.returncode == 0
        assert payload["verdict"] == "PASS"
        assert payload["phase_code"] == phase


@pytest.mark.integration
@pytest.mark.timeout(240)
def test_cli_verdicts_replay_and_fail_closed_through_postgres_and_http(pg_url):
    with _openai_compatible_server() as (provider_url, provider_state):
        env = _cli_env(pg_url, provider_url)
        _initialize_cli_database(env)

        first_cross_result, first_cross = _step(env, "RUN-82008", "identical cross-phase report")
        second_cross_result, second_cross = _step(env, "RUN-82008", "identical cross-phase report")
        assert first_cross_result.returncode == second_cross_result.returncode == 0
        assert first_cross["phase_code"] != second_cross["phase_code"]
        assert first_cross["replayed"] is second_cross["replayed"] is False

        partial_result, partial = _step(env, "RUN-82002", "MODE=PARTIAL incomplete report")
        request_count = len(provider_state.chat_requests)
        progress_result, progress = _step(env, "RUN-82002", "MODE=PARTIAL incomplete report")
        stable_request_count = len(provider_state.chat_requests)
        replay_result, replay = _step(env, "RUN-82002", "MODE=PARTIAL incomplete report")
        assert partial_result.returncode == progress_result.returncode == replay_result.returncode == 0
        assert partial["verdict"] == progress["verdict"] == replay["verdict"] == "PARTIAL"
        assert progress["replayed"] is False
        assert stable_request_count == request_count + 1
        assert replay["replayed"] is True
        assert len(provider_state.chat_requests) == stable_request_count

        blocked_result, blocked = _step(env, "RUN-82003", "MODE=BLOCKED blocked report")
        assert blocked_result.returncode == 1
        assert blocked["verdict"] == "BLOCKED"
        assert blocked["retryable"] is False

        invalid_result, invalid = _step(env, "RUN-82004", "MODE=INVALID invalid response")
        invalid_retry_result, invalid_retry = _step(env, "RUN-82004", "MODE=INVALID invalid response")
        assert invalid_result.returncode == invalid_retry_result.returncode == 1
        assert invalid["verdict"] == invalid_retry["verdict"] == "BLOCKED"
        assert invalid["retryable"] is invalid_retry["retryable"] is True
        assert invalid["replayed"] is invalid_retry["replayed"] is False

        http_result, http_error = _step(env, "RUN-82005", "MODE=HTTP_ERROR provider error")
        assert http_result.returncode == 1
        assert http_error["verdict"] == "BLOCKED"
        assert http_error["retryable"] is True

        phases_before_rollback = [
            "1.INTAKE",
            "2.REQUIREMENTS",
            "3.DOR_GATE",
            "4.START",
            "5.RESEARCH",
            "6.SOLUTION",
            "7.PLAN_GATE",
            "8.IMPLEMENT",
            "9.PR",
        ]
        _advance_to_phase(env, "RUN-82006", phases_before_rollback)
        rollback_result, rollback = _step(
            env, "RUN-82006", "MODE=ROLLBACK return to implementation"
        )
        assert rollback_result.returncode == 0
        assert rollback["verdict"] == "ROLLBACK"
        assert rollback["rollback_phase_code"] == "8.IMPLEMENT"

        _advance_to_phase(env, "RUN-82007", phases_before_rollback)
        delegate_result, delegate = _step(env, "RUN-82007", "MODE=DELEGATE hand off review")
        assert delegate_result.returncode == 0
        assert delegate["verdict"] == "DELEGATE"

    uow = SAUnitOfWork(pg_url)
    partial_task = uow.tasks.get_by_key("RUN-82002")
    blocked_task = uow.tasks.get_by_key("RUN-82003")
    invalid_task = uow.tasks.get_by_key("RUN-82004")
    http_task = uow.tasks.get_by_key("RUN-82005")
    rollback_task = uow.tasks.get_by_key("RUN-82006")
    delegate_task = uow.tasks.get_by_key("RUN-82007")
    assert (partial_task.current_phase_code, partial_task.status) == ("1.INTAKE", "active")
    assert (blocked_task.current_phase_code, blocked_task.status) == ("1.INTAKE", "blocked")
    assert (invalid_task.current_phase_code, invalid_task.status) == ("1.INTAKE", "blocked")
    assert (http_task.current_phase_code, http_task.status) == ("1.INTAKE", "blocked")
    assert (rollback_task.current_phase_code, rollback_task.status) == ("8.IMPLEMENT", "active")
    assert (delegate_task.current_phase_code, delegate_task.status) == ("10.REVIEW", "active")
    invalid_runs = list(uow.step_history.list(task_id=invalid_task.id, limit=10))
    assert len(invalid_runs) == 2
    assert all(run.replay_fingerprint is None for run in invalid_runs)
    assert [
        item.event_type for item in uow.tasks.list_phase_events(invalid_task.id)
    ] == ["entered", "blocked", "blocked"]
    assert [item.event_type for item in uow.tasks.list_phase_events(http_task.id)] == [
        "entered",
        "blocked",
    ]
    uow.close()


@pytest.mark.integration
class TestPostgresContinuationCatalogVersioning:
    def test_concurrent_identical_rebind_reconciles_after_owner_row_lock(self, pg_url):
        from tests.test_runtime_assignment_contract import _continuation

        ensure_migrated(get_engine(pg_url))
        with SAUnitOfWork(pg_url) as uow:
            ensure_managed_catalog(uow)
            project = uow.projects.get_by_cli_command("workflow-developer")
            assigned = TaskService(uow).assign_runtime_task(
                project_id=project.id,
                task_key="DV-1001",
                mode_key="initial",
                cycle_number=0,
                operation_key="pg-concurrent-initial",
                expected_revision=0,
                expected_status="missing",
                **_runtime_binding("pg-concurrent-initial"),
            )
            bound = _bind_runtime_assignment(uow, project.id, assigned)
            history = [item.to_dict() for item in uow.tasks.list_phase_events(bound["id"])]
            project_id = project.id
        request = _continuation(bound, operation_key="pg-concurrent-continuation")
        both_missed_replay = Barrier(2)

        def resume():
            with SAUnitOfWork(pg_url) as uow:
                lookup = uow.tasks.get_assignment_by_operation_key
                initial_lookup = True

                def overlapping_lookup(operation_key):
                    nonlocal initial_lookup
                    result = lookup(operation_key)
                    if operation_key == request["operation_key"] and initial_lookup:
                        initial_lookup = False
                        assert result is None
                        both_missed_replay.wait(timeout=10)
                    return result

                uow.tasks.get_assignment_by_operation_key = overlapping_lookup
                return TaskService(uow).rebind_runtime_assignment(
                    project_id=project_id, role_key="developer", request=request
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(resume) for _ in range(2)]
            results = [future.result(timeout=30) for future in futures]
        assert results[0] == results[1]
        with SAUnitOfWork(pg_url) as uow:
            assert uow.tasks.get_by_id(bound["id"]).assignment_revision == bound["assignment_revision"] + 1
            assert [item.to_dict() for item in uow.tasks.list_phase_events(bound["id"])] == history
            previous = uow.tasks.get_assignment_by_operation_key(bound["assignment_operation_key"])
            assert previous.binding_ref == bound["binding_ref"]
            assert results[0]["binding_state"] == "unbound"

    def test_additive_0005_0006_preserve_legacy_policy_and_support_versioned_duplicates(self, pg_url):
        engine = get_engine(pg_url)
        run_alembic_command("upgrade", engine, "0004_wide_work_item_revision")
        with engine.begin() as connection:
            workflow_id = connection.execute(
                text(
                    "INSERT INTO project_workflow.workflows (key,name,is_default) "
                    "VALUES ('hermes-sdlc:developer','Developer',1) RETURNING id"
                )
            ).scalar_one()
            old_id = connection.execute(
                text(
                    "INSERT INTO project_workflow.workflow_modes "
                    "(workflow_id,key,name,mode_order,role_key,execution_scope,tech_workspace_policy) "
                    "VALUES (:workflow,'initial','Initial',1,'developer','delivery','required') RETURNING id"
                ),
                {"workflow": workflow_id},
            ).scalar_one()
        ensure_migrated(engine)
        with engine.begin() as connection:
            old = connection.execute(
                text(
                    "SELECT execution_scope,execution_scopes,catalog_version "
                    "FROM project_workflow.workflow_modes WHERE id=:id"
                ),
                {"id": old_id},
            ).one()
            assert tuple(old) == ("delivery", None, 1)
            connection.execute(
                text(
                    "INSERT INTO project_workflow.workflow_modes "
                    "(workflow_id,key,name,mode_order,role_key,execution_scope,execution_scopes,"
                    "tech_workspace_policy,catalog_version) "
                    "VALUES (:workflow,'initial','Initial',1,'developer','delivery',:scopes,'required',2)"
                ),
                {"workflow": workflow_id, "scopes": json.dumps(["delivery", "aggregate"])},
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM project_workflow.workflow_modes "
                        "WHERE workflow_id=:workflow AND key='initial'"
                    ),
                    {"workflow": workflow_id},
                ).scalar_one()
                == 2
            )
        assert schema_is_ready(engine)

    @pytest.mark.parametrize(
        "mode_key,scope", [(mode, scope) for mode in ("initial", "rework") for scope in ("delivery", "aggregate")]
    )
    def test_v2_developer_pins_mode_independently_of_scope(self, pg_url, mode_key, scope):
        ensure_migrated(get_engine(pg_url))
        with SAUnitOfWork(pg_url) as uow:
            ensure_managed_catalog(uow)
            project = uow.projects.get_by_cli_command("workflow-developer")
            key = f"version2-{mode_key}-{scope}"
            assigned = TaskService(uow).assign_runtime_task(
                project_id=project.id,
                task_key="DV-1002",
                mode_key=mode_key,
                cycle_number=0,
                operation_key=key,
                expected_revision=0,
                expected_status="missing",
                **{**_runtime_binding(key), "execution_scope": scope},
            )
            bound = _bind_runtime_assignment(uow, project.id, assigned)
            assert bound["execution_scope"] == scope and bound["mode_key"] == mode_key
            pinned = uow.workflows.get_mode(bound["mode_id"])
            assert pinned.catalog_version == 2 and set(pinned.execution_scopes) == {"delivery", "aggregate"}

    def test_v1_bound_integration_survives_v2_adoption_but_refuses_v2_step(self, pg_url):
        from tests.test_managed_catalog import _install_frozen_v1
        from tests.test_runtime_assignment_contract import _binding, _step_request

        ensure_migrated(get_engine(pg_url))
        with SAUnitOfWork(pg_url) as uow:
            _install_frozen_v1(uow)
            project = uow.projects.get_by_cli_command("workflow-developer")
            mode = uow.workflows.get_mode_by_key(project.workflow_id, "integration")
            phase = uow.phases.list(project.workflow_id, mode_id=mode.id)[0]
            task_id = uow.tasks.create(
                {
                    "project_id": project.id,
                    "workflow_id": project.workflow_id,
                    "mode_id": mode.id,
                    "task_key": "DV-LEGACY-1",
                    "current_phase_id": phase.id,
                    "status": "active",
                    "assignment_revision": 1,
                    "assignment_operation_key": "legacy-bound",
                }
            )
            payload = {**_binding(execution_scope="aggregate"), "mode_key": "integration", "cycle_number": 0}
            record = {
                **payload,
                "task_id": task_id,
                "project_id": project.id,
                "workflow_id": project.workflow_id,
                "mode_id": mode.id,
                "operation_key": "legacy-bound",
                "assignment_revision": 1,
                "payload_sha256": "a" * 64,
                "payload": payload,
                "binding_ref": "legacy-binding",
                "hermes_run_ref": "legacy-run",
                "bind_operation_key": "legacy-bind-op",
                "bind_request_sha256": "b" * 64,
            }
            uow.tasks.create_assignment(record)
            uow.commit()
            before = uow.tasks.get_assignment_by_operation_key("legacy-bound").to_dict()
            task_before = uow.tasks.get_by_id(task_id).to_dict()
            ensure_managed_catalog(uow)
            uow.commit()
            assert uow.tasks.get_assignment_by_operation_key("legacy-bound").to_dict() == before
            assert uow.tasks.get_by_id(task_id).to_dict() == task_before
            bound = {
                **task_before,
                **before,
                "task_key": "DV-LEGACY-1",
                "current_phase_code": phase.code,
                "status": "active",
            }
            with pytest.raises(ConflictError, match="RUNTIME_VERSION_INCOMPATIBLE"):
                TaskService(uow).validate_runtime_step(**_step_request(project.id, bound))
            assert uow.tasks.get_by_id(task_id).to_dict() == task_before
            assert uow.workflows.get_mode(mode.id).key == "integration"
            assert uow.workflows.get_mode_by_key(project.workflow_id, "integration") is None
