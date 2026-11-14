"""The registered Start cutover appends defaults, never adopts saved work."""

from copy import deepcopy

import pytest
import sqlalchemy as sa

from project_workflow.application import catalog_publication as editor
from project_workflow.domain.catalog_publication import CatalogDraft, CatalogPublish
from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.session import (
    database_revisions,
    get_engine,
    migration_head,
    run_alembic_command,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._historical_catalog import historical_publication_writer
from tests._report_helpers import report_json
from tests.test_postgres_integration import pg_url as pg_url

PREVIOUS = "2f16635c0f588d1f285393b4ad8c163119b4dba4b9918335c821f295e88a4f64"
PREVIOUS_REVISION = "0030_analyst_baseline_ledger"
TARGET_REVISION = "0031_explicit_stage_start"
TARGET_MANIFEST = "852e0647ad8645c9c6280b21c1595b9efa6ff87754d07df8dcc92bcb04f76381"
# These historical cutover invariants stop at0031; current source-default migration
# has its own preservation/failure tests and must not change this frozen target.


def snapshot(engine):
    metadata = sa.MetaData()
    metadata.reflect(bind=engine)
    with engine.connect() as connection:
        return {table.name: connection.execute(sa.select(table).order_by(*table.primary_key.columns)).mappings().all()
                for table in metadata.sorted_tables}


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.integration)])
def database(tmp_path, request):
    engine = (sa.create_engine(f"sqlite:///{tmp_path / 'cutover.db'}") if request.param == "sqlite"
              else get_engine(request.getfixturevalue("pg_url")))
    yield engine
    engine.dispose()


@pytest.fixture
def predecessor(database, monkeypatch):
    engine = database
    run_alembic_command("upgrade", engine, PREVIOUS_REVISION)
    reader = catalog.load_profile
    with monkeypatch.context() as old_runtime:
        old_runtime.setattr(catalog, "load_profile", lambda digest=None: reader(digest or PREVIOUS))
        with SAUnitOfWork(engine) as uow:
            installed = catalog.ensure_single_task_catalog(uow)
    yield engine, installed


def test_fresh_installation_selects_the_current_start_contract(database):
    engine = database
    from project_workflow.infrastructure.db.session import ensure_migrated

    ensure_migrated(engine)
    with SAUnitOfWork(engine) as uow:
        installed = catalog.ensure_single_task_catalog(uow)
        assert installed.instruction_manifest_sha256 == catalog.MANIFEST_SHA256
        assert len(installed.bindings) == 7 and installed.phases == 33
        for binding in installed.bindings:
            workflow = uow.workflows.get_by_id(int(binding.workflow_id))
            active = editor.read_active(uow, workflow.id)
            assert active["catalog_version"] == 2
            assert all("Before business work, explicitly start" in
                       mode["phases"][0]["instructions"][0]["description"] for mode in active["modes"])
    assert database_revisions(engine) == {migration_head()}


@pytest.mark.parametrize("draft_role", [None, "project_manager", "analyst", "architect"])
def test_cutover_preserves_populated_history_and_pending_drafts(predecessor, draft_role, monkeypatch):
    engine, installed = predecessor
    original_draft = None
    reader = catalog.load_profile
    with monkeypatch.context() as old_runtime, historical_publication_writer(), SAUnitOfWork(engine) as uow:
        old_runtime.setattr(catalog, "load_profile", lambda digest=None: reader(digest or PREVIOUS))
        for binding in installed.bindings:
            workflow_id = int(binding.workflow_id)
            if binding.role_key == draft_role:
                active = editor.read_active(uow, workflow_id)
                modes = deepcopy(active["modes"])
                modes[0]["phases"][0]["instructions"][0]["description"] += " Original operator clarification."
                draft = editor.save_draft(uow, workflow_id, CatalogDraft(
                    expected_version=active["catalog_version"], expected_sha256=active["content_sha256"], modes=modes))
                original_draft = draft
            mode = uow.workflows.list_modes(workflow_id)[0]
            phase = uow.phases.list(workflow_id, mode_id=mode.id)[0]
            task = uow.tasks.create({
                "project_id": int(binding.namespace_id), "workflow_id": workflow_id, "mode_id": mode.id,
                "task_key": f"SAVED-{binding.role_key}", "current_phase_id": phase.id, "status": "active",
                "cycle_number": 1,
            })
            uow.record_step(task_id=task, phase_id=phase.id, mode_id=mode.id, cycle_number=1,
                            verdict="partial", worker_report=report_json("Actual saved business work"),
                            covered_item_ids=[], missing_item_ids=["original-gap"], blocker_messages=[],
                            evaluation_snapshot={"original": True}, supervisor_response={"complete": False})
    before = snapshot(engine)
    run_alembic_command("upgrade", engine, TARGET_REVISION)
    after = snapshot(engine)
    additive = {"workflow_modes", "phases", "phase_instructions", "phase_checks",
                "phase_evidence_requirements", "workflow_catalog_publications"}
    for name in before.keys() - additive - {"workflows", "alembic_version"}:
        assert after[name] == before[name], name
    for name in additive:
        assert all(row in after[name] for row in before[name]), name
    receipts_before = {(row["workflow_id"], row["catalog_version"])
                       for row in before["workflow_catalog_publications"]}
    receipts = [row for row in after["workflow_catalog_publications"]
                if (row["workflow_id"], row["catalog_version"]) not in receipts_before]
    assert len(receipts) == 7
    with SAUnitOfWork(engine) as uow:
        current = catalog.observe_installation(uow)
        assert current.instruction_manifest_sha256 == TARGET_MANIFEST
        old_workflows = {row["id"]: row for row in before["workflows"]}
        for receipt in receipts:
            old = old_workflows[receipt["workflow_id"]]
            assert receipt["parent_version"] == old["active_catalog_version"]
            assert receipt["operation_key"] == (
                f'{editor.BASELINE_OPERATION}{old["id"]}:{TARGET_MANIFEST}')
            assert receipt["published_by_subject"] is None and receipt["published_at"] is None
            workflow = uow.workflows.get_by_id(old["id"])
            assert workflow.active_catalog_version == receipt["catalog_version"]
            for mode in uow.workflows.list_modes(workflow.id):
                assert mode.id not in {row["mode_id"] for row in before["tasks"]}
            if workflow.key == f"single-task-v1:{draft_role}":
                pending = editor.read_pending_draft(uow, workflow.id)
                assert pending["active_catalog_version"] == workflow.active_catalog_version
                assert pending == {**original_draft, "active_catalog_version": workflow.active_catalog_version}
    assert len(after["phases"]) == len(before["phases"]) + 33
    assert database_revisions(engine) == {TARGET_REVISION}
    run_alembic_command("upgrade", engine, TARGET_REVISION)
    assert snapshot(engine) == after


def test_cutover_failure_rolls_back_all_seven_and_the_migration_ledger(predecessor, monkeypatch):
    engine, _ = predecessor
    before = snapshot(engine)
    publish = editor.publish_baseline
    calls = []

    def interrupted(uow, workflow, manifest):
        calls.append(workflow.key)
        result = publish(uow, workflow, manifest)
        if len(calls) == 5:
            raise RuntimeError("Controlled cutover interruption")
        return result

    # Alembic loads the registered module afresh; patch its existing imported producer.
    monkeypatch.setattr(editor, "publish_baseline", interrupted)
    with pytest.raises(RuntimeError, match="Controlled cutover interruption"):
        run_alembic_command("upgrade", engine, TARGET_REVISION)
    assert len(calls) == 5
    assert snapshot(engine) == before
    assert database_revisions(engine) == {PREVIOUS_REVISION}


@pytest.mark.parametrize("role", [
    "project_manager", "analyst", "architect", "developer", "reviewer", "tester", "devops",
])
def test_active_operator_publication_requires_explicit_cutover_before_any_write(predecessor, monkeypatch, role):
    engine, installed = predecessor
    binding = next(binding for binding in installed.bindings if binding.role_key == role)
    reader = catalog.load_profile
    with monkeypatch.context() as old_runtime, historical_publication_writer(), SAUnitOfWork(engine) as uow:
        old_runtime.setattr(catalog, "load_profile", lambda digest=None: reader(digest or PREVIOUS))
        workflow_id = int(binding.workflow_id)
        active = editor.read_active(uow, workflow_id)
        modes = deepcopy(active["modes"])
        modes[0]["phases"][0]["instructions"][0]["description"] += " Deliberate active operator instruction."
        draft = editor.save_draft(uow, workflow_id, CatalogDraft(
            expected_version=active["catalog_version"], expected_sha256=active["content_sha256"], modes=modes))
        published = editor.publish(uow, workflow_id, draft["catalog_version"], CatalogPublish(
            expected_version=active["catalog_version"], expected_sha256=active["content_sha256"],
            draft_sha256=draft["content_sha256"], operation_key="operator-before-start-cutover"),
            publisher_subject="verified-test-operator")
        assert catalog._observe_profile(uow, *reader(PREVIOUS)).instruction_manifest_sha256 == PREVIOUS
    before = snapshot(engine)
    for _ in range(2):
        with pytest.raises(ValueError, match=f"Explicit Start cutover publication required.*single-task-v1:{role}"):
            run_alembic_command("upgrade", engine, TARGET_REVISION)
        assert snapshot(engine) == before
        assert database_revisions(engine) == {PREVIOUS_REVISION}
        with SAUnitOfWork(engine) as uow:
            assert editor.read_operation(uow, workflow_id, "operator-before-start-cutover") == published
            assert editor.read_active(uow, workflow_id)["modes"] == published["modes"]


@pytest.mark.parametrize("role", [
    "project_manager", "analyst", "architect", "developer", "reviewer", "tester", "devops",
])
def test_exact_target_operator_publication_is_sealed_without_overriding_content(predecessor, monkeypatch, role):
    engine, installed = predecessor
    binding = next(binding for binding in installed.bindings if binding.role_key == role)
    workflow_id = int(binding.workflow_id)
    target = editor._definition(binding.workflow_key, TARGET_MANIFEST)
    reader = catalog.load_profile
    with monkeypatch.context() as old_runtime, historical_publication_writer(), SAUnitOfWork(engine) as uow:
        old_runtime.setattr(catalog, "load_profile", lambda digest=None: reader(digest or PREVIOUS))
        # Old jobs stay on the selected old modes even when the operator publishes
        # the reviewed Start text before the normal registered migration.
        mode = uow.workflows.list_modes(workflow_id)[0]
        phase = uow.phases.list(workflow_id, mode_id=mode.id)[0]
        task = uow.tasks.create({
            "project_id": int(binding.namespace_id), "workflow_id": workflow_id, "mode_id": mode.id,
            "task_key": "PINNED-BEFORE-EXPLICIT-CUTOVER", "current_phase_id": phase.id,
            "status": "active", "cycle_number": 1,
        })
        uow.record_step(task_id=task, phase_id=phase.id, mode_id=mode.id, cycle_number=1,
                        verdict="partial", worker_report=report_json("Saved pre-cutover business work"),
                        covered_item_ids=[], missing_item_ids=["saved-gap"], blocker_messages=[],
                        evaluation_snapshot={"original": True}, supervisor_response={"complete": False})
        active = editor.read_active(uow, workflow_id)
        draft = editor.save_draft(uow, workflow_id, CatalogDraft(
            expected_version=active["catalog_version"], expected_sha256=active["content_sha256"],
            modes=editor._normalize(target["modes"])))
        command = CatalogPublish(
            expected_version=active["catalog_version"], expected_sha256=active["content_sha256"],
            draft_sha256=draft["content_sha256"], operation_key="explicit-start-target")
        published = editor.publish(uow, workflow_id, draft["catalog_version"], command,
                                   publisher_subject="verified-test-operator")
        assert catalog._observe_profile(uow, *reader(PREVIOUS)).instruction_manifest_sha256 == PREVIOUS
    before = snapshot(engine)
    run_alembic_command("upgrade", engine, TARGET_REVISION)
    after = snapshot(engine)
    for name in ("tasks", "task_runtime_assignments", "task_step_history", "task_phase_events"):
        assert after[name] == before[name], name
    for name in ("workflow_modes", "phases", "phase_instructions", "phase_checks",
                 "phase_evidence_requirements", "workflow_catalog_publications"):
        assert all(row in after[name] for row in before[name]), name
    with SAUnitOfWork(engine) as uow:
        assert catalog.observe_installation(uow).instruction_manifest_sha256 == TARGET_MANIFEST
        selected = editor.read_active(uow, workflow_id)
        assert selected["catalog_version"] == published["catalog_version"] + 1
        assert selected["modes"] == published["modes"]
        assert selected["content_sha256"] == published["content_sha256"]
        assert editor.read_operation(uow, workflow_id, "explicit-start-target") == published
        assert editor.publish(uow, workflow_id, draft["catalog_version"], command,
                              publisher_subject="another-current-operator") == published
        assert uow.workflows.get_by_id(workflow_id).active_catalog_version == selected["catalog_version"]
    run_alembic_command("upgrade", engine, TARGET_REVISION)
    assert snapshot(engine) == after


@pytest.mark.parametrize("publication", ["operator_text", "previous_first_step"])
def test_almost_target_publication_is_not_silently_replaced(predecessor, monkeypatch, publication):
    engine, installed = predecessor
    binding = next(binding for binding in installed.bindings if binding.role_key == "project_manager")
    workflow_id = int(binding.workflow_id)
    manifest = ("e502e0e1bed9f4a16e08423a4ac1f0162e5ef6b006d9a9a7540137ac0ec5c08f"
                if publication == "previous_first_step" else TARGET_MANIFEST)
    modes = editor._normalize(editor._definition(binding.workflow_key, manifest)["modes"])
    if publication == "operator_text":
        modes[0]["phases"][-1]["instructions"][-1]["description"] += " Keep this deliberate operator text."
    reader = catalog.load_profile
    with monkeypatch.context() as old_runtime, historical_publication_writer(), SAUnitOfWork(engine) as uow:
        old_runtime.setattr(catalog, "load_profile", lambda digest=None: reader(digest or PREVIOUS))
        active = editor.read_active(uow, workflow_id)
        draft = editor.save_draft(uow, workflow_id, CatalogDraft(
            expected_version=active["catalog_version"], expected_sha256=active["content_sha256"], modes=modes))
        editor.publish(uow, workflow_id, draft["catalog_version"], CatalogPublish(
            expected_version=active["catalog_version"], expected_sha256=active["content_sha256"],
            draft_sha256=draft["content_sha256"], operation_key="target-with-operator-change"),
            publisher_subject="verified-test-operator")
    before = snapshot(engine)
    with pytest.raises(ValueError, match="Explicit Start cutover publication required"):
        run_alembic_command("upgrade", engine, TARGET_REVISION)
    assert snapshot(engine) == before
    assert database_revisions(engine) == {PREVIOUS_REVISION}


@pytest.mark.parametrize("drift", ["source", "pointer"])
def test_cutover_rejects_unaccepted_predecessor_without_partial_publication(predecessor, drift):
    engine, installed = predecessor
    with SAUnitOfWork(engine) as uow:
        binding = installed.bindings[0]
        if drift == "source":
            instruction = uow.phase_instructions.list(int(binding.modes[0].phase_ids[0]))[0]
            uow.phase_instructions.update(instruction["id"], {"description": "Unreceipted change"})
        else:
            workflow = uow.workflows.get_by_id(int(binding.workflow_id))
            uow.workflows.update(workflow.id, {"active_catalog_version": workflow.active_catalog_version + 1})
    before = snapshot(engine)
    with pytest.raises((ValueError, editor.ConflictError)):
        run_alembic_command("upgrade", engine, TARGET_REVISION)
    assert snapshot(engine) == before
    assert database_revisions(engine) == {PREVIOUS_REVISION}
