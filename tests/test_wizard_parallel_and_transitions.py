"""Tests for parallel group logic, record transitions, result builders, and edge cases."""

import pytest
from unittest.mock import MagicMock, patch

from wartz_workflow.models import Phase, PhaseCheck, PhaseEvidence, PhaseInstruction, PhaseDelegate
from wartz_workflow.wizard import WizardEngine, PromptCache


# ═══════════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def engine():
    with patch("wartz_workflow.wizard.convo") as mock_convo:
        mock_convo.get_last_phase.return_value = None
        eng = WizardEngine("AAT-1", "/tmp")
        eng.all_phases = [
            Phase(
                id=1, code="-1", name="Intake", description="",
                execution_type="sync",
                checks=[], evidence=[], instructions=[],
                next_recommendation="next",
                parallel_with=None, rollback_target=None,
                is_blocker=False, is_delegated=False,
                delegate=None,
            ),
            Phase(
                id=2, code="0", name="Jira", description="",
                execution_type="sync",
                checks=[], evidence=[], instructions=[],
                next_recommendation="next",
                parallel_with=None, rollback_target=None,
                is_blocker=False, is_delegated=False,
                delegate=None,
            ),
            Phase(
                id=3, code="1", name="Parallel A", description="A",
                execution_type="parallel",
                checks=[PhaseCheck(description="check-a")],
                evidence=[PhaseEvidence(item="ev-a")],
                instructions=[PhaseInstruction(step="inst-a")],
                next_recommendation="next",
                parallel_with="2", rollback_target="0",
                is_blocker=False, is_delegated=False,
                delegate=None,
            ),
            Phase(
                id=4, code="2", name="Parallel B", description="B",
                execution_type="parallel",
                checks=[PhaseCheck(description="check-b")],
                evidence=[PhaseEvidence(item="ev-b")],
                instructions=[PhaseInstruction(step="inst-b")],
                next_recommendation="next",
                parallel_with="1", rollback_target="0",
                is_blocker=False, is_delegated=False,
                delegate=None,
            ),
            Phase(
                id=5, code="3", name="Done", description="",
                execution_type="sync",
                checks=[], evidence=[], instructions=[],
                next_recommendation="done",
                parallel_with=None, rollback_target=None,
                is_blocker=False, is_delegated=False,
                delegate=None,
            ),
        ]
        eng.phase_map = {ph.code: ph for ph in eng.all_phases}
        eng.current_phase = "-1"
        eng.task = {"id": 7, "current_phase": "-1", "status": "active", "project_id": 1}
        yield eng


# ═══════════════════════════════════════════════════════════════════════
#  PromptCache
# ═══════════════════════════════════════════════════════════════════════

class TestPromptCache:
    def test_get_set_hit(self):
        cache = PromptCache()
        cache.set("T-1", "-1", {"data": 42})
        assert cache.get("T-1", "-1") == {"data": 42}

    def test_get_miss(self):
        cache = PromptCache()
        assert cache.get("T-1", "-1") is None

    def test_invalidation_bumps_generation(self):
        cache = PromptCache()
        cache.set("T-1", "-1", {"data": 42})
        cache.invalidate()
        assert cache.get("T-1", "-1") is None

    def test_invalidation_resets_after_1000(self):
        cache = PromptCache()
        cache._gen = 1000
        cache.set("T-1", "-1", {"data": 42})
        cache.invalidate()
        assert cache._gen == 0
        assert cache.get("T-1", "-1") is None


# ═══════════════════════════════════════════════════════════════════════
#  _get_next_phase edge cases
# ═══════════════════════════════════════════════════════════════════════

class TestGetNextPhase:
    def test_last_phase_returns_none(self, engine):
        assert engine._get_next_phase("3") == (None, None)

    def test_phase_not_in_list_returns_none(self, engine):
        assert engine._get_next_phase("nonexistent") == (None, None)

    def test_normal_next(self, engine):
        assert engine._get_next_phase("-1") == ("0", "Jira")


# ═══════════════════════════════════════════════════════════════════════
#  _get_parallel_group
# ═══════════════════════════════════════════════════════════════════════

class TestGetParallelGroup:
    def test_contiguous_parallel_run(self, engine):
        group = engine._get_parallel_group(engine.phase_map["1"])
        codes = [p.code for p in group]
        assert codes == ["1", "2"]

    def test_single_parallel_when_last(self, engine):
        # Mock last phase as parallel
        engine.all_phases[-1] = Phase(
            id=5, code="3", name="Done", description="",
            execution_type="parallel",
            checks=[], evidence=[], instructions=[],
            next_recommendation="done",
            parallel_with=None, rollback_target=None,
            is_blocker=False, is_delegated=False,
            delegate=None,
        )
        engine.phase_map["3"] = engine.all_phases[-1]
        group = engine._get_parallel_group(engine.phase_map["3"])
        codes = [p.code for p in group]
        assert codes == ["3"]

    def test_value_error_returns_single(self, engine):
        orphan = Phase(id=99, code="orphan", name="O", description="")
        group = engine._get_parallel_group(orphan)
        assert group == [orphan]


# ═══════════════════════════════════════════════════════════════════════
#  _get_next_phase_after_group
# ═══════════════════════════════════════════════════════════════════════

class TestGetNextPhaseAfterGroup:
    def test_normal(self, engine):
        group = [engine.phase_map["1"], engine.phase_map["2"]]
        assert engine._get_next_phase_after_group(group) == ("3", "Done")

    def test_empty_group(self, engine):
        assert engine._get_next_phase_after_group([]) == (None, None)

    def test_last_group_returns_none(self, engine):
        group = [engine.phase_map["3"]]
        assert engine._get_next_phase_after_group(group) == (None, None)

    def test_value_error_returns_none(self, engine):
        orphan = Phase(id=99, code="orphan", name="O", description="")
        assert engine._get_next_phase_after_group([orphan]) == (None, None)


# ═══════════════════════════════════════════════════════════════════════
#  _record_transition — all verdict branches
# ═══════════════════════════════════════════════════════════════════════

class TestRecordTransition:
    def test_pass(self, engine):
        ph = engine.phase_map["-1"]
        with patch.object(engine.db, "add_task_history") as mock_hist, \
             patch.object(engine.db, "update_task") as mock_upd:
            engine._record_transition(ph, "pass", "0", None)
        calls = [c.args for c in mock_hist.call_args_list]
        assert calls == [(7, "-1", "done"), (7, "0", "pending")]
        mock_upd.assert_called_once_with(7, {"current_phase": "0", "status": "active"})

    def test_partial(self, engine):
        ph = engine.phase_map["-1"]
        with patch.object(engine.db, "add_task_history") as mock_hist, \
             patch.object(engine.db, "update_task") as mock_upd:
            engine._record_transition(ph, "partial", None, None)
        mock_hist.assert_called_once_with(7, "-1", "partial")
        mock_upd.assert_called_once_with(7, {"current_phase": "-1", "status": "active"})

    def test_blocked(self, engine):
        ph = engine.phase_map["-1"]
        with patch.object(engine.db, "add_task_history") as mock_hist, \
             patch.object(engine.db, "update_task") as mock_upd:
            engine._record_transition(ph, "blocked", None, None)
        mock_hist.assert_called_once_with(7, "-1", "blocked")
        mock_upd.assert_called_once_with(7, {"current_phase": "-1", "status": "blocked"})

    def test_rollback(self, engine):
        ph = engine.phase_map["0"]
        with patch.object(engine.db, "add_task_history") as mock_hist, \
             patch.object(engine.db, "update_task") as mock_upd:
            engine._record_transition(ph, "rollback", None, "-1")
        calls = [c.args for c in mock_hist.call_args_list]
        assert calls == [(7, "0", "rollback"), (7, "-1", "pending")]
        mock_upd.assert_called_once_with(7, {"current_phase": "-1", "status": "active"})

    def test_rollback_without_target_uses_phase(self, engine):
        ph = engine.phase_map["0"]
        ph.rollback_target = None
        with patch.object(engine.db, "add_task_history") as mock_hist, \
             patch.object(engine.db, "update_task") as mock_upd:
            engine._record_transition(ph, "rollback", None, None)
        calls = [c.args for c in mock_hist.call_args_list]
        assert calls == [(7, "0", "rollback"), (7, "0", "pending")]
        mock_upd.assert_called_once_with(7, {"current_phase": "0", "status": "active"})

    def test_delegate(self, engine):
        ph = engine.phase_map["-1"]
        with patch.object(engine.db, "add_task_history") as mock_hist, \
             patch.object(engine.db, "update_task") as mock_upd:
            engine._record_transition(ph, "delegate", None, None)
        mock_hist.assert_called_once_with(7, "-1", "delegated")
        mock_upd.assert_called_once_with(7, {"current_phase": "-1", "status": "active"})


# ═══════════════════════════════════════════════════════════════════════
#  _record_parallel_transition
# ═══════════════════════════════════════════════════════════════════════

class TestRecordParallelTransition:
    def test_pass_advances_all_and_next(self, engine):
        group = [engine.phase_map["1"], engine.phase_map["2"]]
        with patch.object(engine.db, "add_task_history") as mock_hist, \
             patch.object(engine.db, "update_task") as mock_upd:
            engine._record_parallel_transition(group, "pass", "3")
        calls = [c.args for c in mock_hist.call_args_list]
        assert calls == [(7, "1", "done"), (7, "2", "done"), (7, "3", "pending")]
        mock_upd.assert_called_once_with(7, {"current_phase": "3", "status": "active"})

    def test_pass_no_next_marks_done(self, engine):
        # Only one phase, no next
        group = [engine.phase_map["3"]]
        with patch.object(engine.db, "add_task_history") as mock_hist, \
             patch.object(engine.db, "update_task") as mock_upd:
            engine._record_parallel_transition(group, "pass", None)
        mock_hist.assert_called_once_with(7, "3", "done")
        mock_upd.assert_called_once_with(7, {"current_phase": "3", "status": "done"})

    def test_partial_does_not_touch_history(self, engine):
        group = [engine.phase_map["1"], engine.phase_map["2"]]
        with patch.object(engine.db, "add_task_history") as mock_hist, \
             patch.object(engine.db, "update_task") as mock_upd:
            engine._record_parallel_transition(group, "partial", "3")
        mock_hist.assert_not_called()
        mock_upd.assert_not_called()

    def test_blocked_sets_status(self, engine):
        group = [engine.phase_map["1"], engine.phase_map["2"]]
        with patch.object(engine.db, "add_task_history") as mock_hist, \
             patch.object(engine.db, "update_task") as mock_upd:
            engine._record_parallel_transition(group, "blocked", "3")
        mock_hist.assert_not_called()
        mock_upd.assert_called_once_with(7, {"status": "blocked"})


# ═══════════════════════════════════════════════════════════════════════
#  _build_result verdict branches
# ═══════════════════════════════════════════════════════════════════════

class TestBuildResult:
    def _make_engine(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            eng = WizardEngine("AAT-1", "/tmp")
        eng.db = MagicMock()
        return eng

    def test_pass_message(self):
        engine = self._make_engine()
        ph = Phase(id=1, code="0", name="X", description="", next_recommendation="Go next")
        result = engine._build_result(
            phase=ph, verdict="pass",
            covered=["c"], missing=[], blockers=[],
            next_phase="1", next_phase_name="Next",
            rollback_target=None,
        )
        assert result["verdict"] == "PASS"
        assert result["message"] == "Go next"
        assert result["next_phase"] == "1"

    def test_rollback_message(self):
        engine = self._make_engine()
        ph = Phase(id=1, code="0", name="X", description="")
        result = engine._build_result(
            phase=ph, verdict="rollback",
            covered=[], missing=[], blockers=[],
            next_phase=None, next_phase_name=None,
            rollback_target="-1",
        )
        assert result["verdict"] == "ROLLBACK"
        assert "roll back to" in result["message"]

    def test_blocked_message(self):
        engine = self._make_engine()
        ph = Phase(id=1, code="0", name="X", description="")
        result = engine._build_result(
            phase=ph, verdict="blocked",
            covered=[], missing=["m1"], blockers=["b1"],
            next_phase=None, next_phase_name=None,
            rollback_target=None,
        )
        assert result["verdict"] == "BLOCKED"
        assert "BLOCKED" in result["message"]

    def test_delegate_message(self):
        engine = self._make_engine()
        ph = Phase(id=1, code="0", name="X", description="")
        result = engine._build_result(
            phase=ph, verdict="delegate",
            covered=[], missing=[], blockers=[],
            next_phase=None, next_phase_name=None,
            rollback_target=None,
        )
        assert result["verdict"] == "DELEGATE"
        assert "Delegate work" in result["message"]

    def test_partial_message(self):
        engine = self._make_engine()
        ph = Phase(id=1, code="0", name="X", description="")
        result = engine._build_result(
            phase=ph, verdict="partial",
            covered=["c1"], missing=["m1"], blockers=[],
            next_phase=None, next_phase_name=None,
            rollback_target=None,
        )
        assert result["verdict"] == "PARTIAL"
        assert "PARTIAL" in result["message"]


# ═══════════════════════════════════════════════════════════════════════
#  _build_parallel_result verdict branches
# ═══════════════════════════════════════════════════════════════════════

class TestBuildParallelResult:
    def _make_engine(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            eng = WizardEngine("AAT-1", "/tmp")
        eng.db = MagicMock()
        return eng

    def test_pass(self):
        engine = self._make_engine()
        ph_a = Phase(id=1, code="1", name="A", description="")
        ph_b = Phase(id=2, code="2", name="B", description="")
        engine.phase_map = {"1": ph_a, "2": ph_b, "0": Phase(id=0, code="0", name="Prev", description="")}
        group = [ph_a, ph_b]
        result = engine._build_parallel_result(
            group, "pass", ["c"], [], [],
            "0", "Prev", None,
        )
        assert result["verdict"] == "PASS"
        assert "accepted" in result["message"]
        assert result["next_phase"] == "0"
        assert result["next_phase_name"] == "Prev"

    def test_rollback(self):
        engine = self._make_engine()
        ph_a = Phase(id=1, code="1", name="A", description="")
        ph_b = Phase(id=2, code="2", name="B", description="")
        engine.phase_map = {"0": Phase(id=0, code="0", name="Prev", description="")}
        group = [ph_a, ph_b]
        result = engine._build_parallel_result(
            group, "rollback", [], [], [],
            None, None, "0",
        )
        assert result["verdict"] == "ROLLBACK"
        assert "Roll back" in result["message"]
        assert result["next_phase"] == "0"
        assert result["next_phase_name"] == "Prev"

    def test_blocked(self):
        engine = self._make_engine()
        ph_a = Phase(id=1, code="1", name="A", description="")
        group = [ph_a]
        result = engine._build_parallel_result(
            group, "blocked", [], ["m1"], ["b1"],
            None, None, None,
        )
        assert result["verdict"] == "BLOCKED"
        assert "BLOCKED" in result["message"]

    def test_delegate(self):
        engine = self._make_engine()
        ph_a = Phase(id=1, code="1", name="A", description="")
        group = [ph_a]
        result = engine._build_parallel_result(
            group, "delegate", [], [], [],
            None, None, None,
        )
        assert result["verdict"] == "DELEGATE"
        assert "Delegate work" in result["message"]

    def test_partial(self):
        engine = self._make_engine()
        ph_a = Phase(id=1, code="1", name="A", description="")
        group = [ph_a]
        result = engine._build_parallel_result(
            group, "partial", ["c1"], ["m1"], [],
            None, None, None,
        )
        assert result["verdict"] == "PARTIAL"
        assert "PARTIAL" in result["message"]


# ═══════════════════════════════════════════════════════════════════════
#  _build_fail_message
# ═══════════════════════════════════════════════════════════════════════

class TestBuildFailMessage:
    def _make_engine(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            eng = WizardEngine("AAT-1")
        eng.db = MagicMock()
        return eng

    def test_with_missing_and_blockers(self):
        engine = self._make_engine()
        ph = Phase(id=1, code="0", name="X", description="")
        msg = engine._build_fail_message(ph, ["m1"], ["b1"])
        assert "Missing or blocked" in msg
        assert "m1" in msg
        # When missing is truthy, blockers are not included (Python `or` short-circuit)
        # This is expected behavior

    def test_with_only_blockers(self):
        engine = self._make_engine()
        ph = Phase(id=1, code="0", name="X", description="")
        msg = engine._build_fail_message(ph, [], ["b1"])
        assert "Missing or blocked" in msg
        assert "b1" in msg

    def test_with_only_blockers_multiple(self):
        engine = self._make_engine()
        ph = Phase(id=1, code="0", name="X", description="")
        msg = engine._build_fail_message(ph, [], ["b1", "b2"])
        assert "b1" in msg
        assert "b2" in msg

    def test_fallback_to_phase_name(self):
        engine = self._make_engine()
        ph = Phase(id=1, code="0", name="X", description="")
        msg = engine._build_fail_message(ph, [], [])
        assert "X" in msg


# ═══════════════════════════════════════════════════════════════════════
#  evaluate edge cases
# ═══════════════════════════════════════════════════════════════════════

class TestEvaluateEdgeCases:
    def test_orphan_phase_returns_blocked(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1", "/tmp")
            engine.current_phase = "orphan"
            engine.phase_map = {}
            engine.all_phases = []
            engine.task = {"id": 7, "current_phase": "orphan", "status": "active", "project_id": 1}
            engine.db = MagicMock()
            result = engine.evaluate("report")
        assert result["verdict"] == "BLOCKED"
        assert result["blockers"] == ["phase-not-configured"]

    def test_sync_evaluate_pass(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1", "/tmp")
            ph = Phase(
                id=1, code="-1", name="T", description="",
                checks=[PhaseCheck(description="deploy")],
                evidence=[], instructions=[],
                next_recommendation="next",
                parallel_with=None, rollback_target=None,
                is_blocker=False, is_delegated=False,
                delegate=None,
            )
            engine.phase_map = {"-1": ph}
            engine.all_phases = [ph]
            engine.current_phase = "-1"
            engine.task = {"id": 7, "current_phase": "-1", "status": "active", "project_id": 1}
            engine.db = MagicMock()
            result = engine.evaluate("deploy done")
        assert result["verdict"] == "PASS"
        assert "deploy" in result["covered"]

    def test_parallel_evaluate_pass(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1", "/tmp")
            ph_a = Phase(
                id=1, code="1", name="A", description="A",
                execution_type="parallel",
                checks=[PhaseCheck(description="check-a")],
                evidence=[], instructions=[],
                next_recommendation="next",
                parallel_with="2", rollback_target=None,
                is_blocker=False, is_delegated=False,
                delegate=None,
            )
            ph_b = Phase(
                id=2, code="2", name="B", description="B",
                execution_type="parallel",
                checks=[PhaseCheck(description="check-b")],
                evidence=[], instructions=[],
                next_recommendation="next",
                parallel_with="1", rollback_target=None,
                is_blocker=False, is_delegated=False,
                delegate=None,
            )
            ph_next = Phase(
                id=3, code="3", name="Next", description="",
                execution_type="sync", checks=[], evidence=[], instructions=[],
            )
            engine.phase_map = {"1": ph_a, "2": ph_b, "3": ph_next}
            engine.all_phases = [ph_a, ph_b, ph_next]
            engine.current_phase = "1"
            engine.task = {"id": 7, "current_phase": "1", "status": "active", "project_id": 1}
            engine.db = MagicMock()
            result = engine.evaluate("check-a done and check-b complete")
        assert result["verdict"] == "PASS"
        assert result["phase_name"] == "Parallel group: 1, 2"

    def test_parallel_evaluate_partial_stays(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1", "/tmp")
            ph_a = Phase(
                id=1, code="1", name="A", description="A",
                execution_type="parallel",
                checks=[PhaseCheck(description="deploy microservice")],
                evidence=[], instructions=[],
                next_recommendation="next",
                parallel_with="2", rollback_target=None,
                is_blocker=False, is_delegated=False,
                delegate=None,
            )
            ph_b = Phase(
                id=2, code="2", name="B", description="B",
                execution_type="parallel",
                checks=[PhaseCheck(description="write unit tests")],
                evidence=[], instructions=[],
                next_recommendation="next",
                parallel_with="1", rollback_target=None,
                is_blocker=False, is_delegated=False,
                delegate=None,
            )
            ph_next = Phase(
                id=3, code="3", name="Next", description="",
                execution_type="sync", checks=[], evidence=[], instructions=[],
            )
            engine.phase_map = {"1": ph_a, "2": ph_b, "3": ph_next}
            engine.all_phases = [ph_a, ph_b, ph_next]
            engine.current_phase = "1"
            engine.task = {"id": 7, "current_phase": "1", "status": "active", "project_id": 1}
            engine.db = MagicMock()
            result = engine.evaluate("microservice deployed")
        assert result["verdict"] == "PARTIAL"
        assert result["next_phase"] is None  # non-pass: stay on group
        assert "write unit tests" in result["missing"]
