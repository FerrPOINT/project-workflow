"""Tests for service.py — PhaseService."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow.application.phase_service import PhaseService
from project_workflow.domain.exceptions import ConflictError, NotFoundError
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


class TestPhaseAggregate:
    def test_save_and_get_phase_detail(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "2.REQUIREMENTS")
        ids = svc.update_phase_detail(
            phase.id,
            {
                "instructions": [
                    {"id": None, "description": "Run tests", "execution_type": "sync", "skills": ["testing"]},
                ]
            },
        )
        assert len(ids["instructions"]) == 1
        detail = svc.get_phase_detail(phase.id)
        assert detail["instructions"][0]["description"] == "Run tests"
        assert detail["instructions"][0]["skills"] == ["testing"]

    def test_invalid_phase_raises(self, svc):
        with pytest.raises(NotFoundError, match="Фаза 9999 не найдена"):
            svc.update_phase_detail(9999, {"instructions": [{"id": None, "description": "x"}]})

    def test_save_checks(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "2.REQUIREMENTS")
        ids = svc.update_phase_detail(phase.id, {"checks": [{"id": None, "description": "Check A"}]})
        assert len(ids["checks"]) == 1
        detail = svc.get_phase_detail(phase.id)
        assert detail["checks"][0]["description"] == "Check A"

    def test_save_checks_replaces_previous(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "2.REQUIREMENTS")
        first = svc.update_phase_detail(phase.id, {"checks": [{"id": None, "description": "Old"}]})
        svc.update_phase_detail(
            phase.id,
            {"checks": [{"id": first["checks"][0], "description": "New"}]},
        )
        detail = svc.get_phase_detail(phase.id)
        assert len(detail["checks"]) == 1
        assert detail["checks"][0]["description"] == "New"

    def test_save_evidence(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "2.REQUIREMENTS")
        ids = svc.update_phase_detail(phase.id, {"evidence": [{"id": None, "description": "Screenshot"}]})
        assert len(ids["evidence"]) == 1
        detail = svc.get_phase_detail(phase.id)
        assert detail["evidence"][0]["description"] == "Screenshot"

    def test_noop_save_preserves_all_nested_ids(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "2.REQUIREMENTS")
        before = svc.get_phase_detail(phase.id)
        payload = {
            "instructions": [
                {
                    "id": item["id"],
                    "description": item["description"],
                    "execution_type": item["execution_type"],
                    "skills": item["skills"],
                }
                for item in before["instructions"]
            ],
            "checks": [
                {"id": item["id"], "description": item["description"]}
                for item in before["checks"]
            ],
            "evidence": [
                {"id": item["id"], "description": item["description"]}
                for item in before["evidence"]
            ],
        }

        result = svc.update_phase_detail(phase.id, payload)
        after = svc.get_phase_detail(phase.id)

        assert result == {
            "instructions": [item["id"] for item in before["instructions"]],
            "checks": [item["id"] for item in before["checks"]],
            "evidence": [item["id"] for item in before["evidence"]],
        }
        assert after == before

    def test_edit_add_delete_and_reorder_preserve_retained_instruction_ids(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "2.REQUIREMENTS")
        before = svc.get_phase_detail(phase.id)["instructions"]
        assert len(before) >= 2
        retained_id = before[1]["id"]

        result = svc.update_phase_detail(
            phase.id,
            {
                "instructions": [
                    {
                        "id": retained_id,
                        "description": "Изменённая инструкция",
                        "execution_type": "sync",
                        "skills": [],
                    },
                    {
                        "id": None,
                        "description": "Новая инструкция",
                        "execution_type": "parallel",
                        "skills": ["testing"],
                    },
                ]
            },
        )
        after = svc.get_phase_detail(phase.id)["instructions"]

        assert result["instructions"][0] == retained_id
        assert [item["id"] for item in after] == result["instructions"]
        assert [item["step_num"] for item in after] == [1, 2]
        assert after[0]["description"] == "Изменённая инструкция"
        assert before[0]["id"] not in result["instructions"]

    def test_foreign_nested_id_rolls_back_complete_aggregate(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "2.REQUIREMENTS")
        other = phase_by_code(fresh_db, "3.DOR_GATE")
        before = svc.get_phase_detail(phase.id)
        foreign_check_id = svc.get_phase_detail(other.id)["checks"][0]["id"]

        with pytest.raises(ConflictError, match="не принадлежат фазе"):
            svc.update_phase_detail(
                phase.id,
                {
                    "description": "Не должно сохраниться",
                    "checks": [{"id": foreign_check_id, "description": "Чужая проверка"}],
                },
            )

        assert svc.get_phase_detail(phase.id) == before

    @pytest.mark.parametrize("field", ["checks", "evidence"])
    def test_nested_descriptions_can_swap_without_changing_ids(self, svc, fresh_db, field):
        phase = phase_by_code(fresh_db, "2.REQUIREMENTS")
        before = svc.get_phase_detail(phase.id)[field]
        assert len(before) >= 2
        first, second = before[:2]
        payload = [
            {"id": first["id"], "description": second["description"]},
            {"id": second["id"], "description": first["description"]},
            *[
                {"id": item["id"], "description": item["description"]}
                for item in before[2:]
            ],
        ]

        result = svc.update_phase_detail(phase.id, {field: payload})
        after = svc.get_phase_detail(phase.id)[field]

        assert result[field] == [item["id"] for item in before]
        assert after[0]["description"] == second["description"]
        assert after[1]["description"] == first["description"]


class TestUpdatePhase:
    def test_update_phase_metadata(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "2.REQUIREMENTS")
        svc.update_phase_detail(phase.id, {"description": "Updated"})
        detail = svc.get_phase_detail(phase.id)
        assert detail["description"] == "Updated"

    def test_get_phase_detail_empty(self, svc):
        assert svc.get_phase_detail(9999) == {}

    @staticmethod
    def _groups(fresh_db):
        phases = list(fresh_db.phases.list(workflow_id=1))
        return [
            [phase.code for phase in group]
            for group in group_parallel_phases(
                phases,
                id_of=lambda phase: int(phase.id),
                execution_type_of=lambda phase: phase.execution_type,
                parallel_with_phase_id_of=lambda phase: phase.parallel_with_phase_id,
            )
        ]

    def test_sync_phase_becomes_explicitly_isolated_parallel(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "7.PLAN_GATE")

        svc.update_phase_detail(phase.id, {"execution_type": "parallel"})

        updated = phase_by_code(fresh_db, "7.PLAN_GATE")
        assert updated.parallel_with_phase_id is None
        assert ["7.PLAN_GATE"] in self._groups(fresh_db)

    def test_explicit_partner_joins_contiguous_parallel_component(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "7.PLAN_GATE")

        svc.update_phase_detail(
            phase.id,
            {
                "execution_type": "parallel",
                "parallel_with_phase_id": phase_by_code(fresh_db, "6.TEST_PLAN").id,
            },
        )

        assert (
            phase_by_code(fresh_db, "7.PLAN_GATE").parallel_with_phase_id
            == phase_by_code(fresh_db, "6.TEST_PLAN").id
        )
        assert ["6.SOLUTION", "6.TEST_PLAN", "7.PLAN_GATE"] in self._groups(fresh_db)

    def test_parallel_to_sync_clears_outgoing_and_incoming_links(self, svc, fresh_db):
        phase = phase_by_code(fresh_db, "6.SOLUTION")

        svc.update_phase_detail(phase.id, {"execution_type": "sync"})
        assert phase_by_code(fresh_db, "6.SOLUTION").parallel_with_phase_id is None
        assert phase_by_code(fresh_db, "6.TEST_PLAN").parallel_with_phase_id is None
