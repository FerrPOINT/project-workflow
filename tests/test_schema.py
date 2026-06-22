"""Tests for schema.py bootstrap and seed persistence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_workflow import config
from project_workflow.infrastructure.db.schema import (
    ensure_phase_catalog,
    get_phase_from_db,
    load_phases_from_db,
    load_phases_from_seed,
    persist_phase_update_to_seed,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.wizard.models import Phase


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "workflow.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    uow = SAUnitOfWork(str(db_path))
    uow.create_all()
    return uow


class TestEnsurePhaseCatalog:
    def test_default_workflow_seeded(self, fresh_db):
        ensure_phase_catalog(fresh_db)
        phases = load_phases_from_db(fresh_db)
        codes = [p.code for p in phases]
        assert len(codes) > 0
        for code in config.PHASE_ORDER:
            assert code in codes

    def test_idempotent_rerun(self, fresh_db):
        ensure_phase_catalog(fresh_db)
        first_count = len(load_phases_from_db(fresh_db))
        ensure_phase_catalog(fresh_db)
        assert len(load_phases_from_db(fresh_db)) == first_count


class TestSeedPersistence:
    def test_persist_phase_update_to_seed(self, fresh_db, tmp_path, monkeypatch):
        seed_path = tmp_path / "seed.json"
        seed_path.write_text(json.dumps([{
            "code": "1",
            "name": "One",
            "next_recommendation": "Old",
            "instructions": [],
            "checks": [],
            "evidence": [],
        }], ensure_ascii=False))
        monkeypatch.setattr(config, "SEED_PATH", seed_path)
        ensure_phase_catalog(fresh_db, seed_path=seed_path)
        phase = get_phase_from_db(fresh_db, "1")
        persist_phase_update_to_seed(fresh_db, "1", {"next_recommendation": "New"}, seed_path=seed_path)
        reloaded = json.loads(seed_path.read_text(encoding="utf-8"))
        assert reloaded[0]["next_recommendation"] == "New"


class TestGenerateProgressJson:
    def test_progress_json_structure(self, fresh_db, tmp_path, monkeypatch):
        seed_path = tmp_path / "seed.json"
        seed_path.write_text(json.dumps([{
            "code": "-1",
            "name": "Task Intake",
            "instructions": [{"description": "Step 1"}],
            "checks": [{"description": "Check 1"}],
            "evidence": [{"description": "Evidence 1"}],
        }], ensure_ascii=False))
        monkeypatch.setattr(config, "SEED_PATH", seed_path)
        ensure_phase_catalog(fresh_db, seed_path=seed_path)
        phase = get_phase_from_db(fresh_db, "-1")
        assert phase is not None
        assert phase.name == "Task Intake"
        assert len(phase.instructions) >= 1


class TestParseOldYaml:
    def test_parse_old_yaml_item(self, fresh_db):
        from project_workflow.infrastructure.db.schema import _phase_item_to_wizard
        raw = {
            "code": "1",
            "name": "One",
            "description": "Desc",
            "instructions": [{"step": "Do it", "execution_type": "sync"}],
            "checks": [{"description": "Check it"}],
            "evidence": [{"description": "Show it"}],
        }
        phase = _phase_item_to_wizard(raw)
        assert isinstance(phase, Phase)
        assert phase.code == "1"


class TestReadSeedItems:
    def test_read_seed_items(self, fresh_db, tmp_path):
        seed_path = tmp_path / "seed.json"
        seed_path.write_text(json.dumps([{"code": "1", "name": "One"}], ensure_ascii=False))
        items = load_phases_from_seed(seed_path)
        assert len(items) == 1
        assert items[0].code == "1"

    def test_read_seed_items_from_path_missing(self, fresh_db, tmp_path):
        seed_path = tmp_path / "missing.json"
        items = load_phases_from_seed(seed_path)
        assert items == []

    def test_read_seed_items_with_allowed_codes(self, fresh_db, tmp_path):
        seed_path = tmp_path / "seed.json"
        seed_path.write_text(json.dumps([
            {"code": "1", "name": "One"},
            {"code": "2", "name": "Two"},
        ], ensure_ascii=False))
        items = load_phases_from_seed(seed_path)
        codes = {p.code for p in items}
        assert codes == {"1", "2"}


class TestSerializeHelpers:
    def test_serialize_seed_instructions(self):
        from project_workflow.infrastructure.db.schema import _phase_to_seed_dict
        from project_workflow.wizard.models import Phase, PhaseInstruction
        phase = Phase(
            code="1",
            name="One",
            instructions=[PhaseInstruction(step="Do it")],
        )
        data = _phase_to_seed_dict(phase)
        assert data["instructions"] == [{"step": "Do it", "execution_type": "sync", "skills": [], "example": None}]

    def test_serialize_seed_checks(self):
        from project_workflow.infrastructure.db.schema import _phase_to_seed_dict
        from project_workflow.wizard.models import Phase, PhaseCheck
        phase = Phase(code="1", name="One", checks=[PhaseCheck(description="Check it")])
        data = _phase_to_seed_dict(phase)
        assert data["checks"] == [{"description": "Check it"}]

    def test_serialize_seed_evidence(self):
        from project_workflow.infrastructure.db.schema import _phase_to_seed_dict
        from project_workflow.wizard.models import Phase, PhaseEvidence
        phase = Phase(code="1", name="One", evidence=[PhaseEvidence(item="Show it")])
        data = _phase_to_seed_dict(phase)
        assert data["evidence"] == [{"description": "Show it"}]


class TestGetPhase:
    def test_get_phase_returns_phase(self, fresh_db):
        ensure_phase_catalog(fresh_db)
        phase = get_phase_from_db(fresh_db, "-1")
        assert phase is not None
        assert phase.code == "-1"

    def test_get_phase_order(self, fresh_db):
        ensure_phase_catalog(fresh_db)
        phase = get_phase_from_db(fresh_db, "0.0a")
        assert phase is not None
        assert phase.code == "0.0a"


class TestLoadPhases:
    def test_load_phases_from_db(self, fresh_db):
        ensure_phase_catalog(fresh_db)
        phases = load_phases_from_db(fresh_db)
        assert len(phases) > 0

    def test_get_phase_from_db(self, fresh_db):
        ensure_phase_catalog(fresh_db)
        phase = get_phase_from_db(fresh_db, "-1")
        assert phase is not None
        assert phase.code == "-1"

    def test_get_phase_from_db_missing(self, fresh_db):
        ensure_phase_catalog(fresh_db)
        phase = get_phase_from_db(fresh_db, "nonexistent")
        assert phase is None
