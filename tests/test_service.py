"""Tests for service.py — PhaseService."""
from __future__ import annotations

import json

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow.infrastructure.db.schema import ensure_phase_catalog
from project_workflow.infrastructure.db.phase_service import PhaseService
from project_workflow.infrastructure.db.uow import SAUnitOfWork


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'workflow.db'}")
    uow = SAUnitOfWork(str(tmp_path / "workflow.db"))
    uow.create_all()
    ensure_phase_catalog(uow)
    return uow


@pytest.fixture
def svc(fresh_db):
    return PhaseService(fresh_db)


class TestNormalizeAndSerializeSkills:
    def test_normalize_skills_list(self, svc):
        assert svc.normalize_skills(["a", "b"]) == ["a", "b"]

    def test_normalize_skills_json_string(self, svc):
        assert svc.normalize_skills('["a", "b"]') == ["a", "b"]

    def test_normalize_skills_empty(self, svc):
        assert svc.normalize_skills(None) == []
        assert svc.normalize_skills("") == []
        assert svc.normalize_skills([]) == []

    def test_serialize_skills(self, svc):
        assert svc.serialize_skills(["a"]) == json.dumps(["a"], ensure_ascii=False)
        assert svc.serialize_skills([]) is None


class TestSaveInstructions:
    def test_save_and_get_phase_detail(self, svc, fresh_db):
        phase = fresh_db.phases.get_by_code("1")
        ids = svc.save_instructions(phase.id, [
            {"description": "Run tests", "execution_type": "sync", "skills": ["testing"]},
        ])
        assert len(ids) == 1
        detail = svc.get_phase_detail(phase.id)
        assert detail["instructions"][0]["description"] == "Run tests"
        assert detail["instructions"][0]["skills"] == ["testing"]

    def test_invalid_phase_raises(self, svc):
        with pytest.raises(ValueError, match="Phase not found"):
            svc.save_instructions(9999, [{"description": "x"}])


class TestSaveChecks:
    def test_invalid_phase_raises(self, svc):
        with pytest.raises(ValueError, match="Phase not found"):
            svc.save_checks(9999, [{"description": "x"}])

    def test_save_checks(self, svc, fresh_db):
        phase = fresh_db.phases.get_by_code("1")
        ids = svc.save_checks(phase.id, [{"description": "Check A"}])
        assert len(ids) == 1
        detail = svc.get_phase_detail(phase.id)
        assert detail["checks"][0]["description"] == "Check A"

    def test_save_checks_replaces_previous(self, svc, fresh_db):
        phase = fresh_db.phases.get_by_code("1")
        svc.save_checks(phase.id, [{"description": "Old"}])
        svc.save_checks(phase.id, [{"description": "New"}])
        detail = svc.get_phase_detail(phase.id)
        assert len(detail["checks"]) == 1
        assert detail["checks"][0]["description"] == "New"


class TestSaveEvidence:
    def test_invalid_phase_raises(self, svc):
        with pytest.raises(ValueError, match="Phase not found"):
            svc.save_evidence(9999, [{"description": "x"}])

    def test_save_evidence(self, svc, fresh_db):
        phase = fresh_db.phases.get_by_code("1")
        ids = svc.save_evidence(phase.id, [{"description": "Screenshot"}])
        assert len(ids) == 1
        detail = svc.get_phase_detail(phase.id)
        assert detail["evidence"][0]["description"] == "Screenshot"


class TestGetAllPhases:
    def test_get_all_phases(self, svc, fresh_db):
        phases = svc.get_all_phases()
        assert len(phases) == len(fresh_db.phases.list())
        assert all("instructions" in p for p in phases)


class TestUpdatePhase:
    def test_update_phase_metadata(self, svc, fresh_db):
        phase = fresh_db.phases.get_by_code("1")
        svc.update_phase(phase.id, {"next_recommendation": "Updated"})
        detail = svc.get_phase_detail(phase.id)
        assert detail["next_recommendation"] == "Updated"

    def test_get_phase_detail_empty(self, svc):
        assert svc.get_phase_detail(9999) == {}


class TestNormalizeSkills:
    def test_normalize_skills_integer(self, svc):
        """Non-list, non-str, non-none input returns []."""
        assert svc.normalize_skills(42) == []

    def test_parse_skills_bad_json(self, svc):
        """Non-JSON string returns empty list."""
        assert PhaseService.parse_skills("not json") == []

    def test_parse_skills_not_list_json(self, svc):
        """JSON that parses to dict instead of list returns []."""
        assert PhaseService.parse_skills('{"a": 1}') == []

    def test_serialize_skills_none(self, svc):
        assert svc.serialize_skills(None) is None

    def test_serialize_skills_empty(self, svc):
        assert svc.serialize_skills([]) is None
