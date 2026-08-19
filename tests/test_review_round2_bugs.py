"""Regression tests for bugs found in the second review pass (2026-08-20).

Each test documents a real defect reproduced against the live SQLite schema:

1. SATaskRepository.update mass-assignment (id/project_id overwrite -> FK crash
   or silent data corruption).
2. InstructionService.reorder + SAInstructionRepository.reorder:
   - partial order lists permanently shift unlisted instructions (+1000 offset)
   - instruction ids belonging to other phases mutate foreign rows
   - duplicate ids in the payload leave gaps in step numbering
3. ReasoningEngine: Confidence parsed from text is always 0.0 (multiline block
   leaks into float()).
"""

from __future__ import annotations

import tempfile

import pytest
import sqlalchemy as sa

from project_workflow.application.instruction_service import InstructionService
from project_workflow.infrastructure.db.session import ensure_schema, get_engine
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.wizard.reasoning import ReasoningEngine


@pytest.fixture()
def uow():
    db = tempfile.mktemp(suffix=".db")
    ensure_schema(get_engine("sqlite:///" + db))
    unit = SAUnitOfWork(db_path_or_engine="sqlite:///" + db)
    wid = unit.workflows.create({"name": "WF", "is_default": True})
    pid = unit.projects.create({"name": "P", "code": "P", "workflow_id": wid})
    tid = unit.tasks.create({"project_id": pid, "task_key": "P-1"})
    unit.commit()
    unit.wf, unit.prj, unit.tid = wid, pid, tid  # type: ignore[attr-defined]
    yield unit
    unit.close()


class TestTaskUpdateMassAssignment:
    def test_update_ignores_id_and_project_id(self, uow):
        # id/project_id must be immutable through update()
        uow.tasks.update(uow.tid, {"id": 999, "project_id": 12345, "title": "renamed"})
        uow.commit()
        task = uow.tasks.get_by_id(uow.tid)
        assert task is not None
        assert task.id == uow.tid
        assert task.project_id == uow.prj
        assert task.title == "renamed"

    def test_update_allows_legitimate_fields(self, uow):
        uow.tasks.update(uow.tid, {"title": "t2", "status": "done"})
        uow.commit()
        task = uow.tasks.get_by_id(uow.tid)
        assert task.title == "t2"
        assert task.status == "done"


class TestInstructionReorder:
    def _seed_phase_with_instructions(self, uow, count, tag=None):
        code = f"ph{tag or count}"
        pid = uow.phases.create(
            {"workflow_id": uow.wf, "code": code, "name": f"Ph{code}", "phase_order": count}
        )
        ids = [
            uow.instructions.create(pid, {"description": f"i{n}", "step_num": n})
            for n in range(1, count + 1)
        ]
        uow.commit()
        return pid, ids

    def test_partial_reorder_keeps_unlisted_instructions_sane(self, uow):
        pid, ids = self._seed_phase_with_instructions(uow, 3)
        # Reorder only the first two; the third must keep a real step number
        uow.instructions.reorder(pid, [(ids[1], 1), (ids[0], 2)])
        uow.commit()
        steps = {i["description"]: i["step_num"] for i in uow.instructions.list(pid)}
        assert steps["i3"] < 100, f"unlisted instruction shifted: {steps}"

    def test_reorder_does_not_touch_other_phases(self, uow):
        p1, a = self._seed_phase_with_instructions(uow, 2, tag="a")
        p2, b = self._seed_phase_with_instructions(uow, 2, tag="b")
        # Sneak p2's instruction id into p1's reorder payload
        uow.instructions.reorder(p1, [(a[0], 1), (b[0], 5)])
        uow.commit()
        foreign = [i for i in uow.instructions.list(p2) if i["id"] == b[0]][0]
        assert foreign["step_num"] == 1, "reorder mutated an instruction of another phase"

    def test_service_reorder_with_duplicate_ids_has_no_gaps(self, uow):
        pid, ids = self._seed_phase_with_instructions(uow, 2)
        svc = InstructionService(uow)
        svc.reorder_instructions(pid, [ids[1], ids[0], ids[0]])  # duplicate
        uow.commit()
        steps = sorted(i["step_num"] for i in uow.instructions.list(pid))
        assert steps == [1, 2], f"gap or duplicate numbering: {steps}"


class TestReasoningConfidence:
    def test_confidence_parsed_from_text(self):
        text = (
            "Analysis: ready\n"
            "Verdict: PASS\n"
            "Confidence: 0.8\n"
            "Next steps:\n"
            "- deploy\n"
        )
        result = ReasoningEngine.parse(text)
        assert result.confidence == 0.8

    def test_confidence_single_value_variants(self):
        for raw, expected in [("0.5", 0.5), ("1", 1.0), ("85%", 0.85), ("nonsense", 0.0)]:
            text = f"Verdict: PASS\nConfidence: {raw}\n"
            result = ReasoningEngine.parse(text)
            assert result.confidence == expected, f"Confidence {raw!r} -> {result.confidence}"
