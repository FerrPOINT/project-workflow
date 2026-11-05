"""Analyst phase progression via HTTP; evaluator and external peers are controlled."""

import pytest

from project_workflow.infrastructure.db.single_task_catalog import load_profile
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._report_helpers import report_json
from tests.test_configured_cli import MACHINE, enroll, step
from tests.test_configured_cli import configured as configured


def analyst_phases():
    workflow = next(w for w in load_profile()[0]["workflows"] if w["role_key"] == "analyst")
    return workflow["modes"][0]["phases"]


def test_research_contract_covers_hypotheses_primary_sources_and_disconfirmation():
    phases = analyst_phases()
    assert [p["phase_order"] for p in phases] == list(range(1, 13))
    assert len({p["name"] for p in phases}) == 12
    questions = str(phases[1])
    internal = str(phases[2])
    public = str(phases[3])
    synthesis = str(phases[4])
    assert "disprove" in questions and "stopping condition" in questions
    assert "actual project binding" in internal and "Tracker-bound" in internal
    assert "exploratory research" in public and "disprove" in public
    assert "web_search" in public and "web_extract" in public
    assert "snippets and tables of contents are not proof" in public
    assert "internal identifiers, filenames" in public and "credentials" in public
    assert "reject or leave each material hypothesis" in synthesis


def test_final_artifact_and_future_delivery_do_not_block_early_research():
    phases = analyst_phases()
    for phase in phases[:-1]:
        assert "ArtifactReceipt" not in str(phase["checks"] + phase["evidence"])
        assert "All mandatory behavior is supported and covered" not in str(phase["checks"])
    final = str(phases[-1])
    assert "download and compare raw bytes/SHA256 before this final phase report" in final
    assert "unresolved essential facts prevent final acceptance" in final
    assert "leave Workflow unfinished" in final and "without a delivery proposal" in final
    assert "sdlc critical-blocker" not in str(phases)
    assert "ONLY after accepted Workflow complete=true" in final


@pytest.mark.parametrize("configured", [("analyst", "analysis")], indirect=True)
def test_partial_research_and_mandatory_gap_do_not_complete_or_lose_history(configured, supervisor_llm):
    enrollment = enroll(configured)
    phases = analyst_phases()
    version = 1
    for number, phase in enumerate(phases, 1):
        current = step(configured).json()["result"]
        assert current["phase_code"] == phase["code"]
        assert phase["name"] in current["instructions"] or phase["description"] in current["instructions"]
        # Both an incomplete research step and an unresolved mandatory final gap
        # stay in place, without creating a terminal receipt or delivery commands.
        if number in (4, 12):
            supervisor_llm("PARTIAL", missing=[current["phase_contract"]["required_checks"][0]])
            command = dict(report=report_json("Relevant source unavailable; mandatory fact still unsupported"),
                           operation_key=f"gap-{number}", expected_version=version)
            response = step(configured, **command)
            assert response.status_code == 200, response.text
            partial = response.json()["result"]
            assert partial["complete"] is False and partial["phase_code"] == phase["code"]
            assert "terminal_receipt" not in partial and "completion_instructions" not in partial
            assert step(configured, **command).json() == response.json()
            version = partial["version"]
        supervisor_llm("PASS")
        response = step(configured, report=report_json(f"Controlled completed work for {phase['name']}"),
                        operation_key=f"accepted-{number}", expected_version=version)
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["complete"] is (number == 12)
        version = result["version"]
    assert "discussion publish" in result["completion_instructions"]
    assert "sdlc result propose" in result["completion_instructions"]
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key(configured[1]["task"], project_id=configured[1]["namespace_id"])
        assert len(uow.step_history.list(task_id=task.id)) == 14
    history = configured[0].get("/internal/runtime/history", headers=MACHINE, params={
        "interaction_protocol": "configured-cli-v1", "task": configured[1]["task"],
        "namespace_id": configured[1]["namespace_id"], "execution_ref": enrollment["execution_ref"],
    })
    assert history.status_code == 200, history.text
    assert len(history.json()["result"]["records"]) == 14


def test_enrolled_analyst_continues_original_three_phases_after_structural_upgrade(monkeypatch, supervisor_llm):
    import importlib
    from types import SimpleNamespace
    from uuid import uuid4

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from project_workflow.application import configured_cli
    from project_workflow.infrastructure.db import single_task_catalog as catalog
    from project_workflow.infrastructure.db.session import get_engine
    from tests import test_configured_cli as protocol

    previous = "62762bf58f337d9e063226aef58ea6c89cdfb2e87159056f1a6b2b6c4d1ddf3a"
    old_catalog, old_manifest = catalog.load_profile(previous)
    fixture = None
    try:
        # Reproduce the installed predecessor, not a hand-edited current task.
        with monkeypatch.context() as old_runtime:
            old_runtime.setattr(catalog, "load_profile", lambda *_args: (old_catalog, old_manifest))
            old_runtime.setattr(configured_cli, "MANIFEST_SHA256", previous)
            old_runtime.setattr(configured_cli, "CATALOG_SHA256", old_manifest["workflow_catalog"]["sha256"])
            fixture = protocol.configured.__wrapped__(monkeypatch, SimpleNamespace(param=("analyst", "analysis")))
            context = next(fixture)
            original = enroll(context)
            supervisor_llm("PASS")
            command = dict(report=report_json("Original completed research"), operation_key="old-research",
                           expected_version=1)
            accepted = step(context, **command).json()
            before = step(context).json()
        migration = importlib.import_module(
            "project_workflow.infrastructure.db.migrations.versions.0029_analyst_twelve_phases")
        with get_engine().begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
        assert step(context).json() == before
        assert step(context, **command).json() == accepted
        for version in (2, 3):
            response = step(context, report=report_json("Original snapshot work"),
                            operation_key=f"old-{version}", expected_version=version)
            assert response.status_code == 200, response.text
        assert response.json()["result"]["complete"] is True
        client, assignment = context
        task_ref = str(uuid4())
        new = {**assignment, "task": "SDLC-902", "operation_key": "new-analyst",
               "business_task_ref": task_ref, "tracker_task_id": task_ref,
               "assignment_ref": str(uuid4()), "tracker_execution_id": str(uuid4())}
        current = enroll((client, new))
        assert current["mode_id"] != original["mode_id"]
        with SAUnitOfWork() as uow:
            assert len(uow.phases.list(original["workflow_id"], mode_id=original["mode_id"])) == 3
            assert len(uow.phases.list(current["workflow_id"], mode_id=current["mode_id"])) == 12
    finally:
        if fixture is not None:
            fixture.close()
