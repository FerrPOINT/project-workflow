"""Tests for parallel group logic, record transitions, result builders, and edge cases."""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.wizard]

from project_workflow.wizard import PromptCache, WizardEngine
from project_workflow.wizard.models import Phase, PhaseCheck, PhaseEvidence, PhaseInstruction

# ═══════════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def engine():
    with patch("project_workflow.wizard.convo") as mock_convo:
        mock_convo.get_last_phase.return_value = None
        eng = WizardEngine("AAT-1", "/tmp")
        eng.all_phases = [
            Phase(
                id=1,
                code="-1",
                name="Intake",
                description="",
                execution_type="sync",
                checks=[],
                evidence=[],
                instructions=[],
                next_recommendation="next",
                parallel_with=None,
                rollback_target=None,
                is_blocker=False,
                is_delegated=False,
                delegate=None,
            ),
            Phase(
                id=2,
                code="0",
                name="Jira",
                description="",
                execution_type="sync",
                checks=[],
                evidence=[],
                instructions=[],
                next_recommendation="next",
                parallel_with=None,
                rollback_target=None,
                is_blocker=False,
                is_delegated=False,
                delegate=None,
            ),
            Phase(
                id=3,
                code="1",
                name="Parallel A",
                description="A",
                execution_type="parallel",
                checks=[PhaseCheck(description="check-a")],
                evidence=[PhaseEvidence(item="ev-a")],
                instructions=[PhaseInstruction(step="inst-a")],
                next_recommendation="next",
                parallel_with="2",
                rollback_target="0",
                is_blocker=False,
                is_delegated=False,
                delegate=None,
            ),
            Phase(
                id=4,
                code="2",
                name="Parallel B",
                description="B",
                execution_type="parallel",
                checks=[PhaseCheck(description="check-b")],
                evidence=[PhaseEvidence(item="ev-b")],
                instructions=[PhaseInstruction(step="inst-b")],
                next_recommendation="next",
                parallel_with="1",
                rollback_target="0",
                is_blocker=False,
                is_delegated=False,
                delegate=None,
            ),
            Phase(
                id=5,
                code="3",
                name="Done",
                description="",
                execution_type="sync",
                checks=[],
                evidence=[],
                instructions=[],
                next_recommendation="done",
                parallel_with=None,
                rollback_target=None,
                is_blocker=False,
                is_delegated=False,
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
            id=5,
            code="3",
            name="Done",
            description="",
            execution_type="parallel",
            checks=[],
            evidence=[],
            instructions=[],
            next_recommendation="done",
            parallel_with=None,
            rollback_target=None,
            is_blocker=False,
            is_delegated=False,
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

    def test_adjacent_parallel_pairs_have_independent_next_phases(self, engine):
        pair_c = Phase(id=5, code="3", name="Parallel C", execution_type="parallel", parallel_with="4")
        pair_d = Phase(id=6, code="4", name="Parallel D", execution_type="parallel", parallel_with="3")
        done = Phase(id=7, code="5", name="Done", execution_type="sync")
        engine.all_phases = [*engine.all_phases[:-1], pair_c, pair_d, done]
        engine.phase_map = {phase.code: phase for phase in engine.all_phases}

        first = engine._get_parallel_group(engine.phase_map["1"])
        second = engine._get_parallel_group(engine.phase_map["3"])

        assert [phase.code for phase in first] == ["1", "2"]
        assert engine._get_next_phase_after_group(first) == ("3", "Parallel C")
        assert [phase.code for phase in second] == ["3", "4"]
        assert engine._get_next_phase_after_group(second) == ("5", "Done")


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


def _record_calls(engine, callback):
    with (
        patch.object(engine.db.tasks, "add_history") as history,
        patch.object(engine.db.tasks, "update_if_state", return_value=True) as update,
    ):
        callback()
    return [call.args for call in history.call_args_list], update.call_args.args


class TestRecordTransition:
    def test_pass(self, engine):
        ph = engine.phase_map["-1"]
        history, update = _record_calls(engine, lambda: engine._record_transition(ph, "pass", "0", None))
        assert history == [(7, 1, "done"), (7, 2, "pending")]
        assert update == (7, "-1", "active", {"current_phase": "0", "status": "active"})

    @pytest.mark.parametrize(
        ("verdict", "status", "task_status"),
        [("soft_fail", "partial", "active"), ("blocked", "blocked", "blocked"), ("delegate", "delegated", "active")],
    )
    def test_stays_on_phase(self, engine, verdict, status, task_status):
        ph = engine.phase_map["-1"]
        history, update = _record_calls(engine, lambda: engine._record_transition(ph, verdict, None, None))
        assert history == [(7, 1, status)]
        assert update[-1] == {"current_phase": "-1", "status": task_status}

    def test_rollback(self, engine):
        ph = engine.phase_map["0"]
        history, update = _record_calls(engine, lambda: engine._record_transition(ph, "rollback", None, "-1"))
        assert history == [(7, 2, "rollback"), (7, 1, "pending")]
        assert update[-1] == {"current_phase": "-1", "status": "active"}

    def test_rollback_without_target_uses_phase(self, engine):
        ph = engine.phase_map["0"]
        history, update = _record_calls(engine, lambda: engine._record_transition(ph, "rollback", None, None))
        assert history == [(7, 2, "rollback"), (7, 2, "pending")]
        assert update[-1] == {"current_phase": "0", "status": "active"}


# ═══════════════════════════════════════════════════════════════════════
#  _record_parallel_transition
# ═══════════════════════════════════════════════════════════════════════


class TestRecordParallelTransition:
    def test_pass_advances_all_and_next(self, engine):
        group = [engine.phase_map["1"], engine.phase_map["2"]]
        history, update = _record_calls(engine, lambda: engine._record_parallel_transition(group, "pass", "3"))
        assert history == [(7, 3, "done"), (7, 4, "done"), (7, 5, "pending")]
        assert update[-1] == {"current_phase": "3", "status": "active"}

    def test_pass_no_next_marks_done(self, engine):
        group = [engine.phase_map["3"]]
        history, update = _record_calls(engine, lambda: engine._record_parallel_transition(group, "pass", None))
        assert history == [(7, 5, "done")]
        assert update[-1] == {"current_phase": "3", "status": "done"}

    @pytest.mark.parametrize(
        ("verdict", "history_status", "task_status"),
        [("partial", "partial", "active"), ("blocked", "blocked", "blocked")],
    )
    def test_group_stays_on_first_phase(self, engine, verdict, history_status, task_status):
        group = [engine.phase_map["1"], engine.phase_map["2"]]
        history, update = _record_calls(engine, lambda: engine._record_parallel_transition(group, verdict, "3"))
        assert history == [(7, 3, history_status), (7, 4, history_status)]
        assert update[-1] == {"current_phase": "1", "status": task_status}

    def test_rollback_records_group_and_target(self, engine):
        group = [engine.phase_map["1"], engine.phase_map["2"]]
        history, update = _record_calls(
            engine, lambda: engine._record_parallel_transition(group, "rollback", None, "0")
        )
        assert history == [(7, 3, "rollback"), (7, 4, "rollback"), (7, 2, "pending")]
        assert update[-1] == {"current_phase": "0", "status": "active"}


# ═══════════════════════════════════════════════════════════════════════
#  evaluate edge cases
# ═══════════════════════════════════════════════════════════════════════


class TestEvaluateEdgeCases:
    def test_orphan_phase_returns_blocked(self):
        with patch("project_workflow.wizard.convo") as mock_convo:
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

    def test_sync_evaluate_pass(self, wizard_llm):
        with patch("project_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1", "/tmp")
            ph = Phase(
                id=1,
                code="-1",
                name="T",
                description="",
                checks=[PhaseCheck(description="deploy")],
                evidence=[],
                instructions=[],
                next_recommendation="next",
                parallel_with=None,
                rollback_target=None,
                is_blocker=False,
                is_delegated=False,
                delegate=None,
            )
            engine.phase_map = {"-1": ph}
            engine.all_phases = [ph]
            engine.current_phase = "-1"
            engine.task = {"id": 7, "current_phase": "-1", "status": "active", "project_id": 1}
            engine.db = MagicMock()
            wizard_llm("PASS", covered=["deploy"])
            result = engine.evaluate("deploy done")
        assert result["verdict"] == "PASS"
        assert "deploy" in result["covered"]

    def test_parallel_evaluate_pass(self, wizard_llm):
        with patch("project_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1", "/tmp")
            ph_a = Phase(
                id=1,
                code="1",
                name="A",
                description="A",
                execution_type="parallel",
                checks=[PhaseCheck(description="check-a")],
                evidence=[],
                instructions=[],
                next_recommendation="next",
                parallel_with="2",
                rollback_target=None,
                is_blocker=False,
                is_delegated=False,
                delegate=None,
            )
            ph_b = Phase(
                id=2,
                code="2",
                name="B",
                description="B",
                execution_type="parallel",
                checks=[PhaseCheck(description="check-b")],
                evidence=[],
                instructions=[],
                next_recommendation="next",
                parallel_with="1",
                rollback_target=None,
                is_blocker=False,
                is_delegated=False,
                delegate=None,
            )
            ph_next = Phase(
                id=3,
                code="3",
                name="Next",
                description="",
                execution_type="sync",
                checks=[],
                evidence=[],
                instructions=[],
            )
            engine.phase_map = {"1": ph_a, "2": ph_b, "3": ph_next}
            engine.all_phases = [ph_a, ph_b, ph_next]
            engine.current_phase = "1"
            engine.task = {"id": 7, "current_phase": "1", "status": "active", "project_id": 1}
            engine.db = MagicMock()
            wizard_llm("PASS", covered=["check-a", "check-b"])
            result = engine.evaluate("check-a done and check-b complete")
        assert result["verdict"] == "PASS"
        assert result["phase_name"] == "Parallel group: 1, 2"

    def test_parallel_evaluate_partial_stays(self, wizard_llm):
        with patch("project_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1", "/tmp")
            ph_a = Phase(
                id=1,
                code="1",
                name="A",
                description="A",
                execution_type="parallel",
                checks=[PhaseCheck(description="deploy microservice")],
                evidence=[],
                instructions=[],
                next_recommendation="next",
                parallel_with="2",
                rollback_target=None,
                is_blocker=False,
                is_delegated=False,
                delegate=None,
            )
            ph_b = Phase(
                id=2,
                code="2",
                name="B",
                description="B",
                execution_type="parallel",
                checks=[PhaseCheck(description="write unit tests")],
                evidence=[],
                instructions=[],
                next_recommendation="next",
                parallel_with="1",
                rollback_target=None,
                is_blocker=False,
                is_delegated=False,
                delegate=None,
            )
            ph_next = Phase(
                id=3,
                code="3",
                name="Next",
                description="",
                execution_type="sync",
                checks=[],
                evidence=[],
                instructions=[],
            )
            engine.phase_map = {"1": ph_a, "2": ph_b, "3": ph_next}
            engine.all_phases = [ph_a, ph_b, ph_next]
            engine.current_phase = "1"
            engine.task = {"id": 7, "current_phase": "1", "status": "active", "project_id": 1}
            engine.db = MagicMock()
            wizard_llm("PARTIAL", covered=["deploy microservice"], missing=["write unit tests"])
            result = engine.evaluate("microservice deployed")
        assert result["verdict"] == "PARTIAL"
        assert result["next_phase"] is None  # non-pass: stay on group
        assert "write unit tests" in result["missing"]
