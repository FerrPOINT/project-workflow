"""Real repository reads: fixed SQL sets without weakening catalog validation."""

from collections import Counter

import pytest
from sqlalchemy import event
from sqlalchemy.sql import Select

from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.managed_catalog import (
    ManagedMode,
    _ArchivedWorkflowDefinition,
    _assert_existing_workflow,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests.test_single_task_profile_compatibility import all_rows, install_retained


@pytest.fixture(params=["current", "retained"])
def installed(request, monkeypatch):
    if request.param == "retained":
        original = install_retained(monkeypatch)
    else:
        with SAUnitOfWork() as seed:
            original = catalog.ensure_single_task_catalog(seed)
    with SAUnitOfWork() as uow:
        yield uow, original


def test_content_validation_uses_three_sql_sets_across_modes_in_same_uow(installed, monkeypatch):
    uow, original = installed
    source, _ = catalog.load_profile(original.instruction_manifest_sha256)
    definition = next(w for w in source["workflows"] if w["role_key"] == "developer")
    workflow = next(w for w in uow.workflows.list() if w.key == definition["key"])
    expected = _ArchivedWorkflowDefinition(
        key=definition["key"], name=definition["name"], description=definition["description"],
        role_key=definition["role_key"], modes=[ManagedMode.model_validate(mode) for mode in definition["modes"]],
    )
    modes = uow.workflows.list_modes(workflow.id)
    assert len(modes) == 2
    phase_ids = [phase.id for mode in modes for phase in uow.phases.list(workflow.id, mode_id=mode.id)]
    repositories = (uow.phase_instructions, uow.phase_checks, uow.phase_evidence_requirements)
    # Compare the existing ordered single-phase results with each batched read.
    baseline = [{phase_id: repo.list(phase_id) for phase_id in phase_ids} for repo in repositories]
    before = all_rows(uow)
    calls = []

    for index, repo in enumerate(repositories):
        read = repo.list_for_phases

        def record(ids, *, index=index, repo=repo, read=read):
            assert repo._session is uow.session
            assert list(ids) == phase_ids
            rows = read(ids)
            assert rows == baseline[index]
            calls.append(index)
            return rows

        monkeypatch.setattr(repo, "list_for_phases", record)

    entities = (m.PhaseInstruction, m.PhaseCheck, m.PhaseEvidenceRequirement)
    counts = Counter()
    connection = uow.session.connection()

    def sql_read(conn, _cursor, _statement, _parameters, context, _many):
        statement = getattr(context.compiled, "statement", None)
        if isinstance(statement, Select):
            for column in statement.column_descriptions:
                entity = column.get("entity")
                if entity in entities:
                    assert conn is connection
                    counts[entity] += 1

    event.listen(connection, "before_cursor_execute", sql_read)
    try:
        _assert_existing_workflow(uow, workflow, expected)
    finally:
        event.remove(connection, "before_cursor_execute", sql_read)
    assert counts == Counter(dict.fromkeys(entities, 1))
    assert calls == [0, 1, 2]
    assert all_rows(uow) == before


@pytest.mark.parametrize("kind", ["instructions", "checks", "evidence"])
@pytest.mark.parametrize("drift", ["missing", "order"])
def test_batched_catalog_still_rejects_missing_or_reordered_content(installed, kind, drift):
    uow, original = installed
    assert catalog.observe_installation(uow) == original
    repository = {
        "instructions": uow.phase_instructions,
        "checks": uow.phase_checks,
        "evidence": uow.phase_evidence_requirements,
    }[kind]
    phase_ids = [int(p) for binding in original.bindings for mode in binding.modes for p in mode.phase_ids]
    rows = next(items for phase_id in phase_ids if len(items := repository.list(phase_id)) >= 2)
    if drift == "missing":
        repository.delete(rows[0]["id"])
    elif kind == "instructions":
        repository.reorder(rows[0]["phase_id"], [
            (rows[0]["id"], rows[1]["step_num"]), (rows[1]["id"], rows[0]["step_num"]),
            *((row["id"], row["step_num"]) for row in rows[2:]),
        ])
    else:
        # These two repositories order by id; swap content without violating uniqueness.
        repository.update(rows[0]["id"], {"description": "temporary synthetic order swap"})
        repository.update(rows[1]["id"], {"description": rows[0]["description"]})
        repository.update(rows[0]["id"], {"description": rows[1]["description"]})
    uow.session.flush()
    before = all_rows(uow)
    with pytest.raises(ValueError):
        catalog.observe_installation(uow)
    assert all_rows(uow) == before


def test_batched_catalog_sees_committed_drift_in_next_uow(installed):
    uow, original = installed
    assert catalog.observe_installation(uow) == original
    uow.commit()
    with SAUnitOfWork() as writer:
        phase_id = int(original.bindings[0].modes[0].phase_ids[0])
        row = writer.phase_instructions.list(phase_id)[0]
        writer.phase_instructions.update(row["id"], {"description": "synthetic committed drift"})
    with SAUnitOfWork() as reader:
        with pytest.raises(ValueError):
            catalog.observe_installation(reader)
