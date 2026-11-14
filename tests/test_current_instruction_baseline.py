"""Registered source cutover preserves accepted publications and pinned work."""

import importlib
from copy import deepcopy

import pytest

from project_workflow import config
from project_workflow.application import catalog_publication as editor
from project_workflow.domain.catalog_publication import CatalogDraft, CatalogPublish
from project_workflow.domain.single_task_profile import CATALOG_SHA256
from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.session import (
    database_revisions,
    ensure_migrated,
    migration_head,
    run_alembic_command,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._report_helpers import report_json
from tests.test_postgres_integration import pg_url as pg_url
from tests.test_stage_start_catalog_cutover import database as database
from tests.test_stage_start_catalog_cutover import snapshot

PREVIOUS = "852e0647ad8645c9c6280b21c1595b9efa6ff87754d07df8dcc92bcb04f76381"
PREVIOUS_REVISION = "0031_explicit_stage_start"
TARGET = "d035a0ddb06436714b76e40bc8cb68084203011f53dd52436732367690940e85"
TARGET_REVISION = "0033_background_convergence"


@pytest.fixture
def predecessor(database, monkeypatch):
    run_alembic_command("upgrade", database, PREVIOUS_REVISION)
    reader = catalog.load_profile
    with monkeypatch.context() as old_runtime:
        old_runtime.setattr(catalog, "load_profile", lambda digest=None: reader(digest or PREVIOUS))
        with SAUnitOfWork(database) as uow:
            installed = catalog.ensure_single_task_catalog(uow)
    return database, installed


def ordinary_init(engine, monkeypatch):
    from scripts import init_db

    with monkeypatch.context() as startup:
        startup.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        startup.setenv("PROJECT_WORKFLOW_MODE", "platform")
        startup.setenv("AUTH_ISSUER", "https://auth.fixture.invalid")
        startup.setenv("AUTH_INTERNAL_BASE_URL", "https://auth.fixture.invalid")
        startup.setenv("AUTH_SESSION_SECRET", "current-source-fixture-session-secret-32-characters")
        startup.setattr(init_db, "get_engine", lambda _: engine)
        config.get_settings.cache_clear()
        try:
            assert init_db.main() == 0
        finally:
            config.get_settings.cache_clear()


def test_registered_upgrade_preserves_the_frozen_cutover_target(predecessor, monkeypatch):
    engine, _ = predecessor
    assert database_revisions(engine) == {PREVIOUS_REVISION}
    ensure_migrated(engine)
    ordinary_init(engine, monkeypatch)
    with SAUnitOfWork(engine) as uow:
        current = catalog.observe_installation(uow)
        assert current.instruction_manifest_sha256 == TARGET
        assert len(current.bindings) == 7 and current.phases == 33
    assert database_revisions(engine) == {migration_head()} == {TARGET_REVISION}


@pytest.mark.parametrize("family", [
    "920379c0c86455148e6fae35e2007037595c2d1cc82116c392c575c4625ffd28",
    "230d245a4562a25a71d1d167fbfa3deea2276084447046631aade9056252df68",
])
def test_registered_upgrade_keeps_other_compatible_installations(database, monkeypatch, family):
    run_alembic_command("upgrade", database, PREVIOUS_REVISION)
    reader = catalog.load_profile
    with monkeypatch.context() as old_runtime:
        old_runtime.setattr(catalog, "load_profile", lambda digest=None: reader(digest or family))
        with SAUnitOfWork(database) as uow:
            original = catalog.ensure_single_task_catalog(uow)
    before = snapshot(database)
    ensure_migrated(database)
    assert database_revisions(database) == {TARGET_REVISION}
    assert snapshot(database) == {**before, "alembic_version": [{"version_num": TARGET_REVISION}]}
    with SAUnitOfWork(database) as uow:
        assert catalog.observe_installation(uow) == original


def test_fresh_ordinary_initialization_selects_shipping_source(database, monkeypatch):
    ordinary_init(database, monkeypatch)
    with SAUnitOfWork(database) as uow:
        installed = catalog.observe_installation(uow)
        assert installed.instruction_manifest_sha256 == catalog.MANIFEST_SHA256
        assert installed.workflow_catalog_sha256 == CATALOG_SHA256
        for binding in installed.bindings:
            assert editor.read_active(uow, int(binding.workflow_id))["catalog_version"] == 2
    assert database_revisions(database) == {TARGET_REVISION}


def publish(uow, workflow_id, modes, key):
    active = editor.read_active(uow, workflow_id)
    draft = editor.save_draft(uow, workflow_id, CatalogDraft(
        expected_version=active["catalog_version"], expected_sha256=active["content_sha256"], modes=modes))
    command = CatalogPublish(expected_version=active["catalog_version"], expected_sha256=active["content_sha256"],
                             draft_sha256=draft["content_sha256"], operation_key=key)
    result = editor.publish(uow, workflow_id, draft["catalog_version"], command,
                            publisher_subject="verified-fixture-operator")
    return draft["catalog_version"], command, result


@pytest.mark.parametrize("explicit_targets", [False, True])
def test_cutover_preserves_publications_history_and_pins(predecessor, monkeypatch, explicit_targets):
    engine, installed = predecessor
    reader = catalog.load_profile
    original_publications = []
    with monkeypatch.context() as old_runtime, SAUnitOfWork(engine) as uow:
        old_runtime.setattr(catalog, "load_profile", lambda digest=None: reader(digest or PREVIOUS))
        for binding in installed.bindings:
            workflow_id = int(binding.workflow_id)
            if explicit_targets and binding.role_key in {"project_manager", "analyst"}:
                modes = deepcopy(editor.read_active(uow, workflow_id)["modes"])
                modes[0]["phases"][0]["instructions"][0]["description"] += " Deliberate saved business override."
                version, command, result = publish(uow, workflow_id, modes, "old-custom-" + binding.role_key)
                original_publications.append((workflow_id, version, command, result))
            mode = uow.workflows.list_modes(workflow_id)[0]
            phase = uow.phases.list(workflow_id, mode_id=mode.id)[0]
            task = uow.tasks.create({
                "project_id": int(binding.namespace_id), "workflow_id": workflow_id, "mode_id": mode.id,
                "task_key": "PINNED-" + binding.role_key, "current_phase_id": phase.id,
                "status": "active", "cycle_number": 1,
            })
            uow.record_step(task_id=task, phase_id=phase.id, mode_id=mode.id, cycle_number=1,
                            verdict="partial", worker_report=report_json("Actual preserved work"),
                            covered_item_ids=[], missing_item_ids=["original-gap"], blocker_messages=[],
                            evaluation_snapshot={"original": True}, supervisor_response={"complete": False})
            if explicit_targets and binding.role_key in {"project_manager", "analyst"}:
                target = editor._normalize(editor._definition(binding.workflow_key, TARGET)["modes"])
                version, command, result = publish(uow, workflow_id, target, "explicit-target-" + binding.role_key)
                original_publications.append((workflow_id, version, command, result))
    before = snapshot(engine)
    ensure_migrated(engine)
    ordinary_init(engine, monkeypatch)
    after = snapshot(engine)
    additive = {"workflow_modes", "phases", "phase_instructions", "phase_checks",
                "phase_evidence_requirements", "workflow_catalog_publications", "projects", "profession_workflows"}
    for name in before.keys() - additive - {"workflows", "alembic_version"}:
        assert after[name] == before[name], name
    for name in additive:
        assert all(row in after[name] for row in before[name]), name
    receipts_before = {(row["workflow_id"], row["catalog_version"])
                       for row in before["workflow_catalog_publications"]}
    receipts = [row for row in after["workflow_catalog_publications"]
                if (row["workflow_id"], row["catalog_version"]) not in receipts_before]
    assert len(receipts) == 9
    source_receipts = [row for row in receipts if row["operation_key"].startswith(editor.BASELINE_OPERATION)]
    assert len(source_receipts) == 7
    old_workflow_ids = {row["id"] for row in before["workflows"]}
    background_workflows = [row for row in after["workflows"] if row["id"] not in old_workflow_ids]
    assert {row["key"] for row in background_workflows} == {
        "fleet:background:bug_searcher", "fleet:background:refactorer",
    }
    background_ids = {row["id"] for row in background_workflows}
    assert {row["workflow_id"] for row in receipts if row not in source_receipts} == background_ids
    old_profession_ids = {row["id"] for row in before["projects"]}
    assert {row["code"] for row in after["projects"] if row["id"] not in old_profession_ids} == {
        "BUG_SEARCHER", "REFACTORER",
    }
    assert len(after["profession_workflows"]) == len(before["profession_workflows"]) + 2
    assert len(after["phases"]) == len(before["phases"]) + 33 + 20
    assert len([row for row in after["phases"] if row["workflow_id"] in background_ids]) == 20
    with SAUnitOfWork(engine) as uow:
        assert catalog.observe_installation(uow).instruction_manifest_sha256 == TARGET
        old_workflows = {row["id"]: row for row in before["workflows"]}
        for receipt in source_receipts:
            old = old_workflows[receipt["workflow_id"]]
            assert receipt["parent_version"] == old["active_catalog_version"]
            assert receipt["operation_key"] == f'{editor.BASELINE_OPERATION}{old["id"]}:{TARGET}'
            assert receipt["published_by_subject"] is None and receipt["published_at"] is None
            assert uow.workflows.get_by_id(old["id"]).active_catalog_version == receipt["catalog_version"]
        for workflow_id, version, command, original in original_publications:
            assert editor.read_operation(uow, workflow_id, command.operation_key) == original
            assert editor.publish(uow, workflow_id, version, command,
                                  publisher_subject="another-fixture-operator") == original
    ensure_migrated(engine)
    assert snapshot(engine) == after


@pytest.mark.parametrize("role", ["project_manager", "analyst", "architect"])
def test_unknown_active_custom_refuses_before_any_append(predecessor, monkeypatch, role):
    engine, installed = predecessor
    binding = next(b for b in installed.bindings if b.role_key == role)
    reader = catalog.load_profile
    with monkeypatch.context() as old_runtime, SAUnitOfWork(engine) as uow:
        old_runtime.setattr(catalog, "load_profile", lambda digest=None: reader(digest or PREVIOUS))
        modes = deepcopy(editor.read_active(uow, int(binding.workflow_id))["modes"])
        modes[0]["phases"][0]["instructions"][0]["description"] += " Keep this active custom instruction."
        publish(uow, int(binding.workflow_id), modes, "unaccepted-custom")
    before = snapshot(engine)
    calls = []
    monkeypatch.setattr(editor, "publish_baseline", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="Explicit current source cutover publication required"):
        ensure_migrated(engine)
    assert calls == [] and snapshot(engine) == before
    assert database_revisions(engine) == {PREVIOUS_REVISION}


def test_old_architect_publication_guard_does_not_gain_new_skill_authority(predecessor, monkeypatch):
    engine, installed = predecessor
    binding = next(b for b in installed.bindings if b.role_key == "architect")
    target = editor._normalize(editor._definition(binding.workflow_key, TARGET)["modes"])
    before = snapshot(engine)
    reader = catalog.load_profile
    with monkeypatch.context() as old_runtime, SAUnitOfWork(engine) as uow:
        old_runtime.setattr(catalog, "load_profile", lambda digest=None: reader(digest or PREVIOUS))
        with pytest.raises(editor.ConflictError, match="existing synchronous role skills"):
            publish(uow, int(binding.workflow_id), target, "not-admitted-before-cutover")
    assert snapshot(engine) == before


@pytest.mark.parametrize("drift", ["source", "pointer", "partial_target", "partial_current"])
def test_unaccepted_predecessor_refuses_without_partial_writes(predecessor, monkeypatch, drift):
    engine, installed = predecessor
    with SAUnitOfWork(engine) as uow:
        binding = installed.bindings[0]
        if drift == "source":
            instruction = uow.phase_instructions.list(int(binding.modes[0].phase_ids[0]))[0]
            uow.phase_instructions.update(instruction["id"], {"description": "Unreceipted drift"})
        elif drift == "pointer":
            workflow = uow.workflows.get_by_id(int(binding.workflow_id))
            uow.workflows.update(workflow.id, {"active_catalog_version": workflow.active_catalog_version + 1})
        elif drift == "partial_target":
            editor.publish_baseline(uow, uow.workflows.get_by_id(int(binding.workflow_id)), TARGET)
        else:
            for candidate in installed.bindings:
                workflow = uow.workflows.get_by_id(int(candidate.workflow_id))
                previous = editor._normalize(editor._definition(candidate.workflow_key, PREVIOUS)["modes"])
                target = editor._normalize(editor._definition(candidate.workflow_key, TARGET)["modes"])
                if previous != target:
                    editor.publish_baseline(uow, workflow, TARGET)
    before = snapshot(engine)
    with pytest.raises((ValueError, editor.ConflictError)):
        ensure_migrated(engine)
    assert snapshot(engine) == before
    assert database_revisions(engine) == {PREVIOUS_REVISION}


def test_known_but_wrong_predecessor_family_is_not_adopted(database, monkeypatch):
    run_alembic_command("upgrade", database, PREVIOUS_REVISION)
    reader = catalog.load_profile
    with monkeypatch.context() as old_runtime, SAUnitOfWork(database) as uow:
        old_runtime.setattr(catalog, "load_profile", lambda digest=None: reader(
            digest or "2f16635c0f588d1f285393b4ad8c163119b4dba4b9918335c821f295e88a4f64"))
        catalog.ensure_single_task_catalog(uow)
    before = snapshot(database)
    with pytest.raises(ValueError, match="exact sealed 852 predecessor"):
        ensure_migrated(database)
    assert snapshot(database) == before


def test_cutover_interruption_rolls_back_all_seven(predecessor, monkeypatch):
    engine, _ = predecessor
    before = snapshot(engine)
    producer = editor.publish_baseline
    calls = []

    def interrupted(uow, workflow, manifest):
        calls.append(workflow.key)
        result = producer(uow, workflow, manifest)
        if len(calls) == 5:
            raise RuntimeError("Controlled source cutover interruption")
        return result

    monkeypatch.setattr(editor, "publish_baseline", interrupted)
    with pytest.raises(RuntimeError, match="Controlled source cutover interruption"):
        ensure_migrated(engine)
    assert len(calls) == 5 and snapshot(engine) == before
    assert database_revisions(engine) == {PREVIOUS_REVISION}


def test_current_family_replay_is_noop_and_downgrade_keeps_history(predecessor, monkeypatch):
    engine, _ = predecessor
    ensure_migrated(engine)
    before = snapshot(engine)
    migration = importlib.import_module(
        "project_workflow.infrastructure.db.migrations.versions.0032_current_source_baseline")
    with engine.begin() as connection:
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        migration.upgrade()
    assert snapshot(engine) == before
    with engine.begin() as connection:
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        with pytest.raises(RuntimeError, match="forward-only"):
            migration.downgrade()
    assert snapshot(engine) == before
