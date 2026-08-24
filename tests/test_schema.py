"""Tests for schema.py bootstrap and seed persistence."""

from __future__ import annotations

import json

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow.infrastructure.db.schema import (
    _SeedPhase,
    ensure_phase_catalog,
    load_phases_from_db,
    load_phases_from_seed,
)
from project_workflow.infrastructure.db.session import ensure_schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.supervisor.models import Phase
from tests._db_helpers import phase_by_code


def _supervisor_phase_by_code(uow, code: str, workflow_id: int):
    return next((phase for phase in load_phases_from_db(uow, workflow_id) if phase.code == code), None)


def _default_workflow_id(uow: SAUnitOfWork) -> int:
    workflow = uow.workflows.get_default()
    assert workflow is not None and workflow.id is not None
    return workflow.id


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "workflow.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    uow = SAUnitOfWork(f"sqlite:///{db_path}")
    ensure_schema(uow.session.get_bind())
    return uow


class TestEnsurePhaseCatalog:
    def test_default_workflow_seeded(self, fresh_db):
        ensure_phase_catalog(fresh_db)
        phases = load_phases_from_db(fresh_db)
        codes = [p.code for p in phases]
        assert len(codes) > 0
        for code in (phase.code for phase in load_phases_from_seed()):
            assert code in codes
        assert all(phase.delegate for phase in phases)
        assert all(
            phase.delegate.hermes_profile or phase.delegate.agent == "codex-operator"
            for phase in phases
            if phase.delegate
        )
        assert all(phase.is_delegated for phase in phases)

    def test_idempotent_rerun(self, fresh_db):
        ensure_phase_catalog(fresh_db)
        first_count = len(load_phases_from_db(fresh_db))
        ensure_phase_catalog(fresh_db)
        assert len(load_phases_from_db(fresh_db)) == first_count

    def test_existing_catalog_is_not_overwritten_after_restart(self, fresh_db, tmp_path):
        seed_path = tmp_path / "seed.json"
        seed_path.write_text(
            json.dumps([{"phase_order": 1, "code": "1", "name": "Seed name"}]),
            encoding="utf-8",
        )
        ensure_phase_catalog(fresh_db, seed_path=seed_path)
        phase = phase_by_code(fresh_db, "1")
        fresh_db.phases.update(phase.id, {"name": "Edited in UI"})
        fresh_db.commit()

        seed_path.write_text(
            json.dumps([{"phase_order": 1, "code": "1", "name": "Changed seed"}]),
            encoding="utf-8",
        )
        ensure_phase_catalog(fresh_db, seed_path=seed_path)

        assert phase_by_code(fresh_db, "1").name == "Edited in UI"


class TestGenerateProgressJson:
    def test_progress_json_structure(self, fresh_db, tmp_path):
        seed_path = tmp_path / "seed.json"
        seed_path.write_text(
            json.dumps(
                [
                    {
                        "phase_order": 1,
                        "code": "custom.intake",
                        "name": "Custom Intake",
                        "instructions": [{"description": "Step 1"}],
                        "checks": [{"description": "Check 1"}],
                        "evidence": [{"description": "Evidence 1"}],
                    }
                ],
                ensure_ascii=False,
            )
        )
        ensure_phase_catalog(fresh_db, seed_path=seed_path)
        phase = _supervisor_phase_by_code(fresh_db, "custom.intake", _default_workflow_id(fresh_db))
        assert phase is not None
        assert phase.name == "Custom Intake"
        assert len(phase.instructions) >= 1


class TestParseSeedItem:
    def test_parse_seed_item(self, fresh_db):
        from project_workflow.infrastructure.db.schema import _phase_item_to_supervisor

        raw = {
            "phase_order": 1,
            "code": "1",
            "name": "One",
            "description": "Desc",
            "instructions": [{"description": "Do it", "execution_type": "sync"}],
            "checks": [{"description": "Check it"}],
            "evidence": [{"description": "Show it"}],
        }
        phase = _phase_item_to_supervisor(_SeedPhase.model_validate(raw))
        assert isinstance(phase, Phase)
        assert phase.code == "1"


class TestReadSeedItems:
    def test_read_seed_items(self, fresh_db, tmp_path):
        seed_path = tmp_path / "seed.json"
        seed_path.write_text(
            json.dumps([{"phase_order": 1, "code": "1", "name": "One"}], ensure_ascii=False)
        )
        items = load_phases_from_seed(seed_path)
        assert len(items) == 1
        assert items[0].code == "1"

    def test_read_seed_items_from_path_missing(self, fresh_db, tmp_path):
        seed_path = tmp_path / "missing.json"
        with pytest.raises(FileNotFoundError):
            load_phases_from_seed(seed_path)

    def test_read_seed_items_with_allowed_codes(self, fresh_db, tmp_path):
        seed_path = tmp_path / "seed.json"
        seed_path.write_text(
            json.dumps(
                [
                    {"phase_order": 1, "code": "1", "name": "One"},
                    {"phase_order": 2, "code": "2", "name": "Two"},
                ],
                ensure_ascii=False,
            )
        )
        items = load_phases_from_seed(seed_path)
        codes = {p.code for p in items}
        assert codes == {"1", "2"}


class TestGetPhase:
    def test_get_phase_returns_phase(self, fresh_db):
        ensure_phase_catalog(fresh_db)
        phase = _supervisor_phase_by_code(fresh_db, "1.INTAKE", _default_workflow_id(fresh_db))
        assert phase is not None
        assert phase.code == "1.INTAKE"

    def test_get_phase_order(self, fresh_db):
        ensure_phase_catalog(fresh_db)
        phase = _supervisor_phase_by_code(fresh_db, "2.REQUIREMENTS", _default_workflow_id(fresh_db))
        assert phase is not None
        assert phase.code == "2.REQUIREMENTS"


class TestLoadPhases:
    def test_load_phases_from_db(self, fresh_db):
        ensure_phase_catalog(fresh_db)
        phases = load_phases_from_db(fresh_db)
        assert len(phases) > 0

    def test_load_phase_by_scoped_code(self, fresh_db):
        ensure_phase_catalog(fresh_db)
        phase = _supervisor_phase_by_code(fresh_db, "1.INTAKE", _default_workflow_id(fresh_db))
        assert phase is not None
        assert phase.code == "1.INTAKE"

    def test_load_phase_by_scoped_code_missing(self, fresh_db):
        ensure_phase_catalog(fresh_db)
        phase = _supervisor_phase_by_code(fresh_db, "nonexistent", _default_workflow_id(fresh_db))
        assert phase is None
