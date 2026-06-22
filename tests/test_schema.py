"""Tests for schema.py bootstrap and seed persistence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_workflow import config
from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db import WorkflowDB
from project_workflow.wizard.models import Phase


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    import project_workflow.infrastructure.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "workflow.db")
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "workflow.db")
    db = WorkflowDB()
    db.init()
    return db


class TestEnsurePhaseCatalog:
    def test_default_workflow_seeded(self, fresh_db):
        schema.ensure_phase_catalog(fresh_db)
        phases = fresh_db.get_phases()
        codes = [p["code"] for p in phases]
        assert len(codes) > 0
        for code in config.PHASE_ORDER:
            assert code in codes

    def test_idempotent_rerun(self, fresh_db):
        schema.ensure_phase_catalog(fresh_db)
        first_count = len(fresh_db.get_phases())
        schema.ensure_phase_catalog(fresh_db)
        assert len(fresh_db.get_phases()) == first_count


class TestSeedPersistence:
    def test_persist_phase_update_to_seed(self, fresh_db, tmp_path, monkeypatch):
        # Point seed.json to a temp file
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
        fresh_db.sync_phase_catalog(
            [{"code": "1", "name": "One", "next_recommendation": "Old"}],
            ["1"],
            {},
        )
        phase = fresh_db.get_phase_by_code("1")
        # Phase object must reflect update for persist to write new value
        fresh_db.update_phase(
            phase["id"],
            {"next_recommendation": "New"},
        )
        schema.persist_phase_update_to_seed(
            fresh_db,
            phase["id"],
            {"next_recommendation": "New"},
        )
        data = json.loads(seed_path.read_text())
        assert data[0]["next_recommendation"] == "New"


class TestLoadPhases:
    def test_load_phases_from_db(self, fresh_db):
        schema.ensure_phase_catalog(fresh_db)
        phases = schema.load_phases_from_db(fresh_db)
        assert isinstance(phases, list)
        assert isinstance(phases[0], Phase)

    def test_get_phase_from_db(self, fresh_db):
        schema.ensure_phase_catalog(fresh_db)
        phase = schema.get_phase_from_db(fresh_db, config.PHASE_ORDER[0])
        assert phase is not None
        assert phase.code == config.PHASE_ORDER[0]

    def test_get_phase_from_db_missing(self, fresh_db):
        schema.ensure_phase_catalog(fresh_db)
        assert schema.get_phase_from_db(fresh_db, "not-real") is None


class TestGenerateProgressJson:
    def test_progress_json_structure(self):
        raw = schema.generate_progress_json("TASK-1", "123", "Title", "Sprint-1")
        data = json.loads(raw)
        assert data["task_key"] == "TASK-1"
        assert data["version"] == "1.0.0"
        assert len(data["phases"]) > 0


class TestParseOldYaml:
    def test_parse_old_yaml_item(self):
        item = {
            "code": "9",
            "name": "Retro",
            "description": "desc",
            "checks": [{"description": "c1"}],
            "evidence": [{"item": "ev1"}],
            "instructions": [{"step": "i1"}],
            "delegate": {
                "agent": "a1",
                "prompt_template": "p1",
                "context": ["x"],
                "toolsets": ["t1"],
            },
        }
        phase = schema._parse_old_yaml(item)
        assert phase.code == "9"
        assert phase.checks[0].description == "c1"
        assert phase.evidence[0].item == "ev1"
        assert phase.instructions[0].step == "i1"
        assert phase.delegate.agent == "a1"


class TestReadSeedItems:
    def test_read_seed_items(self):
        items = schema._read_seed_items()
        assert len(items) == len(config.PHASE_ORDER)

    def test_read_seed_items_from_path_missing(self):
        assert schema._read_seed_items_from_path(Path("/nonexistent/seed.json")) == []

    def test_read_seed_items_with_allowed_codes(self, tmp_path):
        seed_path = tmp_path / "seed.json"
        seed_path.write_text(json.dumps([
            {"code": "1", "name": "One"},
            {"code": "2", "name": "Two"},
        ], ensure_ascii=False))
        items = schema._read_seed_items_from_path(seed_path, allowed_codes=["2"])
        assert len(items) == 1
        assert items[0]["code"] == "2"


class TestSerializeHelpers:
    def test_serialize_seed_instructions(self):
        rows = schema._serialize_seed_instructions([{"description": "D", "skills": ["s1"]}])
        assert rows[0]["description"] == "D"
        assert rows[0]["skills"] == ["s1"]

    def test_serialize_seed_checks(self):
        rows = schema._serialize_seed_checks([{"description": "C"}])
        assert rows[0]["description"] == "C"

    def test_serialize_seed_evidence(self):
        rows = schema._serialize_seed_evidence([{"description": "E"}])
        assert rows[0]["description"] == "E"


class TestGetPhase:
    def test_get_phase_returns_phase(self, tmp_path, monkeypatch):
        import project_workflow.infrastructure.db as db_module
        monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "workflow.db")
        monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "workflow.db")
        phase = schema.get_phase("1")
        assert phase is not None
        assert phase.code == "1"

    def test_get_phase_order(self, tmp_path, monkeypatch):
        import project_workflow.infrastructure.db as db_module
        monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "workflow.db")
        monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "workflow.db")
        order = schema.get_phase_order()
        assert len(order) > 0
        assert order[0] == config.PHASE_ORDER[0]


class TestLoadPhasesTopLevel:
    def test_load_phases(self, tmp_path, monkeypatch):
        import project_workflow.infrastructure.db as db_module
        monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "workflow.db")
        monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "workflow.db")
        phases = schema.load_phases()
        assert len(phases) > 0
