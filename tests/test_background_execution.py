"""Controlled launch/report fixtures through the shared evaluator; no research agent runs."""
import json
from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from project_workflow import config
from project_workflow.application import background, catalog_publication
from project_workflow.domain.background import BackgroundConclusion, BackgroundStep
from project_workflow.domain.catalog_publication import CatalogDraft, CatalogPublish
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.infrastructure.background_admission import RunAdmission
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.background_professions import ensure_background_professions
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._report_helpers import report_json


@pytest.fixture
def execution(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "platform")
    config.get_settings.cache_clear()
    with SAUnitOfWork() as uow:
        identities = ensure_background_professions(uow)
        uow.commit()
        namespace = identities["BUG_SEARCHER"]
        profession = uow.projects.get_by_id(namespace)
        revision = catalog_publication.read_active(uow, profession.workflow_id)
        admission = RunAdmission.model_validate({
            "run_id": str(uuid4()), "project_id": str(uuid4()), "process_id": str(uuid4()),
            "session_id": str(uuid4()), "agent_id": str(uuid4()), "state": "running",
            "workflow_revision": revision["content_sha256"], "sources": [], "context": {
                "machine_subject": str(uuid4()), "namespace_id": str(namespace),
                "workflow_id": str(profession.workflow_id), "catalog_version": revision["catalog_version"],
                "config_revision": 1, "profession": "BUG_SEARCHER",
            },
        })
        command = BackgroundStep(interaction_protocol="configured-cli-v1", execution_mode="background",
                                 run_id=admission.run_id, namespace_id=namespace)
        yield uow, admission, command


@pytest.mark.parametrize("research_status", ["complete", "incomplete"])
def test_five_phases_replay_and_history_use_no_tracker_identity(execution, supervisor_llm, research_status):
    uow, admission, command = execution
    first = background.step(uow, command, admission, lambda: None)["result"]
    assert first["execution_mode"] == "background" and first["version"] == 1
    assert background.step(uow, command, admission, lambda: None)["result"] == first
    row = uow.session.scalar(select(m.TaskRuntimeAssignment))
    assert row.business_task_ref is None and row.binding_ref is None and row.concrete_agent_ref is None
    supervisor_llm("PASS")
    for index in range(1, 6):
        report = command.model_copy(update={"report": report_json(f"Fixture phase {index}", source="Fixture source"),
            "operation_key": f"phase-{index}", "expected_version": index})
        if index == 5:
            with pytest.raises(ValueError, match="explicit research_result"):
                background.step(uow, report, admission, lambda: None)
            assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 4
            conclusion = BackgroundConclusion(status=research_status, summary="Controlled fixture result",
                coverage=["Fixture contract"],
                limitations=[] if research_status == "complete" else ["Fixture data unavailable"])
            report = report.model_copy(update={"research_result": conclusion})
        result = background.step(uow, report, admission, lambda: None)["result"]
        assert result["version"] == index + 1 and result["complete"] == (index == 5)
        assert background.step(uow, report, admission, lambda: None)["result"] == result
        assert background.history(uow, admission, operation_key=f"phase-{index}")["result"] == result
    assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 5
    page = background.history(uow, admission, n=2)["result"]
    assert page["complete"] is True and page["research_result"]["status"] == research_status
    assert len(page["records"]) == 2 and page["next_before"] == page["records"][-1]["history_id"]
    second = background.history(uow, admission, n=2, before_history_id=page["next_before"])["result"]
    assert second["records"][0]["history_id"] < page["next_before"]
    with pytest.raises(ConflictError, match="payload conflict"):
        background.step(uow, report.model_copy(update={"report": report_json("Changed")}), admission, lambda: None)


def test_selected_publication_catalog_is_background_owned_and_catalog_read_only(execution, monkeypatch):
    from project_workflow.interfaces.ui.routes import runtime_api

    _, admission, _ = execution
    namespace, workflow = int(admission.context.namespace_id), int(admission.context.workflow_id)
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", "b" * 32)
    config.get_settings.cache_clear()
    selected = runtime_api.runtime_background_catalog(namespace, workflow, "Bearer " + "b" * 32)
    assert isinstance(selected, dict)
    assert selected["namespace_id"] == namespace and selected["workflow_id"] == workflow
    assert selected["content_sha256"] == admission.workflow_revision
    assert selected["modes"][0]["execution_scopes"] == ["background"]
    denied = runtime_api.runtime_background_catalog(namespace, workflow, None)
    assert denied.status_code == 401
    mismatch = runtime_api.runtime_background_catalog(namespace + 1000, workflow, "Bearer " + "b" * 32)
    assert mismatch.status_code == 409
    monkeypatch.setattr(runtime_api, "_authorized_service_credential",
                        lambda _: runtime_api._ServiceCredential("project_manager", "assignment", True))
    assert runtime_api.runtime_background_catalog(namespace, workflow, "Bearer fixture").status_code == 403


@pytest.mark.parametrize("value", [None,
    {"status": "complete", "summary": "", "coverage": ["source"], "limitations": []},
    {"status": "complete", "summary": "Fixture", "coverage": [], "limitations": []},
    {"status": "no-bugs", "summary": "Fixture", "coverage": ["source"], "limitations": []},
    {"status": "complete", "summary": "Fixture", "coverage": ["source"], "limitations": [], "model": "forbidden"}])
def test_research_result_is_typed_and_cannot_configure_execution(value):
    with pytest.raises(ValidationError):
        BackgroundConclusion.model_validate(value)


def test_publication_is_pinned_and_new_runs_receive_new_content(execution):
    uow, admission, command = execution
    before = background.step(uow, command, admission, lambda: None)["result"]
    active = catalog_publication.read_active(uow, int(admission.context.workflow_id))
    modes = deepcopy(active["modes"])
    modes[0]["phases"][0]["instructions"][0]["description"] = "New operator instruction"
    draft = catalog_publication.save_draft(uow, active["workflow_id"], CatalogDraft(
        expected_version=active["catalog_version"], expected_sha256=active["content_sha256"], modes=modes))
    published = catalog_publication.publish(uow, active["workflow_id"], draft["catalog_version"], CatalogPublish(
        expected_version=active["catalog_version"], expected_sha256=active["content_sha256"],
        draft_sha256=draft["content_sha256"], operation_key="background-publish-fixture"), publisher_subject="fixture")
    assert background.step(uow, command, admission, lambda: None)["result"] == before
    next_admission = admission.model_copy(deep=True, update={"run_id": str(uuid4())})
    next_admission.context.catalog_version = published["catalog_version"]
    next_admission.workflow_revision = published["content_sha256"]
    next_command = command.model_copy(update={"run_id": next_admission.run_id})
    current = background.step(uow, next_command, next_admission, lambda: None)["result"]
    assert "New operator instruction" in current["instructions"]
    assert current["workflow_revision"] != before["workflow_revision"]


def test_revoked_launch_does_not_commit_evaluation(execution, supervisor_llm):
    uow, admission, command = execution
    background.step(uow, command, admission, lambda: None)
    supervisor_llm("PASS")
    report = command.model_copy(update={"report": report_json("Fixture report"),
        "operation_key": "revoked-fixture", "expected_version": 1})

    def revoked():
        raise ConflictError("Launch stopped")

    with pytest.raises(ConflictError):
        background.step(uow, report, admission, revoked)
    uow.rollback()
    assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 0
    assert background.step(uow, command, admission, lambda: None)["result"]["version"] == 1


def test_background_dto_rejects_tracker_and_runtime_settings():
    base = {"interaction_protocol": "configured-cli-v1", "execution_mode": "background",
            "run_id": str(uuid4()), "namespace_id": 1}
    for field, value in {"task": "FAKE-1", "workflow_id": 1, "model": "override", "start": True,
                         "project_id": str(uuid4()), "requirements_revision": 1}.items():
        with pytest.raises(ValidationError):
            BackgroundStep.model_validate({**base, field: value})


def execution_rows(uow):
    return {
        model.__tablename__: uow.session.execute(select(model.__table__)).mappings().all()
        for model in (m.Task, m.TaskRuntimeAssignment, m.TaskStepHistoryEntry, m.TaskPhaseEvent)
    }


@pytest.mark.parametrize("changed", ["platform-mode", "run-id", "namespace", "profession", "publication"])
def test_launch_refuses_foreign_identity_or_publication_without_creating_a_cursor(execution, monkeypatch, changed):
    uow, admission, command = execution
    foreign = admission.model_copy(deep=True)
    request = command
    if changed == "platform-mode":
        monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "standalone")
        config.get_settings.cache_clear()
    elif changed == "run-id":
        request = command.model_copy(update={"run_id": str(uuid4())})
    elif changed == "namespace":
        request = command.model_copy(update={"namespace_id": command.namespace_id + 1000})
    elif changed == "profession":
        foreign.context.profession = "REFACTORER"
    else:
        foreign.workflow_revision = "f" * 64
    before = execution_rows(uow)
    with pytest.raises(ConflictError):
        background.step(uow, request, foreign, lambda: None)
    assert execution_rows(uow) == before
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "platform")
    config.get_settings.cache_clear()
    assert background.step(uow, command, admission, lambda: None)["result"]["version"] == 1


@pytest.mark.parametrize("changed", ["assignment-revision", "cursor-cycle", "ledger", "stale-report"])
def test_saved_cursor_rejects_changed_custody_and_keeps_the_original_history(execution, supervisor_llm, changed):
    uow, admission, command = execution
    background.step(uow, command, admission, lambda: None)
    supervisor_llm("PASS")
    first_report = command.model_copy(update={"report": report_json("First observation"),
        "operation_key": "first-observation", "expected_version": 1})
    assert background.step(uow, first_report, admission, lambda: None)["result"]["version"] == 2
    original_history = background.history(uow, admission)["result"]
    task = uow.session.scalar(select(m.Task))
    assignment = uow.session.scalar(select(m.TaskRuntimeAssignment))
    entry = uow.session.scalar(select(m.TaskStepHistoryEntry))
    request = command
    if changed == "assignment-revision":
        assignment.assignment_revision += 1
    elif changed == "cursor-cycle":
        task.cycle_number += 1
    elif changed == "ledger":
        entry.evaluation_snapshot = "{}"
    else:
        request = first_report.model_copy(update={"operation_key": "stale-observation"})
    uow.session.flush()
    before = execution_rows(uow)
    with pytest.raises(ConflictError):
        background.step(uow, request, admission, lambda: None)
    assert execution_rows(uow) == before
    uow.rollback()
    assert background.history(uow, admission)["result"] == original_history


def test_completed_cursor_without_a_conclusion_is_not_reported_as_success(execution):
    uow, admission, command = execution
    background.step(uow, command, admission, lambda: None)
    task = uow.session.scalar(select(m.Task))
    task.status = "done"
    uow.session.flush()
    before = execution_rows(uow)
    with pytest.raises(ConflictError, match="conclusion missing"):
        background.history(uow, admission)
    assert execution_rows(uow) == before
    uow.rollback()
    assert background.history(uow, admission)["result"]["version"] == 1


@pytest.mark.parametrize("changed", ["mode", "run-id"])
def test_archived_history_refuses_a_foreign_saved_identity_without_changing_it(execution, changed):
    uow, admission, command = execution
    background.step(uow, command, admission, lambda: None)
    assignment = uow.session.scalar(select(m.TaskRuntimeAssignment))
    payload = json.loads(assignment.payload)
    if changed == "mode":
        payload["mode"] = "single_task"
    else:
        payload["admission"]["run_id"] = str(uuid4())
    assignment.payload = json.dumps(payload)
    uow.session.flush()
    before = execution_rows(uow)
    with pytest.raises(ConflictError):
        background.archived_history(uow, admission.run_id, n=1, before_history_id=None)
    assert execution_rows(uow) == before
    uow.rollback()
    assert background.archived_history(uow, admission.run_id, n=1, before_history_id=None)["result"]["version"] == 1


@pytest.mark.parametrize("selector", [{"n": 0}, {"n": 201}, {"operation_key": "original", "before_history_id": 1}])
def test_history_rejects_invalid_selectors_and_does_not_start_research(execution, selector):
    uow, admission, command = execution
    before = execution_rows(uow)
    with pytest.raises(ValueError, match="Invalid background history selector"):
        background.history(uow, admission, **selector)
    with pytest.raises(NotFoundError, match="not started"):
        background.history(uow, admission, n=1)
    assert execution_rows(uow) == before
    background.step(uow, command, admission, lambda: None)
    assert background.history(uow, admission, n=1)["result"]["records"] == []


@pytest.mark.parametrize("change", [{"summary": " "}, {"coverage": [" "]}, {"limitations": [" "]}])
def test_conclusion_requires_meaningful_text_in_each_statement(change):
    value = {"status": "incomplete", "summary": "Read the authorized source", "coverage": ["module.py"],
             "limitations": ["A dependency could not be read"]}
    with pytest.raises(ValidationError, match="empty statements"):
        BackgroundConclusion.model_validate(value | change)


@pytest.mark.parametrize("change", [
    {"operation_key": None}, {"operation_key": " padded "}, {"operation_key": "control\nkey"}])
def test_report_requires_a_canonical_operation_key(change):
    value = {"interaction_protocol": "configured-cli-v1", "execution_mode": "background", "run_id": str(uuid4()),
             "namespace_id": 1, "report": report_json("Observation"),
             "operation_key": "observation", "expected_version": 1}
    with pytest.raises(ValidationError):
        BackgroundStep.model_validate(value | change)
