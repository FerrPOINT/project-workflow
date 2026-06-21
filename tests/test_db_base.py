"""Direct unit tests for WorkflowDB in db/base.py.

All tests use a temporary in-memory SQLite database for isolation.
"""
from __future__ import annotations

import pytest

from project_workflow.db import WorkflowDB


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    wdb = WorkflowDB(str(db_path))
    wdb.init()
    return wdb


class TestWorkflowCRUD:
    def test_create_workflow_requires_name(self, db):
        with pytest.raises(ValueError, match="Workflow name is required"):
            db.create_workflow({})

    def test_create_workflow_and_get(self, db):
        wid = db.create_workflow({"name": "W1", "description": "desc"})
        wf = db.get_workflow(wid)
        assert wf["name"] == "W1"
        assert wf["description"] == "desc"
        assert wf["is_default"] is False

    def test_get_workflow_by_name(self, db):
        db.create_workflow({"name": "W1"})
        wf = db.get_workflow_by_name("W1")
        assert wf["name"] == "W1"
        assert db.get_workflow_by_name("") is None

    def test_get_default_workflow_after_init(self, db):
        wf = db.get_default_workflow()
        assert wf is not None
        assert wf["is_default"] is True

    def test_update_workflow(self, db):
        wid = db.create_workflow({"name": "W1"})
        db.update_workflow(wid, {"description": "new desc"})
        wf = db.get_workflow(wid)
        assert wf["description"] == "new desc"

    def test_delete_workflow(self, db):
        wid = db.create_workflow({"name": "W1"})
        db.delete_workflow(wid)
        assert db.get_workflow(wid) is None

    def test_delete_workflow_blocked_by_linked_phases(self, db):
        wid = db.create_workflow({"name": "W2"})
        db.create_phase({"workflow_id": wid, "code": "w2-p1", "name": "P1", "phase_order": 2})
        # delete_workflow now cascades phases, so deletion should succeed and leave no phases.
        db.delete_workflow(wid)
        assert db.get_workflow(wid) is None
        assert db.get_phases(workflow_id=wid) == []


class TestProjectCRUD:
    def test_create_project_requires_code(self, db):
        with pytest.raises(ValueError, match="Project code is required"):
            db.create_project({"name": "P"})

    def test_create_project_and_get(self, db):
        pid = db.create_project({"code": "PROJ1", "name": "Project One"})
        proj = db.get_project(pid)
        assert proj["code"] == "PROJ1"
        assert proj["name"] == "Project One"
        assert proj["key_patterns"] == []

    def test_get_project_by_code(self, db):
        db.create_project({"code": "PROJ1", "name": "Project One"})
        proj = db.get_project_by_code("PROJ1")
        assert proj["name"] == "Project One"

    def test_project_key_patterns_serialization(self, db):
        pid = db.create_project({
            "code": "P2",
            "name": "P2",
            "key_patterns": ["^A-\\d+$"],
        })
        proj = db.get_project(pid)
        assert proj["key_patterns"] == ["^A-\\d+$"]

    def test_update_project_key_patterns(self, db):
        pid = db.create_project({"code": "P3", "name": "P3"})
        db.update_project(pid, {"key_patterns": ["^B-\\d+$"]})
        proj = db.get_project(pid)
        assert proj["key_patterns"] == ["^B-\\d+$"]

    def test_delete_project(self, db):
        pid = db.create_project({"code": "P4", "name": "P4"})
        db.delete_project(pid)
        assert db.get_project(pid) is None


class TestPhaseCRUD:
    def test_create_phase_and_get(self, db):
        wid = db.get_default_workflow()["id"]
        phid = db.create_phase({
            "workflow_id": wid,
            "code": "1",
            "name": "First",
            "phase_order": 1,
        })
        ph = db.get_phase(phid)
        assert ph["code"] == "1"
        assert ph["name"] == "First"
        assert ph["workflow_id"] == wid

    def test_get_phase_by_code(self, db):
        wid = db.get_default_workflow()["id"]
        db.create_phase({"workflow_id": wid, "code": "2", "name": "Two", "phase_order": 2})
        ph = db.get_phase_by_code("2")
        assert ph["name"] == "Two"

    def test_update_phase(self, db):
        wid = db.get_default_workflow()["id"]
        phid = db.create_phase({"workflow_id": wid, "code": "3", "name": "Three", "phase_order": 3})
        db.update_phase(phid, {"description": "Updated"})
        ph = db.get_phase(phid)
        assert ph["description"] == "Updated"

    def test_delete_phase(self, db):
        wid = db.get_default_workflow()["id"]
        phid = db.create_phase({"workflow_id": wid, "code": "4", "name": "Four", "phase_order": 4})
        db.create_phase({"workflow_id": wid, "code": "5", "name": "Five", "phase_order": 5})
        db.delete_phase(phid)
        assert db.get_phase(phid) is None

    def test_delete_phase_refuses_last_phase(self, db):
        """A workflow must always keep at least one phase."""
        workflow_id = db.create_workflow({"name": "Last Phase Guard"})
        phases = db.get_phases(workflow_id=workflow_id)
        assert len(phases) == 1
        with pytest.raises(ValueError, match="only phase"):
            db.delete_phase(phases[0]["id"])

    def test_delete_phase_allows_non_last(self, db):
        workflow_id = db.create_workflow({"name": "Non Last Phase"})
        db.create_phase({"workflow_id": workflow_id, "code": "extra", "name": "Extra", "phase_order": 2})
        phases = db.get_phases(workflow_id=workflow_id)
        assert len(phases) == 2
        extra_phase = next(p for p in phases if p["code"] == "extra")
        db.delete_phase(extra_phase["id"])
        remaining = db.get_phases(workflow_id=workflow_id)
        assert len(remaining) == 1

    def test_create_workflow_creates_default_phase(self, db):
        workflow_id = db.create_workflow({"name": "Default Phase WF"})
        phases = db.get_phases(workflow_id=workflow_id)
        assert len(phases) == 1
        assert phases[0]["name"] == "Новая фаза"
        assert phases[0]["execution_type"] == "sync"
        assert phases[0]["is_seed_managed"] == 0
        assert phases[0]["phase_order"] == 1

    def test_get_phases_by_workflow(self, db):
        wid = db.get_default_workflow()["id"]
        db.create_phase({"workflow_id": wid, "code": "5", "name": "Five", "phase_order": 5})
        phases = db.get_phases(workflow_id=wid)
        assert any(p["code"] == "5" for p in phases)


class TestInstructionCheckEvidence:
    def test_create_instruction(self, db):
        wid = db.get_default_workflow()["id"]
        phid = db.create_phase({"workflow_id": wid, "code": "1", "name": "Phase", "phase_order": 1})
        iid = db.create_instruction({
            "phase_id": phid,
            "step_num": 1,
            "description": "Step one",
        })
        insts = db.get_phase_instructions(phid)
        assert any(i["id"] == iid for i in insts)

    def test_reorder_instructions(self, db):
        wid = db.get_default_workflow()["id"]
        phid = db.create_phase({"workflow_id": wid, "code": "1", "name": "Phase", "phase_order": 1})
        iid1 = db.create_instruction({"phase_id": phid, "step_num": 1, "description": "A"})
        iid2 = db.create_instruction({"phase_id": phid, "step_num": 2, "description": "B"})
        db.reorder_instructions(phid, [iid2, iid1])
        insts = db.get_phase_instructions(phid)
        assert insts[0]["id"] == iid2
        assert insts[1]["id"] == iid1

    def test_create_check(self, db):
        wid = db.get_default_workflow()["id"]
        phid = db.create_phase({"workflow_id": wid, "code": "1", "name": "Phase", "phase_order": 1})
        cid = db.create_check({"phase_id": phid, "description": "Check A"})
        checks = db.get_phase_checks(phid)
        assert any(c["id"] == cid for c in checks)

    def test_create_evidence(self, db):
        wid = db.get_default_workflow()["id"]
        phid = db.create_phase({"workflow_id": wid, "code": "1", "name": "Phase", "phase_order": 1})
        eid = db.create_evidence({"phase_id": phid, "description": "Evidence A"})
        evs = db.get_phase_evidence(phid)
        assert any(e["id"] == eid for e in evs)


class TestTaskCRUD:
    def test_create_task_requires_project_match(self, db):
        with pytest.raises(ValueError, match="No project regex matched"):
            db.create_task({"task_key": "UNKNOWN-1"})

    def test_create_task_and_get(self, db):
        db.create_project({"code": "TST", "name": "Tst", "key_patterns": ["^(?P<prefix>TST)-(?P<number>\\d+)$"]})
        tid = db.create_task({"task_key": "TST-1", "title": "Title"})
        task = db.get_task(tid)
        assert task["task_key"] == "TST-1"
        assert task["title"] == "Title"
        assert task["current_phase"] == "-1"

    def test_get_task_by_key(self, db):
        db.create_project({"code": "TST", "name": "Tst", "key_patterns": ["^(?P<prefix>TST)-(?P<number>\\d+)$"]})
        db.create_task({"task_key": "TST-2"})
        task = db.get_task_by_key("TST-2")
        assert task["task_key"] == "TST-2"
        assert db.get_task_by_key("NONE") is None

    def test_update_task(self, db):
        db.create_project({"code": "TST", "name": "Tst", "key_patterns": ["^(?P<prefix>TST)-(?P<number>\\d+)$"]})
        tid = db.create_task({"task_key": "TST-3"})
        db.update_task(tid, {"title": "Updated", "current_phase": "0"})
        task = db.get_task(tid)
        assert task["title"] == "Updated"
        assert task["current_phase"] == "0"

    def test_delete_task(self, db):
        db.create_project({"code": "TST", "name": "Tst", "key_patterns": ["^(?P<prefix>TST)-(?P<number>\\d+)$"]})
        tid = db.create_task({"task_key": "TST-4"})
        db.delete_task(tid)
        assert db.get_task(tid) is None


class TestTaskHistory:
    def test_add_and_get_history(self, db):
        db.create_project({"code": "TST", "name": "Tst", "key_patterns": ["^(?P<prefix>TST)-(?P<number>\\d+)$"]})
        tid = db.create_task({"task_key": "TST-5"})
        wid = db.get_default_workflow()["id"]
        phid = db.create_phase({"workflow_id": wid, "code": "1", "name": "Phase", "phase_order": 1})
        db.add_task_history(tid, phid, status="done")
        hist = db.get_task_history(tid)
        assert len(hist) == 1
        assert hist[0]["status"] == "done"


class TestSupervisorRuns:
    def test_create_supervisor_run_by_task_id(self, db):
        db.create_project({"code": "TST", "name": "Tst", "key_patterns": ["^(?P<prefix>TST)-(?P<number>\\d+)$"]})
        tid = db.create_task({"task_key": "TST-6"})
        wid = db.get_default_workflow()["id"]
        phid = db.create_phase({"workflow_id": wid, "code": "1", "name": "Phase", "phase_order": 1})
        run_id = db.create_supervisor_run({
            "task_id": tid,
            "phase_id": phid,
            "verdict": "pass",
            "covered": ["A"],
            "missing": [],
            "blockers": [],
        })
        runs = db.get_supervisor_runs(task_id=tid)
        assert any(r["id"] == run_id for r in runs)

    def test_create_supervisor_run_by_task_key(self, db):
        db.create_project({"code": "TST", "name": "Tst", "key_patterns": ["^(?P<prefix>TST)-(?P<number>\\d+)$"]})
        _ = db.create_task({"task_key": "TST-7"})
        wid = db.get_default_workflow()["id"]
        phid = db.create_phase({"workflow_id": wid, "code": "1", "name": "Phase", "phase_order": 1})
        db.create_supervisor_run({
            "task_key": "TST-7",
            "phase_id": phid,
            "verdict": "pass",
        })
        runs = db.get_supervisor_runs(task_key="TST-7")
        assert len(runs) >= 1

    def test_create_supervisor_run_requires_task(self, db):
        with pytest.raises(ValueError, match="task_id or task_key is required"):
            db.create_supervisor_run({"phase_id": 1, "verdict": "pass"})

    def test_get_supervisor_runs_requires_task(self, db):
        with pytest.raises(ValueError, match="task_id or task_key is required"):
            db.get_supervisor_runs()


class TestCLIHistory:
    def test_log_and_get_cli_history(self, db):
        db.log_cli_call("step", "TST-1", "req", "resp")
        hist = db.get_cli_history(limit=10)
        assert any(h["command"] == "step" for h in hist)


class TestMatchProject:
    def test_match_project_strict_and_not_strict(self, db):
        db.create_project({"code": "TST", "name": "Tst", "key_patterns": ["^(?P<prefix>TST)-(?P<number>\\d+)$"]})
        assert db.match_project_for_task_key("TST-1")["code"] == "TST"
        assert db.match_project_for_task_key("BOGUS-1", strict=False)["code"] == "TASKNEIROKLYUCH"
        assert db.match_project_for_task_key("BOGUS-1", strict=True) is None


class TestBatchUpdateOrders:
    def test_batch_update_orders(self, db):
        wid = db.get_default_workflow()["id"]
        phid1 = db.create_phase({"workflow_id": wid, "code": "1", "name": "A", "phase_order": 1})
        phid2 = db.create_phase({"workflow_id": wid, "code": "2", "name": "B", "phase_order": 2})
        db.batch_update_orders([(phid1, 10), (phid2, 20)])
        assert db.get_phase(phid1)["phase_order"] == 10
        assert db.get_phase(phid2)["phase_order"] == 20


class TestResolve:
    def test_resolve_phase_id(self, db):
        wid = db.get_default_workflow()["id"]
        phid = db.create_phase({"workflow_id": wid, "code": "r1", "name": "R1", "phase_order": 1})
        assert db._resolve_phase_id(phid) == phid
        assert db._resolve_phase_id("r1") == phid
        with pytest.raises(ValueError, match="Unknown phase code"):
            db._resolve_phase_id("missing")

    def test_resolve_workflow_id(self, db):
        wid = db.get_default_workflow()["id"]
        name = db.get_default_workflow()["name"]
        assert db._resolve_workflow_id(wid) == wid
        assert db._resolve_workflow_id(name) == wid
        with pytest.raises(ValueError, match="Unknown workflow id"):
            db._resolve_workflow_id("no-such-workflow")

    def test_resolve_project_id(self, db):
        pid = db.create_project({"code": "RES", "name": "Res"})
        assert db._resolve_project_id(pid) == pid
        assert db._resolve_project_id("RES") == pid
        with pytest.raises(ValueError, match="Unknown project code"):
            db._resolve_project_id("missing")


class TestJsonHelpers:
    def test_serialize_key_patterns(self, db):
        assert db._serialize_key_patterns(["^A$"]) == '["^A$"]'
        assert db._serialize_key_patterns('["^A$"]') == '["^A$"]'
        assert db._serialize_key_patterns(None) == "[]"

    def test_deserialize_key_patterns(self, db):
        assert db._deserialize_key_patterns('["^A$"]') == ["^A$"]
        assert db._deserialize_key_patterns(["^A$"]) == ["^A$"]
        assert db._deserialize_key_patterns(None) == []
        assert db._deserialize_key_patterns("garbage") == []

    def test_json_loads_dumps(self, db):
        assert db._json_loads('{"a": 1}', {}) == {"a": 1}
        assert db._json_loads(None, []) == []
        assert db._json_loads("bad", {}) == {}
        assert db._json_dumps(None, fallback="[]") == "[]"
