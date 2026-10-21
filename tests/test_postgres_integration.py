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
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import close_all_sessions

from project_workflow import config as config_module
from project_workflow.application.instruction_service import InstructionService
from project_workflow.application.phase import PhaseServiceApp
from project_workflow.application.phase_service import PhaseService
from project_workflow.application.project import ProjectService
from project_workflow.application.task import TaskService
from project_workflow.application.workflow import WorkflowService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db import session as health_db_session
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


@pytest.mark.integration
def test_postgres_legacy_agent_archives_preserve_seven_agents_and_nineteen_links(pg_url):
    from tests.test_initial_migration import assert_populated_legacy_agent_archive_upgrade

    assert_populated_legacy_agent_archive_upgrade(get_engine(pg_url))


@pytest.mark.integration
def test_postgres_legacy_archive_and_released_migrations_roll_back_together(pg_url, monkeypatch):
    from tests.test_initial_migration import assert_legacy_archive_migration_rollback

    assert_legacy_archive_migration_rollback(get_engine(pg_url), monkeypatch)


@pytest.mark.integration
@pytest.mark.parametrize("failure", [
    "partial", "unguarded", "view", "changed_source", "foreign_column", "missing_guard",
])
def test_postgres_legacy_archive_refuses_foreign_partial_or_changed_without_overwrite(pg_url, failure):
    from tests.test_initial_migration import assert_legacy_archive_refusal

    assert_legacy_archive_refusal(get_engine(pg_url), failure)


@pytest.mark.integration
def test_postgres_legacy_archive_guard_loss_at_head_is_not_readiness(pg_url):
    from tests.test_initial_migration import assert_legacy_archive_guard_loss_holds_at_head

    assert_legacy_archive_guard_loss_holds_at_head(get_engine(pg_url))


@pytest.mark.integration
@pytest.mark.parametrize("scenario", ["appearance", "versioned-adoption"])
def test_current_base_initial_professions_and_history_preservation_on_postgres(pg_url, scenario):
    from tests.test_profession_initial_catalog import (
        assert_theme_migration_updates_only_untouched_managed_professions,
        test_adoption_preserves_profession_edits_old_tasks_history_and_user_collections,
    )
    engine = get_engine(pg_url)
    if scenario == "appearance":
        assert_theme_migration_updates_only_untouched_managed_professions(engine)
    else:
        ensure_migrated(engine)
        test_adoption_preserves_profession_edits_old_tasks_history_and_user_collections(
            engine, "base_sdlc_catalog_v1_frozen.json", "parallel",
        )


@pytest.mark.integration
def test_current_single_task_family_preserves_legacy_rows_and_history_on_postgres(pg_url):
    from hashlib import sha256

    from project_workflow.infrastructure.db.single_task_catalog import (
        ensure_single_task_catalog,
        observe_installation,
    )
    from scripts.build_single_task_profile import render
    from tests.test_single_task_installation import test_side_by_side_preserves_every_legacy_row_and_history

    catalog_bytes, manifest_bytes = render()
    engine = get_engine(pg_url)
    ensure_migrated(engine)
    test_side_by_side_preserves_every_legacy_row_and_history(engine)
    with SAUnitOfWork(engine) as uow:
        first = observe_installation(uow)
        assert first.workflow_catalog_sha256 == sha256(catalog_bytes).hexdigest()
        assert first.instruction_manifest_sha256 == sha256(manifest_bytes).hexdigest()
        assert [first.namespaces, first.workflows, first.modes, first.phases] == [7, 7, 8, 24]
        assert len({binding.namespace_id for binding in first.bindings}) == 7
        assert len({binding.workflow_id for binding in first.bindings}) == 7
        modes = [mode for binding in first.bindings for mode in binding.modes]
        assert len({mode.mode_id for mode in modes}) == 8
        assert len({phase_id for mode in modes for phase_id in mode.phase_ids}) == 24
    with SAUnitOfWork(engine) as uow:
        assert ensure_single_task_catalog(uow) == first
        uow.commit()
    with SAUnitOfWork(engine) as uow:
        assert observe_installation(uow) == first


@pytest.fixture
def pm_postgres(pg_url, monkeypatch):
    from tests.test_pm_execution import prepare_pm

    ensure_migrated(get_engine(pg_url))
    yield from prepare_pm(monkeypatch)


@pytest.mark.integration
def test_pm_draft_postgres_concurrent_original_assignment_and_restart(pg_url, monkeypatch):
    from tests.test_pm_draft_assignment import ADAPTER, PATH, prepare_pm_draft

    ensure_migrated(get_engine(pg_url))
    fixture = prepare_pm_draft(monkeypatch)
    client, request = next(fixture)
    try:
        barrier = Barrier(2)

        def assign():
            barrier.wait(timeout=10)
            return client.post(PATH, headers=ADAPTER, json=request)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: assign(), range(2)))
        assert [r.status_code for r in results] == [200, 200]
        assert results[0].json() == results[1].json()
        result = results[0].json()["result"]
        assert result["queue_item_ref"] is None and result["task_workspace_ref"] is None
        with SAUnitOfWork() as uow:
            saved = uow.tasks.get_assignment_by_operation_key(request["assignment_operation_key"])
            assert saved.payload["pm_draft_context"]["execution_ref"] == request["execution_ref"]
            before = saved.to_dict()
        reset_engine()
        with TestClient(create_app()) as restarted:
            assert restarted.post(PATH, headers=ADAPTER, json=request).json() == results[0].json()
        with SAUnitOfWork() as uow:
            assert uow.tasks.get_assignment_by_operation_key(request["assignment_operation_key"]).to_dict() == before
    finally:
        fixture.close()


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
    observations[OLD_RUN]["checkpoint_ref"] = checkpoint["checkpoint_ref"]
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
def test_pm_postgres_pending_resume_uuid_serializes_initial_bind(pm_postgres):
    from project_workflow.infrastructure.db import models as m
    from tests.test_pm_execution import (
        ADAPTER,
        AGENT_REF,
        BASE,
        NEW_RUN,
        OLD_RUN,
        waiting_pm,
    )
    from tests.test_runtime_api import _assignment, _bind_payload

    client, _, _, resume, observations, _ = waiting_pm(pm_postgres)
    observations[OLD_RUN]["status"] = "stopped"
    assignment = client.post(
        "/internal/runtime/assign", headers=ADAPTER,
        json=_assignment("PM-2", "assign:pm:2", "project_manager"),
    ).json()["result"]
    runtime_binding = _bind_payload(assignment)
    runtime_binding["concrete_agent_ref"] = AGENT_REF
    binding_response = client.post("/internal/runtime/bind", headers=ADAPTER, json=runtime_binding)
    assert binding_response.status_code == 200, binding_response.text
    binding = binding_response.json()["result"]
    identity = {
        **pm_postgres[1], "task": "PM-2", "execution_ref": "execution:pm:2",
        "task_ref": assignment["business_task_ref"], "root_ref": assignment["root_task_ref"],
        "assignment_operation_key": assignment["assignment_operation_key"],
        "assignment_ref": assignment["assignment_ref"],
        "assignment_revision": assignment["assignment_revision"],
    }
    observations[NEW_RUN] = {
        **identity, "observation_ref": "observation:pm:2", "status": "running",
        "binding_ref": binding["binding_ref"], "hermes_run_ref": binding["hermes_run_ref"],
        "dispatch_operation_key": "pm-bind:2", "fence": 1, "session_run_id": NEW_RUN,
    }
    bind = {
        **identity, "operation_key": "pm-bind:2", "expected_version": 0,
        "binding_ref": binding["binding_ref"], "hermes_run_ref": binding["hermes_run_ref"],
        "session_run_id": NEW_RUN,
    }
    barrier = Barrier(2)

    def request(path, payload):
        barrier.wait(timeout=10)
        return client.post(BASE + path, headers=ADAPTER, json=payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        resume_future = pool.submit(request, "/resume", resume)
        bind_future = pool.submit(request, "/bind", bind)
        resume_response = resume_future.result(timeout=30)
        bind_response = bind_future.result(timeout=30)
    assert sorted([resume_response.status_code, bind_response.status_code]) == [200, 409]
    with SAUnitOfWork() as uow:
        run = uow.session.get(m.PMRun, NEW_RUN)
        reservation = uow.session.scalar(select(m.PMExecution).where(
            m.PMExecution.resume_session_run_id == NEW_RUN,
            m.PMExecution.state == "resume_pending",
        ))
        assert (run is not None) != (reservation is not None)
        if resume_response.status_code == 200:
            assert reservation is not None and reservation.execution_ref == resume["execution_ref"]
        else:
            assert run is not None and run.execution_ref == bind["execution_ref"]


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
def test_pm_ownership_catalog_lock_order_and_incomplete_schema(pg_url, winner):
    from project_workflow.application.namespace_ownership import NamespaceOwnershipService
    from project_workflow.domain.namespace_ownership import NamespaceOwnershipRequest
    from project_workflow.infrastructure.db.session import DatabaseRecreateRequired
    from project_workflow.infrastructure.namespace_auth import NamespacePrincipal

    engine = get_engine(pg_url)
    ensure_migrated(engine)
    with SAUnitOfWork(engine) as uow:
        ensure_managed_catalog(uow)
        namespace_id = uow.projects.get_by_cli_command("workflow-project_manager").id
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
    assert database_revisions(engine) == {"0016_human_project_commit_guard"}


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
def test_namespace_defaults_upgrade_preserves_catalog_on_postgres(pg_url, tmp_path):
    from tests.test_namespace_default_migration import assert_upgrade_preserves_catalog

    assert_upgrade_preserves_catalog(get_engine(pg_url), tmp_path)


@pytest.mark.integration
class TestPostgresSingleTaskProfile:
    """Real PG transactions/constraints; synthetic evaluator and runtime authority, not live agents."""

    @pytest.fixture
    def profile_client(self, pg_url, monkeypatch):
        from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog

        engine = get_engine(pg_url)
        assert engine.dialect.name == "postgresql"
        ensure_migrated(engine)
        monkeypatch.setattr(config_module, "CATALOG_VARIANT", "single-task-v1")
        monkeypatch.setenv("PROJECT_WORKFLOW_PM_SCOPE_SECRET", "s" * 40)
        monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_TOKEN", "p" * 40)
        monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_URL", "http://runtime.test/readback")
        config_module.get_settings.cache_clear()
        with SAUnitOfWork() as uow:
            assert uow.session.get_bind() is engine
            ensure_single_task_catalog(uow)
        with TestClient(create_app()) as client:
            yield client

    def test_pm_initial_dispatch_persists_binding_run_and_omitted_input_revision(self, profile_client, monkeypatch):
        from project_workflow.domain.pm_execution import RuntimeObservation
        from project_workflow.infrastructure import pm_readback
        from project_workflow.infrastructure.db import models as m
        from tests.test_single_task_pm_producer import exchange, provision
        from tests.test_single_task_runtime import API, PM, RUNNER, WRITER

        source = json.loads((REPO_ROOT / "tests/fixtures/single_task_pm_initial_dispatch.json").read_text("utf-8"))
        assignment = source["assign"]["request"]
        binding = source["bind"]["request"]
        command = source["pm_bind"]["request"]
        monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"project_manager": "w" * 40}))
        monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"project_manager": "r" * 40}))
        config_module.get_settings.cache_clear()

        def no_model(*_args, **_kwargs):
            pytest.fail("PM initial instruction read must not evaluate a report")

        monkeypatch.setattr(OpenAICompatibleClient, "chat", no_model)
        _, accepted = exchange(profile_client, API + "assign", assignment, WRITER)
        _, bound = exchange(profile_client, API + "bind", binding, WRITER)
        assert accepted["result"]["exact_input_refs"] == assignment["exact_input_refs"]
        assert set(accepted["result"]["exact_input_refs"][0]) == {"kind", "ref", "hash"}
        step = {**source["first_step"]["request"],
                "single_task_context_sha256": bound["result"]["single_task_context_sha256"]}
        general_headers = {**RUNNER, "X-Workflow-Execution-Token": bound["execution_token"]}
        assert profile_client.post(API + "step", json=step, headers=general_headers).status_code == 409
        provision(assignment)
        probes = []

        def synthetic_readback(run):
            probes.append(run)
            assert run == binding["session_run_id"]
            return RuntimeObservation.model_validate(source["runtime_observation"])

        monkeypatch.setattr(pm_readback, "observe_run", synthetic_readback)
        _, enrolled = exchange(profile_client, PM + "bind", command, WRITER)
        assert probes == [binding["session_run_id"]]
        assert enrolled["execution_token"] != bound["execution_token"]
        assert enrolled["result"]["single_task_context_sha256"] != step["single_task_context_sha256"]
        step["single_task_context_sha256"] = enrolled["result"]["single_task_context_sha256"]
        headers = {**RUNNER, "X-Workflow-Execution-Token": enrolled["execution_token"]}
        assert profile_client.post(API + "step", json=step, headers=general_headers).status_code == 403
        _, first = exchange(profile_client, API + "step", step, headers)
        assert first["result"]["phase_code"] == "PM-DRAFT-01"
        assert "complete" not in first["result"] and "workflow_receipt" not in first["result"]
        readback = profile_client.post(PM + "readback", json=source["pm_readback"]["request"], headers=WRITER)
        assert readback.status_code == 200, readback.text
        assert readback.json()["result"]["operation"]["result"] == enrolled["result"]
        with SAUnitOfWork() as uow:
            task = uow.tasks.get_by_key(assignment["task"])
            records = uow.tasks.list_assignments(task.id)
            assert len(records) == 1 and task.status == "active" and task.current_phase_code == "PM-DRAFT-01"
            saved = records[0]
            assert saved.exact_input_refs == saved.payload["exact_input_refs"] == assignment["exact_input_refs"]
            assert saved.business_task_ref == saved.root_task_ref == assignment["business_task_ref"]
            assert saved.decomposition_revision_ref is saved.queue_item_ref is saved.task_workspace_ref is None
            assert saved.single_task_binding["request"]["session_run_id"] == binding["session_run_id"]
            assert len(uow.session.scalars(select(m.PMNamespaceOwnership)).all()) == 1
            assert len(uow.session.scalars(select(m.PMExecution)).all()) == 1
            assert len(uow.session.scalars(select(m.PMRun)).all()) == 1
            assert len(uow.session.scalars(select(m.PMOperation)).all()) == 1
            assert not uow.step_history.list(task_id=task.id)
            before = saved.to_dict()
        # Exercise the actual 0015 CHECK branch, not request validators or a SQLite substitute.
        for mutation in ({"root_task_ref": "99999999-9999-4999-8999-999999999999"},
                         {"decomposition_revision_ref": "forbidden:decomposition"},
                         {"single_task_binding_json": None}):
            with pytest.raises(IntegrityError) as rejected, SAUnitOfWork() as uow:
                uow.session.execute(m.TaskRuntimeAssignment.__table__.update().where(
                    m.TaskRuntimeAssignment.operation_key == assignment["operation_key"]).values(**mutation))
            assert rejected.value.orig.diag.constraint_name == "ck_task_runtime_assignments_binding_complete"
        with SAUnitOfWork() as uow:
            assert uow.tasks.get_assignment_by_operation_key(assignment["operation_key"]).to_dict() == before

    def test_pm_pre_document_feedback_checkpoint_preserves_execution_and_null_requirements(
        self, profile_client, monkeypatch,
    ):
        from project_workflow.infrastructure.db import models as m
        from tests.test_single_task_runtime import (
            PM,
            PROFILE,
            SESSION,
            WRITER,
            test_pm_brainstorming_checkpoints_and_resumes_feedback_before_any_requirements,
        )

        def no_model(*_args, **_kwargs):
            pytest.fail("Pre-document brainstorming checkpoint/resume must not evaluate a report")

        monkeypatch.setattr(OpenAICompatibleClient, "chat", no_model)
        # Reuse the parent endpoint case with synthetic readback, including invalid-pair/input rejection and replay.
        test_pm_brainstorming_checkpoints_and_resumes_feedback_before_any_requirements(profile_client, monkeypatch)
        with SAUnitOfWork() as uow:
            task = uow.tasks.get_by_key("RUN-7")
            assignments = uow.tasks.list_assignments(task.id)
            executions = uow.session.scalars(select(m.PMExecution)).all()
            assert len(assignments) == len(executions) == 1
            execution = executions[0]
            identity = json.loads(execution.identity_json)
            assert execution.execution_ref == assignments[0].payload["single_task_context"]["execution_ref"]
            assert execution.state == "resume_pending" and execution.version == 3 and execution.fence == 2
            assert task.status == "active" and task.current_phase_code == "PM-DRAFT-01" and task.cycle_number == 0
            assert not uow.step_history.list(task_id=task.id)
            checkpoint = json.loads(execution.checkpoint_json)
            assert checkpoint["requirements_revision"] is checkpoint["requirements_sha256"] is None
            assert checkpoint["clarification_request_ref"] is checkpoint["clarification_version"] is None
            assert checkpoint["resume_input"]["input"]["input_kind"] == "feedback"
            assert set(checkpoint["resume_input"]) == {"input", "input_receipt"}
            operations = uow.session.scalars(select(m.PMOperation)).all()
            assert len(operations) == 3
            assert {operation.kind for operation in operations} == {"bind", "checkpoint", "resume"}
            for operation in operations:
                if operation.kind != "bind":
                    accepted = json.loads(operation.result_json)
                    assert accepted["checkpoint"]["requirements_revision"] is None
                    assert accepted["checkpoint"]["requirements_sha256"] is None
            runs = uow.session.scalars(select(m.PMRun)).all()
            assert len(runs) == 1 and runs[0].session_run_id == execution.session_run_id == SESSION
            assert json.loads(runs[0].terminal_json)["status"] == "stopped"
            assert execution.resume_session_run_id != SESSION
            assert uow.session.get(m.PMRun, execution.resume_session_run_id) is None
        readback = profile_client.post(PM + "readback", headers=WRITER,
                                      json={**PROFILE, **identity, "operation_key": "brainstorm:resume"})
        assert readback.status_code == 200, readback.text
        result = readback.json()["result"]
        assert result["state"] == "resume_pending" and result["workflow_step_allowed"] is False
        assert result["resume_input"] == checkpoint["resume_input"]
        assert result["operation"]["result"]["resume_input"] == checkpoint["resume_input"]
        assert result["checkpoint"]["requirements_revision"] is result["checkpoint"]["requirements_sha256"] is None

    def test_non_pm_terminal_completion_replay_and_committed_history(self, profile_client, monkeypatch, supervisor_llm):
        from project_workflow.infrastructure.db import models as m
        from tests.test_single_task_terminal import test_actual_completion_artifact_matches_readback_replay_and_restart

        # The shared evaluator fixture is synthetic PASS; all ledgers/receipt seals commit in PostgreSQL.
        test_actual_completion_artifact_matches_readback_replay_and_restart(profile_client, monkeypatch, supervisor_llm)
        with SAUnitOfWork() as uow:
            assignment = uow.tasks.get_assignment_by_operation_key("assignment-7")
            task = uow.tasks.get_by_id(assignment.task_id)
            history = uow.step_history.list(task_id=task.id)
            assert task.status == "done" and len(history) == 3
            assert len(uow.tasks.list_assignments(task.id)) == 1
            terminal = uow.step_history.get_by_step_operation_key("terminal:final")
            assert terminal.supervisor_response["workflow_receipt"]
            events = uow.tasks.list_phase_events(task.id)
            assert len([event for event in events if event.step_history_id == terminal.id
                        and event.event_type == "completed"]) == 1
            before = assignment.to_dict()
        with pytest.raises(IntegrityError) as rejected, SAUnitOfWork() as uow:
            uow.session.execute(m.TaskRuntimeAssignment.__table__.update().where(
                m.TaskRuntimeAssignment.operation_key == "assignment-7").values(
                    tech_execution_workspace_ref="99999999-9999-4999-8999-999999999999"))
        assert rejected.value.orig.diag.constraint_name == "ck_task_runtime_assignments_scope_tech_refs"
        with SAUnitOfWork() as uow:
            assert uow.tasks.get_assignment_by_operation_key("assignment-7").to_dict() == before

    def test_non_pm_terminal_seal_failure_rolls_back_completion(self, profile_client, monkeypatch, supervisor_llm):
        from tests.test_single_task_terminal import test_receipt_and_actual_completion_commit_atomically

        test_receipt_and_actual_completion_commit_atomically(profile_client, monkeypatch, supervisor_llm, "seal")

    @pytest.mark.parametrize("mutation", ["body", "report", "assignment", "unsealed"])
    def test_non_pm_terminal_tamper_or_stale_replay_denied(
        self, profile_client, monkeypatch, supervisor_llm, mutation,
    ):
        from tests.test_single_task_terminal import (
            test_receipt_readback_and_exact_replay_reject_mismatch_or_stale_state,
        )

        test_receipt_readback_and_exact_replay_reject_mismatch_or_stale_state(
            profile_client, monkeypatch, supervisor_llm, mutation,
        )
        # Rejected readback/replay must not add another completion history record.
        with SAUnitOfWork() as uow:
            history = uow.step_history.get_by_step_operation_key("terminal:final")
            assert len(uow.step_history.list(task_id=history.task_id)) == 3
            if mutation == "unsealed":
                assert "workflow_receipt" not in history.supervisor_response
                assert "single_task_terminal_receipt" not in history.supervisor_response

    def test_old_non_pm_terminal_history_has_no_retroactive_receipt(self, profile_client, monkeypatch, supervisor_llm):
        from tests.test_single_task_terminal import test_old_terminal_record_is_not_retroactively_sealed

        test_old_terminal_record_is_not_retroactively_sealed(profile_client, monkeypatch, supervisor_llm)


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
        assert version == migration_head() == "0016_human_project_commit_guard"
        assert schema_is_ready(engine) is True

    def test_managed_bootstrap_serializes_with_public_catalog_creation(self, pg_url):
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

        def create_user_workflow() -> str:
            assert bootstrap_locked.wait(timeout=10)
            mutation_started.set()
            with SAUnitOfWork(engine) as uow:
                WorkflowService(uow).create_workflow({"name": "User workflow"})
            return "saved"

        with ThreadPoolExecutor(max_workers=2) as pool:
            bootstrap_future = pool.submit(bootstrap)
            mutation_future = pool.submit(create_user_workflow)
            bootstrap_future.result(timeout=30)
            mutation_result = mutation_future.result(timeout=30)

        assert mutation_result == "saved"
        with SAUnitOfWork(engine) as uow:
            assert len(uow.workflows.list()) == 8
            assert any(workflow.name == "User workflow" for workflow in uow.workflows.list())
            assert uow.projects.get_by_cli_command("workflow-project_manager") is not None

    def test_installed_instruction_edit_survives_migration_restart(self, pg_url, monkeypatch):
        from scripts import init_db

        ensure_migrated(get_engine(pg_url))
        with SAUnitOfWork(pg_url) as uow:
            ensure_managed_catalog(uow)
            workflow = next(item for item in uow.workflows.list() if item.key == "hermes-sdlc:architect")
            mode = uow.workflows.list_modes(workflow.id)[0]
            phase = uow.phases.list(workflow.id, mode_id=mode.id)[0]
            instruction = uow.phase_instructions.list(phase.id)[0]
            instruction_id = instruction["id"]
            InstructionService(uow).update_instruction(instruction_id, {"description": "Saved on PostgreSQL"})

        monkeypatch.setenv("DATABASE_URL", pg_url)
        config_module.get_settings.cache_clear()
        assert init_db.main() == 0
        with SAUnitOfWork(pg_url) as readback:
            assert readback.phase_instructions.get_by_id(instruction_id)["description"] == "Saved on PostgreSQL"

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
            return "initialized"

        with ThreadPoolExecutor(max_workers=2) as pool:
            mutation_future = pool.submit(mutate)
            bootstrap_future = pool.submit(bootstrap)
            try:
                assert bootstrap_started.wait(timeout=10)
                assert not bootstrap_finished.wait(timeout=0.2)
            finally:
                release_mutation.set()
            assert mutation_future.result(timeout=20) == "committed"
            assert bootstrap_future.result(timeout=20) == "initialized"

        with SAUnitOfWork(engine) as uow:
            workflows = list(uow.workflows.list())
            assert len(workflows) == 8
            assert any(workflow.name == "Existing unmanaged workflow" for workflow in workflows)
            assert validate_managed_catalog_state(uow) is True

    @pytest.mark.parametrize("revision,message", [
        ("0003_runtime_assignment_bind", "Downgrade from runtime assignment bind"),
        ("0004_wide_work_item_revision", "Downgrade from wide Business revisions"),
        ("0008_pm_execution", "PM execution downgrade refused"),
        ("0009_pm_draft_assignment", "PM Draft assignment downgrade refused"),
        ("0016_human_project_commit_guard", "Human policy requires a compatible guarded rollback cohort"),
    ])
    def test_downgrade_refuses_lossy_mode_collapse(self, pg_url, revision, message):
        engine = get_engine(pg_url)
        run_alembic_command("upgrade", engine, revision)
        with pytest.raises(RuntimeError, match=message):
            run_alembic_command("downgrade", engine, "base")
        assert database_revisions(engine) == {revision}
        assert schema_is_ready(engine) is (revision == "0016_human_project_commit_guard")

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
                for table in ("workflows", "projects", "phases")
            }
        assert counts == {"workflows": 7, "projects": 7, "phases": 33}

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
            {**json.loads(row), "concrete_agent_ref": None, "single_task_binding_json": None} for row in before
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
        uow.session.execute(text("CREATE INDEX projects_desc_test_idx ON projects (id DESC)"))
        uow.commit()
        uow.session.execute(text("CLUSTER phase_checks USING checks_desc_test_idx"))
        uow.session.execute(text("CLUSTER phase_evidence_requirements USING evidence_desc_test_idx"))
        uow.session.execute(text("CLUSTER task_phase_events USING phase_events_desc_test_idx"))
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
        projects = list(uow.projects.list())

        assert [row["id"] for row in phase_checks] == sorted(row["id"] for row in phase_checks)
        assert [row["id"] for row in phase_evidence] == sorted(row["id"] for row in phase_evidence)
        assert [row["id"] for row in checks] == sorted(row["id"] for row in checks)
        assert [row["id"] for row in evidence] == sorted(row["id"] for row in evidence)
        assert [row.id for row in history] == sorted(row.id for row in history)
        assert [row.id for row in batch_history] == sorted(row.id for row in batch_history)
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
        profession = uow.projects.get_by_code("RUN")
        uow.projects.update(profession.id, {"launch_profile": "run-developer"})
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
        assert assignment_contract["delegate_agent"] == "RUN"
        assert assignment_contract["hermes_profile"] == "run-developer"
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
                ] == ["run-developer", "run-developer"]
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
        assert terminal["phase_contract"]["hermes_profile"] == "run-developer"
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


@pytest.mark.integration
class TestPostgresPMBootstrap:
    """Real namespace/task locks; synthetic Fleet HTTP permits, never live authority."""

    @pytest.fixture
    def bootstrap_pg(self, pg_url, monkeypatch, request):
        from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog
        from tests.test_pm_bootstrap_http import fleet_server
        from tests.test_pm_bootstrap_retry import prepare_pending

        engine = get_engine(pg_url)
        assert engine.dialect.name == "postgresql"
        ensure_migrated(engine)
        monkeypatch.setattr(config_module, "CATALOG_VARIANT", "single-task-v1")
        monkeypatch.setenv("PROJECT_WORKFLOW_PM_SCOPE_SECRET", "s" * 40)
        monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_TOKEN", "p" * 40)
        config_module.get_settings.cache_clear()
        with SAUnitOfWork() as uow:
            assert uow.session.get_bind() is engine
            ensure_single_task_catalog(uow)
        with TestClient(create_app()) as client:
            pending = prepare_pending(client, monkeypatch, getattr(request, "param", "bound"))
            with fleet_server(pending, monkeypatch) as fleet:
                yield pending, fleet

    @pytest.mark.parametrize("bootstrap_pg", ["bound", "unbound"], indirect=True)
    def test_registered_retry_preserves_predecessor_and_fences_late_bind(self, bootstrap_pg, supervisor_llm):
        from project_workflow.infrastructure.db import models as m
        from tests.test_pm_bootstrap_http import PREDECESSOR, RETRY
        from tests.test_pm_bootstrap_retry import NEXT, command, finish_confirmed_retry
        from tests.test_single_task_runtime import API, PM, PROFILE, RUNNER, WRITER

        pending, fleet = bootstrap_pg
        request = command(pending)
        with SAUnitOfWork() as uow:
            before = uow.tasks.get_assignment_by_operation_key(request.predecessor_operation_key).to_dict()
        reader = pending["client"].get(PREDECESSOR, params={
            "task": pending["assignment"]["task"], "assignment_operation_key": request.predecessor_operation_key,
            "assignment_revision": 1,
        }, headers=WRITER)
        assert reader.status_code == 200 and reader.json()["result"] == pending["state"]
        accepted = pending["client"].post(RETRY, json=request.model_dump(), headers=WRITER)
        assert accepted.status_code == 200, accepted.text
        result = accepted.json()["result"]
        assert result["assignment_revision"] == result["attempt_number"] == 2
        assert result["binding_state"] == "unbound" and result["status"] == "active"
        assert "execution_token" not in accepted.json()
        native = pending["proof"].native
        fleet["runs"][native.session_run_id]["status"] = "running"
        late = {**PROFILE, **native.model_dump(include={
            "task", "execution_ref", "tracker_instance_ref", "tracker_project_ref", "task_ref", "root_ref",
            "agent_ref", "assignment_operation_key", "assignment_ref", "assignment_revision",
            "binding_ref", "hermes_run_ref", "session_run_id",
        }), "operation_key": native.dispatch_operation_key, "expected_version": 0}
        assert pending["client"].post(PM + "bind", json=late, headers=WRITER).status_code == 409
        assert pending["client"].post(API + "bind", json=pending["binding"], headers=WRITER).status_code == 409
        count = len(fleet["paths"])
        fleet["proofs"].clear()
        replay = pending["client"].post(RETRY, json=request.model_dump(), headers=WRITER)
        assert replay.status_code == 200 and len(fleet["paths"]) == count
        with SAUnitOfWork() as uow:
            assert uow.tasks.get_assignment_by_operation_key(request.predecessor_operation_key).to_dict() == before
            assert len(uow.tasks.list_assignments(pending["state"]["task_id"])) == 2
            assert list(uow.session.scalars(select(m.PMExecution))) == []
            assert list(uow.session.scalars(select(m.PMRun))) == []
            assert uow.step_history.list(task_id=pending["state"]["task_id"]) == []

        # Normal explicit enrollment/steps after retry: native and PM identity
        # keep canonicalRoot; only the generic bind/step sink uses the child.
        binding = {**pending["binding"], "assignment_operation_key": request.operation_key,
                   "assignment_revision": 2, "attempt_number": 2, "bind_operation_key": "bind:retry",
                   "binding_ref": "binding:retry", "hermes_run_ref": "run:retry", "session_run_id": NEXT}
        client = pending["client"]
        bound = client.post(API + "bind", json=binding, headers=WRITER)
        assert bound.status_code == 200, bound.text
        identity = native.model_dump(include={
            "task", "execution_ref", "tracker_instance_ref", "tracker_project_ref", "task_ref", "root_ref",
            "agent_ref", "assignment_operation_key", "assignment_ref", "assignment_revision",
        })
        assert identity["assignment_operation_key"] == request.predecessor_operation_key
        pm_command = {**PROFILE, **identity, "operation_key": "pm:retry-bind", "expected_version": 0,
                      "binding_ref": "binding:retry", "hermes_run_ref": "run:retry", "session_run_id": NEXT}
        current_native = native.model_copy(update={
            "status": "running", "binding_ref": "binding:retry", "hermes_run_ref": "run:retry",
            "session_run_id": NEXT, "dispatch_operation_key": "pm:retry-bind",
        })
        fleet["runs"][NEXT] = current_native
        enrolled = client.post(PM + "bind", json=pm_command, headers=WRITER)
        assert enrolled.status_code == 200, enrolled.text
        read = client.post(PM + "readback", json={**PROFILE, **identity}, headers=WRITER)
        assert read.status_code == 200 and read.json()["result"]["identity"] == identity
        step = {**pending["step"], "assignment_revision": 2, "attempt_number": 2,
                "step_operation_key": "step:retry-read", "binding_ref": "binding:retry",
                "hermes_run_ref": "run:retry", "session_run_id": NEXT,
                "single_task_context_sha256": enrolled.json()["result"]["single_task_context_sha256"]}
        headers = {**RUNNER, "X-Workflow-Execution-Token": enrolled.json()["execution_token"]}
        first = client.post(API + "step", json=step, headers=headers)
        assert first.status_code == 200 and first.json()["result"]["phase_code"] == "PM-DRAFT-01"
        finish_confirmed_retry(
            pending, supervisor_llm, identity, current_native, pm_command, step, headers, fleet["runs"],
        )
        with SAUnitOfWork() as uow:
            assert uow.tasks.get_assignment_by_operation_key(request.predecessor_operation_key).to_dict() == before

    @pytest.mark.parametrize("bootstrap_pg", ["bound", "unbound"], indirect=True)
    def test_concurrent_successors_have_one_locked_publication(self, bootstrap_pg):
        from project_workflow.domain.runtime_assignment import payload_sha256
        from tests.test_pm_bootstrap_http import RETRY
        from tests.test_pm_bootstrap_retry import command
        from tests.test_single_task_pm_terminal import CURRENT_RUN
        from tests.test_single_task_runtime import WRITER

        pending, fleet = bootstrap_pg
        second = pending["proof"].model_copy(update={"bootstrap_attempt_ref": CURRENT_RUN})
        fleet["proofs"][CURRENT_RUN] = second.model_dump(mode="json")
        requests = [command(pending), command(
            pending, operation_key="pm-bootstrap:competitor", bootstrap_attempt_ref=CURRENT_RUN,
            proof_sha256=payload_sha256(second.model_dump()),
        )]
        fleet["barrier"] = Barrier(2)

        def send(request):
            return pending["client"].post(RETRY, json=request.model_dump(), headers=WRITER)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, requests))
        assert sorted(result.status_code for result in results) == [200, 409]
        with SAUnitOfWork() as uow:
            records = uow.tasks.list_assignments(pending["state"]["task_id"])
            assert len(records) == 2
            task = uow.tasks.get_by_id(pending["state"]["task_id"])
            assert task.assignment_revision == 2 and task.status == "active"
            winner = next(result.json()["result"] for result in results if result.status_code == 200)
            assert task.assignment_operation_key == winner["assignment_operation_key"]

    def test_enrollment_during_composite_http_read_prevents_successor(self, bootstrap_pg):
        from project_workflow.infrastructure.db import models as m
        from tests.test_pm_bootstrap_http import RETRY
        from tests.test_pm_bootstrap_retry import command
        from tests.test_single_task_runtime import PM, PROFILE, WRITER

        pending, fleet = bootstrap_pg
        fleet["release"].clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(pending["client"].post, RETRY, json=command(pending).model_dump(), headers=WRITER)
            try:
                assert fleet["entered"].wait(timeout=5)
                native = pending["proof"].native
                fleet["runs"][native.session_run_id]["status"] = "running"
                body = {**PROFILE, **native.model_dump(include={
                    "task", "execution_ref", "tracker_instance_ref", "tracker_project_ref", "task_ref", "root_ref",
                    "agent_ref", "assignment_operation_key", "assignment_ref", "assignment_revision",
                    "binding_ref", "hermes_run_ref", "session_run_id",
                }), "operation_key": native.dispatch_operation_key, "expected_version": 0}
                enrolled = pending["client"].post(PM + "bind", json=body, headers=WRITER)
                assert enrolled.status_code == 200, enrolled.text
                fleet["runs"][native.session_run_id]["status"] = native.status
            finally:
                fleet["release"].set()
            rejected = future.result(timeout=15)
        assert rejected.status_code == 409, rejected.text
        with SAUnitOfWork() as uow:
            assert len(uow.tasks.list_assignments(pending["state"]["task_id"])) == 1
            assert len(list(uow.session.scalars(select(m.PMExecution)))) == 1
            assert len(list(uow.session.scalars(select(m.PMRun)))) == 1

    def test_predecessor_lock_timeout_is_unknown_not_absent(self, bootstrap_pg):
        from project_workflow.application.pm_bootstrap import PMBootstrapService
        from tests.test_pm_bootstrap_http import PREDECESSOR
        from tests.test_single_task_runtime import WRITER

        pending, fleet = bootstrap_pg
        query = {"task": pending["assignment"]["task"],
                 "assignment_operation_key": pending["assignment"]["operation_key"], "assignment_revision": 1}
        with SAUnitOfWork() as owner:
            PMBootstrapService(owner)._locked(pending["project"], query["task"], query["assignment_operation_key"])
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(pending["client"].get, PREDECESSOR, params=query, headers=WRITER)
                response = future.result(timeout=8)
            assert response.status_code == 503 and "result" not in response.json()
            assert response.headers["Cache-Control"] == "no-store"
        assert pending["client"].get(PREDECESSOR, params=query, headers=WRITER).status_code == 200
        assert fleet["paths"] == []


def _health_probe_client(pg_url):
    engine = health_db_session.get_engine(pg_url)
    health_db_session.ensure_migrated(engine)
    return engine, TestClient(create_app())


@pytest.mark.integration
def test_postgres_warm_health_reuses_exact_validation_with_bounded_queries(pg_url):
    engine, client = _health_probe_client(pg_url)
    with patch.object(health_db_session, "schema_is_ready", wraps=health_db_session.schema_is_ready) as deep:
        assert client.get("/health").status_code == 200
        queries = []

        def record(_conn, _cursor, statement, _parameters, _context, _many):
            queries.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            for _ in range(3):
                assert client.get("/health").status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert deep.call_count == 1
        assert len(queries) <= 18


@pytest.mark.parametrize("change", [
    "ALTER TABLE projects ADD COLUMN unexpected_health_column TEXT",
    "ALTER TABLE projects ALTER COLUMN name TYPE text",
    "ALTER TABLE projects ALTER COLUMN name SET DEFAULT 'unexpected-default'",
    "CREATE INDEX health_extra_index ON projects(name)",
    "CREATE TABLE unexpected_health_table(id integer)",
    "CREATE FUNCTION legacy_metadata_readonly() RETURNS trigger LANGUAGE plpgsql "
    "AS $$BEGIN RETURN NEW; END;$$",
    "UPDATE alembic_version SET version_num='unknown_health_revision'",
])
@pytest.mark.integration
def test_postgres_health_rejects_ddl_or_revision_drift_without_ttl(pg_url, change):
    engine, client = _health_probe_client(pg_url)
    assert client.get("/health").status_code == 200
    with engine.begin() as connection:
        connection.execute(text(change))
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["error_code"] == "schema-not-ready"


@pytest.mark.integration
def test_postgres_health_recovers_after_ddl_repair(pg_url):
    engine, client = _health_probe_client(pg_url)
    assert client.get("/health").status_code == 200
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE unexpected_health_table(id integer)"))
    assert client.get("/health").status_code == 503
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE unexpected_health_table"))
    assert client.get("/health").status_code == 200


@pytest.mark.integration
def test_postgres_health_neighbor_namespace_and_same_revision_dml_do_not_repeat_validation(pg_url):
    engine, client = _health_probe_client(pg_url)
    with patch.object(health_db_session, "schema_is_ready", wraps=health_db_session.schema_is_ready) as deep:
        assert client.get("/health").status_code == 200
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num=version_num"))
            connection.execute(text('CREATE SCHEMA "Health_Neighbor"'))
            connection.execute(text('CREATE TABLE "Health_Neighbor".extra(id integer)'))
        assert client.get("/health").status_code == 200
        assert deep.call_count == 1
