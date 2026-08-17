from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from project_workflow.config import get_settings
from project_workflow.wizard.workfile import WorkfileError, create_workfile, expected_workfile, load_workfile


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_WORK_ROOT", str(tmp_path))
    get_settings.cache_clear()
    value = MagicMock()
    value.task_key = "TASK-42"
    value.current_phase = "F01"
    value.task = {
        "id": 7,
        "task_key": "TASK-42",
        "title": "Build feature",
        "description": "Expected result",
    }
    value._get_current_phase_obj.return_value = SimpleNamespace(id=11, code="F01")
    value.db.get_supervisor_runs.return_value = []
    value.get_full_context.return_value = {
        "completed_count": 2,
        "total_phases": 60,
        "recent_verdicts": [{"phase_code": "C08", "verdict": "PASS"}],
        "current_contract": {
            "instructions": ["Read the task", "Write the result"],
            "required_checks": ["Task is understood"],
            "required_evidence": ["Task link"],
        },
    }
    yield value
    get_settings.cache_clear()


def test_create_workfile_once_and_preserve_agent_edits(engine):
    path = create_workfile(engine)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert path.name == "F01-001.yaml"
    assert document["task"] == "TASK-42"
    assert document["progress"] == {"completed": 2, "total": 60}
    assert document["instructions"][0]["done"] is False

    document["summary"] = "Agent edit"
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert create_workfile(engine) == path
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["summary"] == "Agent edit"


def test_new_attempt_uses_a_new_file(engine):
    first, attempt = expected_workfile(engine)
    assert attempt == 1
    engine.db.get_supervisor_runs.return_value = [{"phase_id": 11}]
    second, attempt = expected_workfile(engine)
    assert attempt == 2
    assert second != first


def test_load_workfile_validates_exact_contract(engine):
    path = create_workfile(engine)
    assert "Task is understood" in load_workfile(engine, path)

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["checks"] = []
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    with pytest.raises(WorkfileError, match="every current contract item"):
        load_workfile(engine, path)


def test_load_workfile_rejects_stale_or_foreign_path(engine, tmp_path):
    path = create_workfile(engine)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["phase"] = "F02"
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    with pytest.raises(WorkfileError, match="phase is stale"):
        load_workfile(engine, path)

    foreign = tmp_path / "other.yaml"
    foreign.write_text("task: TASK-42", encoding="utf-8")
    with pytest.raises(WorkfileError, match="expected current workfile"):
        load_workfile(engine, foreign)


def test_load_workfile_rejects_unknown_status(engine):
    path = create_workfile(engine)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["checks"][0]["status"] = "done-ish"
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")

    with pytest.raises(WorkfileError, match="status has an invalid value"):
        load_workfile(engine, path)
