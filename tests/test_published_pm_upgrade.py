"""A legitimate published PM must never be rewritten by a catalog upgrade."""

from copy import deepcopy

import pytest
import sqlalchemy as sa

from project_workflow.application import catalog_publication as editor
from project_workflow.domain.catalog_publication import CatalogDraft, CatalogPublish
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.session import (
    database_revisions,
    ensure_migrated,
    get_engine,
    initialization_transaction,
    run_alembic_command,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._report_helpers import report_json
from tests.test_postgres_integration import pg_url as pg_url

PREDECESSOR = "0023_catalog_publication_author"
HEAD = "0030_analyst_baseline_ledger"
PROFILE = "e0cde0c044fe1a38b6fa0f387cc30e0da6e89dedb35b89a893263fd7d2558a40"
TARGETS = (
    "332cfd4fb3419d5765008e196cffb508540462ddd89b798ab4e89379ac5b1796",
    "d76ecbb632b1ceebf33bf78e8e0dedaec278538227d653aa9fd3c998e19ea694",
)
ANALYST_PREDECESSORS = (
    (PREDECESSOR, PROFILE),
    ("0026_analyst_artifact_acceptance", "ab182b9bc6f7182c6250ba20cc322749f6fbae28ddc183765fbd888a658900e6"),
)
ANALYST_TARGET_REVISION = "0028_analyst_read_sources"
ANALYST_TARGET_PROFILE = "62762bf58f337d9e063226aef58ea6c89cdfb2e87159056f1a6b2b6c4d1ddf3a"


def _snapshot(engine):
    tables = sa.MetaData()
    tables.reflect(bind=engine)
    with engine.connect() as connection:
        return {
            table.name: connection.execute(sa.select(table).order_by(*table.primary_key.columns)).mappings().all()
            for table in tables.sorted_tables
        }


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state():
    """These cases own historical schemas, not the shared current seed."""
    yield


def test_published_pm_upgrade_preserves_published_content_and_history(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'published-pm.db'}")
    assert_published_pm_upgrade_preserves_published_content_and_history(engine, monkeypatch)


@pytest.mark.integration
def test_published_pm_upgrade_preserves_published_content_and_history_on_postgres(pg_url, monkeypatch):
    assert_published_pm_upgrade_preserves_published_content_and_history(get_engine(pg_url), monkeypatch)


@pytest.mark.parametrize("role", ["project_manager", "analyst"])
def test_unreceipted_baseline_drift_is_not_accepted_as_a_publication(tmp_path, monkeypatch, role):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'unreceipted-drift.db'}")
    assert_published_pm_upgrade_preserves_published_content_and_history(engine, monkeypatch, drift_role=role)


def assert_published_pm_upgrade_preserves_published_content_and_history(engine, monkeypatch, *, drift_role=None):
    try:
        run_alembic_command("upgrade", engine, PREDECESSOR)
        reader = catalog.load_profile
        predecessor = reader(PROFILE)
        with monkeypatch.context() as patch:
            patch.setattr(catalog, "load_profile", lambda digest=None: reader(digest) if digest else predecessor)
            with SAUnitOfWork(engine) as uow:
                installed = catalog.ensure_single_task_catalog(uow)
                workflow_id = int(next(b for b in installed.bindings if b.role_key == "project_manager").workflow_id)
                analyst_id = int(next(b for b in installed.bindings if b.role_key == "analyst").workflow_id)
                publications = {}
                for version in range(2, 14):
                    active = editor.read_active(uow, workflow_id)
                    modes = deepcopy(active["modes"])
                    modes[0]["phases"][0]["instructions"][0]["description"] += f" Published PM clarification {version}."
                    saved = editor.save_draft(uow, workflow_id, CatalogDraft(
                        expected_version=active["catalog_version"], expected_sha256=active["content_sha256"],
                        modes=modes,
                    ))
                    published = editor.publish(uow, workflow_id, saved["catalog_version"], CatalogPublish(
                        expected_version=active["catalog_version"], expected_sha256=active["content_sha256"],
                        draft_sha256=saved["content_sha256"], operation_key=f"published-pm-{version}",
                    ), publisher_subject="verified-test-admin")
                    assert published["catalog_version"] == version
                    publications[version] = published

        with SAUnitOfWork(engine) as uow:
            catalog._observe_profile(uow, *predecessor)
            assert editor.read_active(uow, workflow_id)["catalog_version"] == 13
            active_pm = editor.read_active(uow, workflow_id)
            assert all(w.active_catalog_version == (13 if w.id == workflow_id else 1) for w in uow.workflows.list())
            for digest in TARGETS:
                with pytest.raises(ValueError):
                    catalog._observe_profile(uow, *reader(digest))
            mode = uow.workflows.list_modes(workflow_id)[0]
            assert mode.catalog_version == 13
            phase = uow.phases.list(workflow_id, mode_id=mode.id)[0]
            binding = next(b for b in installed.bindings if b.role_key == "project_manager")
            task_id = uow.tasks.create({
                "project_id": int(binding.namespace_id), "workflow_id": workflow_id,
                "mode_id": mode.id, "task_key": "PUBLISHED-PM-13",
                "title": "Unfinished work on the published PM revision",
                "current_phase_id": phase.id, "status": "active", "cycle_number": 1,
            })
            history_id = uow.record_step(
                task_id=task_id, phase_id=phase.id, mode_id=mode.id, cycle_number=1,
                verdict="partial", worker_report=report_json("Original incomplete business document"),
                covered_item_ids=[], missing_item_ids=["saved-required-item"], blocker_messages=[],
                evaluation_snapshot={"fixture": "Original saved assessment before catalog upgrade"},
                supervisor_response={"verdict": "PARTIAL", "complete": False},
            )

        drift_revision = PREDECESSOR
        if drift_role == "analyst":
            # Exercise 0027's source guard independently of 0024's selector.
            drift_revision = "0026_analyst_artifact_acceptance"
            with initialization_transaction(engine) as connection:
                run_alembic_command("upgrade", connection, drift_revision)
        if drift_role is not None:
            with SAUnitOfWork(engine) as uow:
                drift_id = workflow_id if drift_role == "project_manager" else analyst_id
                baseline_mode = uow.workflows.list_modes(drift_id, catalog_version=1)[0]
                baseline_phase = uow.phases.list(drift_id, mode_id=baseline_mode.id)[0]
                instruction = uow.phase_instructions.list(baseline_phase.id)[0]
                assert uow.session.get(m.WorkflowCatalogPublication, (drift_id, 1)) is None
                uow.phase_instructions.update(instruction["id"], {
                    "description": instruction["description"] + " Unreceipted source baseline drift.",
                })

        before = _snapshot(engine)
        assert len(before["tasks"]) == len(before["task_step_history"]) == 1
        assert before["tasks"][0]["id"] == task_id
        assert before["tasks"][0]["mode_id"] == mode.id
        assert before["task_step_history"][0]["id"] == history_id
        assert before["task_step_history"][0]["task_id"] == task_id
        assert before["task_step_history"][0]["mode_id"] == mode.id
        assert before["tasks"][0]["cycle_number"] == before["task_step_history"][0]["cycle_number"] == 1
        if drift_role is not None:
            with pytest.raises(ValueError, match="Cannot replace a partial or customized single-task catalog"):
                with initialization_transaction(engine) as connection:
                    ensure_migrated(connection)
            assert database_revisions(engine) == {drift_revision}
            assert _snapshot(engine) == before
            return

        with initialization_transaction(engine) as connection:
            run_alembic_command("upgrade", connection, HEAD)
        assert database_revisions(engine) == {HEAD}
        after = _snapshot(engine)

        # Only source baseline content and the two Analyst publications may change.
        changed_tables = {
            "alembic_version", "workflows", "workflow_modes", "workflow_catalog_publications",
            "phases", "phase_instructions", "phase_checks", "phase_evidence_requirements",
        }
        for name in before.keys() - changed_tables:
            assert after[name] == before[name], name
        modes_after = {row["id"]: row for row in after["workflow_modes"]}
        for row in before["workflow_modes"]:
            assert modes_after[row["id"]] == row
        old_modes = {row["id"] for row in before["workflow_modes"]}
        new_modes = [row for row in after["workflow_modes"] if row["id"] not in old_modes]
        assert [(row["workflow_id"], row["catalog_version"]) for row in new_modes] == [
            (analyst_id, 2), (analyst_id, 3),
        ]
        workflows_after = {row["id"]: row for row in after["workflows"]}
        for row in before["workflows"]:
            expected = dict(row)
            if row["id"] == analyst_id:
                expected["active_catalog_version"] = 3
            assert workflows_after[row["id"]] == expected

        published_modes = {row["id"] for row in before["workflow_modes"]
                           if row["workflow_id"] == workflow_id and row["catalog_version"] > 1}
        published_phases = {row["id"] for row in before["phases"] if row["mode_id"] in published_modes}
        assert [row for row in after["phases"] if row["mode_id"] in published_modes] == [
            row for row in before["phases"] if row["mode_id"] in published_modes]
        for name in ("phase_instructions", "phase_checks", "phase_evidence_requirements"):
            assert [row for row in after[name] if row["phase_id"] in published_phases] == [
                row for row in before[name] if row["phase_id"] in published_phases], name

        receipts_after = {(row["workflow_id"], row["catalog_version"]): row
                          for row in after["workflow_catalog_publications"]}
        old_receipts = {(row["workflow_id"], row["catalog_version"]) for row in before["workflow_catalog_publications"]}
        for row in before["workflow_catalog_publications"]:
            assert receipts_after[(row["workflow_id"], row["catalog_version"])] == row
        assert set(receipts_after) - old_receipts == {(analyst_id, 2), (analyst_id, 3)}
        for version, digest in (
            (2, "7aa0e6c758e2c31cd1dd69ce30826aecaf565e25e4f5fcedcdf9215fcddd1075"),
            (3, "2f16635c0f588d1f285393b4ad8c163119b4dba4b9918335c821f295e88a4f64"),
        ):
            receipt = receipts_after[(analyst_id, version)]
            assert receipt["parent_version"] == version - 1
            assert receipt["operation_key"] == f"{editor.BASELINE_OPERATION}{analyst_id}:{digest}"
            assert receipt["published_by_subject"] is None and receipt["published_at"] is None

        with SAUnitOfWork(engine) as uow:
            catalog._observe_profile(uow, *reader("2f16635c0f588d1f285393b4ad8c163119b4dba4b9918335c821f295e88a4f64"))
            assert editor.read_active(uow, workflow_id) == active_pm
            for version, published in publications.items():
                assert editor.read_operation(uow, workflow_id, f"published-pm-{version}") == published
            for new_mode in new_modes:
                assert len(uow.phases.list(analyst_id, mode_id=new_mode["id"])) == 12

        # Repeating the same upgrade must not append publications or change history.
        with initialization_transaction(engine) as connection:
            run_alembic_command("upgrade", connection, HEAD)
        assert database_revisions(engine) == {HEAD}
        assert _snapshot(engine) == after
    finally:
        engine.dispose()


@pytest.mark.parametrize(("predecessor", "profile"), ANALYST_PREDECESSORS, ids=["0024", "0027"])
def test_published_analyst_upgrade_preserves_active_revision_and_history(tmp_path, monkeypatch, predecessor, profile):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'published-analyst.db'}")
    assert_published_analyst_upgrade_preserves_active_revision_and_history(engine, monkeypatch, predecessor, profile)


@pytest.mark.integration
@pytest.mark.parametrize(("predecessor", "profile"), ANALYST_PREDECESSORS, ids=["0024", "0027"])
def test_published_analyst_upgrade_preserves_active_revision_and_history_on_postgres(
    pg_url, monkeypatch, predecessor, profile,
):
    assert_published_analyst_upgrade_preserves_active_revision_and_history(
        get_engine(pg_url), monkeypatch, predecessor, profile)


def assert_published_analyst_upgrade_preserves_active_revision_and_history(engine, monkeypatch, predecessor, profile):
    try:
        run_alembic_command("upgrade", engine, predecessor)
        reader = catalog.load_profile
        original = reader(profile)
        with monkeypatch.context() as patch:
            patch.setattr(catalog, "load_profile", lambda digest=None: reader(digest) if digest else original)
            with SAUnitOfWork(engine) as uow:
                installed = catalog.ensure_single_task_catalog(uow)
                binding = next(b for b in installed.bindings if b.role_key == "analyst")
                workflow_id = int(binding.workflow_id)
                active = editor.read_active(uow, workflow_id)
                modes = deepcopy(active["modes"])
                phase = modes[0]["phases"][0]
                phase["instructions"][0]["description"] += " Published Analyst clarification."
                phase["checks"][0] += " Published Analyst check."
                phase["evidence"][0] += " Published Analyst evidence."
                saved = editor.save_draft(uow, workflow_id, CatalogDraft(
                    expected_version=1, expected_sha256=active["content_sha256"], modes=modes))
                published = editor.publish(uow, workflow_id, saved["catalog_version"], CatalogPublish(
                    expected_version=1, expected_sha256=active["content_sha256"],
                    draft_sha256=saved["content_sha256"], operation_key="published-analyst-2",
                ), publisher_subject="verified-test-admin")
                assert published["catalog_version"] == 2

        with SAUnitOfWork(engine) as uow:
            catalog._observe_profile(uow, *original)
            active = editor.read_active(uow, workflow_id)
            mode = uow.workflows.list_modes(workflow_id)[0]
            assert mode.catalog_version == 2
            phase = uow.phases.list(workflow_id, mode_id=mode.id)[0]
            task_id = uow.tasks.create({
                "project_id": int(binding.namespace_id), "workflow_id": workflow_id,
                "mode_id": mode.id, "task_key": "PUBLISHED-ANALYST-2", "title": "Saved published analysis",
                "current_phase_id": phase.id, "status": "active", "cycle_number": 1,
            })
            history_id = uow.record_step(
                task_id=task_id, phase_id=phase.id, mode_id=mode.id, cycle_number=1,
                verdict="partial", worker_report=report_json("Original incomplete analysis document"),
                covered_item_ids=[], missing_item_ids=["saved-analysis-item"], blocker_messages=[],
                evaluation_snapshot={"fixture": "Saved Analyst assessment before catalog upgrade"},
                supervisor_response={"verdict": "PARTIAL", "complete": False},
            )
        before = _snapshot(engine)
        assert before["tasks"][0]["id"] == task_id
        assert before["task_step_history"][0]["id"] == history_id
        assert before["tasks"][0]["cycle_number"] == before["task_step_history"][0]["cycle_number"] == 1

        with initialization_transaction(engine) as connection:
            run_alembic_command("upgrade", connection, ANALYST_TARGET_REVISION)
        assert database_revisions(engine) == {ANALYST_TARGET_REVISION}
        after = _snapshot(engine)
        content_tables = {"phases", "phase_instructions", "phase_checks", "phase_evidence_requirements"}
        for name in before.keys() - content_tables - {"alembic_version"}:
            assert after[name] == before[name], name
        published_phases = {row["id"] for row in before["phases"] if row["mode_id"] == mode.id}
        assert [row for row in after["phases"] if row["mode_id"] == mode.id] == [
            row for row in before["phases"] if row["mode_id"] == mode.id]
        for name in content_tables - {"phases"}:
            assert [row for row in after[name] if row["phase_id"] in published_phases] == [
                row for row in before[name] if row["phase_id"] in published_phases], name
        with SAUnitOfWork(engine) as uow:
            catalog._observe_profile(uow, *reader(ANALYST_TARGET_PROFILE))
            assert editor.read_active(uow, workflow_id) == active
            assert editor.read_operation(uow, workflow_id, "published-analyst-2") == published
        with initialization_transaction(engine) as connection:
            run_alembic_command("upgrade", connection, ANALYST_TARGET_REVISION)
        assert _snapshot(engine) == after

        with initialization_transaction(engine) as connection:
            run_alembic_command("upgrade", connection, HEAD)
        assert database_revisions(engine) == {HEAD}
        final = _snapshot(engine)
        additive_tables = content_tables | {"workflow_modes", "workflow_catalog_publications"}
        for name in after.keys() - additive_tables - {"alembic_version", "workflows"}:
            assert final[name] == after[name], name
        for name in additive_tables:
            assert all(row in final[name] for row in after[name]), name
        final_workflows = {row["id"]: row for row in final["workflows"]}
        for row in after["workflows"]:
            expected = dict(row)
            if row["id"] == workflow_id:
                expected["active_catalog_version"] = 4
            assert final_workflows[row["id"]] == expected
        old_modes = {row["id"] for row in after["workflow_modes"]}
        new_modes = [row for row in final["workflow_modes"] if row["id"] not in old_modes]
        assert [(row["workflow_id"], row["catalog_version"]) for row in new_modes] == [
            (workflow_id, 3), (workflow_id, 4),
        ]
        old_receipts = {(row["workflow_id"], row["catalog_version"])
                        for row in after["workflow_catalog_publications"]}
        new_receipts = {(row["workflow_id"], row["catalog_version"]): row
                        for row in final["workflow_catalog_publications"]
                        if (row["workflow_id"], row["catalog_version"]) not in old_receipts}
        assert set(new_receipts) == {(workflow_id, 3), (workflow_id, 4)}
        for version, digest in (
            (3, "7aa0e6c758e2c31cd1dd69ce30826aecaf565e25e4f5fcedcdf9215fcddd1075"),
            (4, "2f16635c0f588d1f285393b4ad8c163119b4dba4b9918335c821f295e88a4f64"),
        ):
            receipt = new_receipts[(workflow_id, version)]
            assert receipt["parent_version"] == version - 1
            assert receipt["operation_key"] == f"{editor.BASELINE_OPERATION}{workflow_id}:{digest}"
            assert receipt["published_by_subject"] is None and receipt["published_at"] is None
        with SAUnitOfWork(engine) as uow:
            catalog._observe_profile(uow, *reader("2f16635c0f588d1f285393b4ad8c163119b4dba4b9918335c821f295e88a4f64"))
            assert editor.read_active(uow, workflow_id)["catalog_version"] == 4
            assert editor.read_revision(uow, uow.workflows.get_by_id(workflow_id), 2) == active
            assert editor.read_operation(uow, workflow_id, "published-analyst-2") == published
            for new_mode in new_modes:
                assert len(uow.phases.list(workflow_id, mode_id=new_mode["id"])) == 12
        with initialization_transaction(engine) as connection:
            run_alembic_command("upgrade", connection, HEAD)
        assert database_revisions(engine) == {HEAD}
        assert _snapshot(engine) == final
    finally:
        engine.dispose()
