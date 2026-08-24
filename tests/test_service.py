"""Tests for service.py — PhaseService."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow.application.phase_service import PhaseService
from project_workflow.domain.exceptions import NotFoundError
from project_workflow.domain.phase_grouping import group_parallel_phases
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._db_helpers import phase_by_code, prepare_sqlite_uow


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'workflow.db'}")
    uow = SAUnitOfWork(f"sqlite:///{tmp_path / 'workflow.db'}")
    prepare_sqlite_uow(uow)
    return uow


@pytest.fixture
def svc(fresh_db):
    return PhaseService(fresh_db)


class TestNormalizeSkills:
    def test_normalize_skills_list(self, svc):
        assert svc.normalize_skills(["a", "b"]) == ["a", "b"]

    def test_normalize_skills_empty(self, svc):
        assert svc.normalize_skills(None) == []
        assert svc.normalize_skills([]) == []

    @pytest.mark.parametrize("value", ['["a", "b"]', "", 42, ["ok", 1]])
    def test_rejects_noncanonical_skills(self, svc, value):
        with pytest.raises(TypeError, match="skills"):
            svc.normalize_skills(value)


class TestSaveInstructions:
    def test_save_and_get_phase_detail(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "2.REQUIREMENTS")
        ids = svc.save_instructions(
            phase.id,
            [
                {"description": "Run tests", "execution_type": "sync", "skills": ["testing"]},
            ],
        )
        assert len(ids) == 1
        detail = svc.get_phase_detail(phase.id)
        assert detail["instructions"][0]["description"] == "Run tests"
        assert detail["instructions"][0]["skills"] == ["testing"]

    def test_invalid_phase_raises(self, svc):
        with pytest.raises(NotFoundError, match="Phase 9999 not found"):
            svc.save_instructions(9999, [{"description": "x"}])

    def test_deferred_save_does_not_commit(self, svc, fresh_db, monkeypatch):
        phase = phase_by_code(fresh_db, "2.REQUIREMENTS")
        commits = 0

        def count_commit():
            nonlocal commits
            commits += 1

        monkeypatch.setattr(fresh_db, "commit", count_commit)
        svc.save_instructions(phase.id, [{"description": "Deferred"}], commit=False)
        assert commits == 0


class TestSaveChecks:
    def test_invalid_phase_raises(self, svc):
        with pytest.raises(NotFoundError, match="Phase 9999 not found"):
            svc.save_checks(9999, [{"description": "x"}])

    def test_save_checks(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "2.REQUIREMENTS")
        ids = svc.save_checks(phase.id, [{"description": "Check A"}])
        assert len(ids) == 1
        detail = svc.get_phase_detail(phase.id)
        assert detail["checks"][0]["description"] == "Check A"

    def test_save_checks_replaces_previous(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "2.REQUIREMENTS")
        svc.save_checks(phase.id, [{"description": "Old"}])
        svc.save_checks(phase.id, [{"description": "New"}])
        detail = svc.get_phase_detail(phase.id)
        assert len(detail["checks"]) == 1
        assert detail["checks"][0]["description"] == "New"


class TestSaveEvidence:
    def test_invalid_phase_raises(self, svc):
        with pytest.raises(NotFoundError, match="Phase 9999 not found"):
            svc.save_evidence(9999, [{"description": "x"}])

    def test_save_evidence(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "2.REQUIREMENTS")
        ids = svc.save_evidence(phase.id, [{"description": "Screenshot"}])
        assert len(ids) == 1
        detail = svc.get_phase_detail(phase.id)
        assert detail["evidence"][0]["description"] == "Screenshot"


class TestUpdatePhase:
    def test_update_phase_metadata(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "2.REQUIREMENTS")
        svc.update_phase(phase.id, {"next_recommendation": "Updated"})
        detail = svc.get_phase_detail(phase.id)
        assert detail["next_recommendation"] == "Updated"

    def test_get_phase_detail_empty(self, svc):
        assert svc.get_phase_detail(9999) == {}

    @staticmethod
    def _groups(fresh_db):
        phases = list(fresh_db.phases.list(workflow_id=1))
        return [
            [phase.code for phase in group]
            for group in group_parallel_phases(
                phases,
                code_of=lambda phase: phase.code,
                execution_type_of=lambda phase: phase.execution_type,
                parallel_with_of=lambda phase: phase.parallel_with,
            )
        ]

    def test_sync_phase_becomes_explicitly_isolated_parallel(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "7.PLAN_GATE")

        svc.update_phase(phase.id, {"execution_type": "parallel"})

        updated = phase_by_code(fresh_db, "7.PLAN_GATE")
        assert updated.parallel_with is None
        assert ["7.PLAN_GATE"] in self._groups(fresh_db)

    def test_explicit_partner_joins_contiguous_parallel_component(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "7.PLAN_GATE")

        svc.update_phase(
            phase.id,
            {"execution_type": "parallel", "parallel_with": "6.TEST_PLAN"},
        )

        assert phase_by_code(fresh_db, "7.PLAN_GATE").parallel_with == "6.TEST_PLAN"
        assert ["6.SOLUTION", "6.TEST_PLAN", "7.PLAN_GATE"] in self._groups(fresh_db)

    def test_parallel_to_sync_clears_outgoing_and_incoming_links(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "6.SOLUTION")

        svc.update_phase(phase.id, {"execution_type": "sync"})
        assert phase_by_code(fresh_db, "6.SOLUTION").parallel_with is None
        assert phase_by_code(fresh_db, "6.TEST_PLAN").parallel_with is None
