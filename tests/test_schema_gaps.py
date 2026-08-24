"""Strict JSON catalog and scoped DB lookup regressions."""

from __future__ import annotations

from pathlib import Path

import pytest

from project_workflow import config
from project_workflow.infrastructure.db.schema import (
    _load_seed,
    _phase_item_to_supervisor,
    ensure_phase_catalog,
    get_phase_from_db,
    load_phases_from_db,
    load_phases_from_seed,
)
from project_workflow.infrastructure.db.session import ensure_schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork

pytestmark = [pytest.mark.ui]


def _seed_path(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[1] / "project_workflow" / "references" / "seed.json"
    dst = tmp_path / "seed.json"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dst


def _bootstrapped_uow(tmp_path: Path, monkeypatch) -> SAUnitOfWork:
    uow = SAUnitOfWork(f"sqlite:///{tmp_path / 'catalog.db'}")
    ensure_schema(uow.session.get_bind())
    monkeypatch.setattr(config, "SEED_PATH", _seed_path(tmp_path))
    ensure_phase_catalog(uow)
    uow.commit()
    return uow


def test_unknown_workflow_is_empty(tmp_path, monkeypatch):
    uow = _bootstrapped_uow(tmp_path, monkeypatch)
    assert load_phases_from_db(uow, workflow_id=999999) == []
    uow.close()


def test_phase_lookup_is_scoped_to_workflow(tmp_path, monkeypatch):
    uow = _bootstrapped_uow(tmp_path, monkeypatch)
    default = uow.workflows.get_default()
    assert default is not None and default.id is not None
    other_id = uow.workflows.create({"name": "Other", "is_default": 0})
    uow.phases.create(
        {"workflow_id": other_id, "code": "1.INTAKE", "name": "Other phase", "phase_order": 1}
    )
    uow.commit()

    default_phase = get_phase_from_db(uow, "1.INTAKE", default.id)
    other_phase = get_phase_from_db(uow, "1.INTAKE", other_id)
    assert default_phase is not None and default_phase.name != "Other phase"
    assert other_phase is not None and other_phase.name == "Other phase"
    uow.close()


@pytest.mark.parametrize(
    ("name", "contents", "message"),
    [
        ("seed.yaml", "- code: old", "must be JSON"),
        ("malformed.json", "{", "Malformed seed catalog"),
        ("object.json", '{"code": "bad"}', "root must be a list"),
        ("items.json", '["bad"]', "item must be an object"),
    ],
)
def test_invalid_seed_is_rejected(tmp_path, name, contents, message):
    path = tmp_path / name
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        _load_seed(path)


def test_missing_seed_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError, match="Seed catalog not found"):
        _load_seed(tmp_path / "missing.json")


def test_load_packaged_json_seed(tmp_path):
    assert load_phases_from_seed(_seed_path(tmp_path))


def test_phase_item_to_supervisor_with_delegate():
    phase = _phase_item_to_supervisor(
        {
            "code": "DLG",
            "name": "Delegate",
            "delegate": {
                "agent": "reviewer",
                "toolsets": ["ts1"],
                "timeout_min": 5,
                "max_cycles": 2,
            },
        }
    )
    assert phase.delegate is not None
    assert phase.delegate.agent == "reviewer"
    assert phase.delegate.toolsets == ["ts1"]


def test_catalog_bootstrap_is_database_idempotent(tmp_path, monkeypatch):
    uow = _bootstrapped_uow(tmp_path, monkeypatch)
    counts = (len(uow.workflows.list()), len(uow.phases.list()), len(uow.agents.list()))
    ensure_phase_catalog(uow)
    uow.commit()
    assert counts == (len(uow.workflows.list()), len(uow.phases.list()), len(uow.agents.list()))
    uow.close()
