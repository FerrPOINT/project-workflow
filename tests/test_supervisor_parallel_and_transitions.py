"""Tests for parallel group logic, record transitions, result builders, and edge cases."""

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.supervisor]

from project_workflow.domain.exceptions import ConcurrentTransitionError
from project_workflow.supervisor import SupervisorEngine
from project_workflow.supervisor.core import PromptCache
from project_workflow.supervisor.models import Phase, PhaseCheck, PhaseEvidence, PhaseInstruction

# ═══════════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def engine():
    with nullcontext():
        eng = SupervisorEngine("RUN-1")
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
                parallel_with_phase_code=None,
                rollback_target_phase_code=None,
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
                parallel_with_phase_code=None,
                rollback_target_phase_code=None,
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
                parallel_with_phase_code="2",
                rollback_target_phase_code="0",
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
                parallel_with_phase_code="1",
                rollback_target_phase_code="0",
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
                parallel_with_phase_code=None,
                rollback_target_phase_code=None,
                delegate=None,
            ),
        ]
        eng.phase_map = {ph.code: ph for ph in eng.all_phases}
        eng.current_phase_code = "-1"
        eng.task = {
            "id": 7,
            "current_phase_id": 1,
            "current_phase_code": "-1",
            "status": "active",
            "project_id": 1,
            "workflow_id": 1,
        }
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
            parallel_with_phase_code=None,
            rollback_target_phase_code=None,
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
        pair_c = Phase(id=5, code="3", name="Parallel C", execution_type="parallel", parallel_with_phase_code="4")
        pair_d = Phase(id=6, code="4", name="Parallel D", execution_type="parallel", parallel_with_phase_code="3")
        done = Phase(id=7, code="5", name="Done", execution_type="sync")
        engine.all_phases = [*engine.all_phases[:-1], pair_c, pair_d, done]
        engine.phase_map = {phase.code: phase for phase in engine.all_phases}

        first = engine._get_parallel_group(engine.phase_map["1"])
        second = engine._get_parallel_group(engine.phase_map["3"])

        assert [phase.code for phase in first] == ["1", "2"]
        assert engine._get_next_phase_after_group(first) == ("3", "Parallel C")
        assert [phase.code for phase in second] == ["3", "4"]
        assert engine._get_next_phase_after_group(second) == ("5", "Done")

    def test_interleaved_parallel_component_does_not_skip_isolated_phase(self, engine):
        linked_a = Phase(id=10, code="a", name="A", execution_type="parallel", parallel_with_phase_code="c")
        isolated_b = Phase(id=11, code="b", name="B", execution_type="parallel")
        linked_c = Phase(id=12, code="c", name="C", execution_type="parallel")
        done = Phase(id=13, code="done", name="Done", execution_type="sync")
        engine.all_phases = [linked_a, isolated_b, linked_c, done]
        engine.phase_map = {phase.code: phase for phase in engine.all_phases}

        linked_group = engine._get_parallel_group(linked_a)
        isolated_group = engine._get_parallel_group(isolated_b)

        assert engine._resolve_transition(linked_a, "pass", linked_group) == ("b", "B", None)
        assert engine._resolve_transition(isolated_b, "pass", isolated_group) == ("done", "Done", None)


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
        patch.object(engine.db.tasks, "record_phase_event") as events,
        patch.object(engine.db.tasks, "update_if_state", return_value=True) as update,
    ):
        callback()
    return [call.args for call in events.call_args_list], update.call_args.args


class TestRecordTransition:
    def test_pass(self, engine):
        ph = engine.phase_map["-1"]
        events, update = _record_calls(
            engine, lambda: engine._record_transition(ph, "pass", "0", None, 55)
        )
        assert events == [(7, 1, "completed", 55), (7, 2, "entered", 55)]
        assert update == (7, 1, "active", {"current_phase_id": 2, "status": "active"})

    @pytest.mark.parametrize(
        ("verdict", "event_type", "task_status"),
        [("partial", None, "active"), ("blocked", "blocked", "blocked"), ("delegate", None, "active")],
    )
    def test_stays_on_phase(self, engine, verdict, event_type, task_status):
        ph = engine.phase_map["-1"]
        events, update = _record_calls(
            engine, lambda: engine._record_transition(ph, verdict, None, None, 55)
        )
        assert events == ([(7, 1, event_type, 55)] if event_type else [])
        assert update[-1] == {"current_phase_id": 1, "status": task_status}

    def test_rollback(self, engine):
        ph = engine.phase_map["0"]
        events, update = _record_calls(
            engine, lambda: engine._record_transition(ph, "rollback", None, "-1", 55)
        )
        assert events == [(7, 2, "rolled_back", 55), (7, 1, "entered", 55)]
        assert update[-1] == {"current_phase_id": 1, "status": "active"}

    def test_rollback_without_target_is_rejected(self, engine):
        ph = engine.phase_map["0"]
        with pytest.raises(ConcurrentTransitionError, match="Цель отката"):
            _record_calls(engine, lambda: engine._record_transition(ph, "rollback", None, None, 55))

    def test_unknown_next_phase_is_not_treated_as_workflow_completion(self, engine):
        ph = engine.phase_map["0"]
        with pytest.raises(ConcurrentTransitionError, match="Следующая фаза"):
            _record_calls(engine, lambda: engine._record_transition(ph, "pass", "missing", None, 55))


# ═══════════════════════════════════════════════════════════════════════
#  _record_parallel_transition
# ═══════════════════════════════════════════════════════════════════════


class TestRecordParallelTransition:
    def test_pass_advances_all_and_next(self, engine):
        group = [engine.phase_map["1"], engine.phase_map["2"]]
        events, update = _record_calls(
            engine,
            lambda: engine._record_parallel_transition(group, "pass", "3", step_history_id=55),
        )
        assert events == [
            (7, 3, "completed", 55),
            (7, 4, "completed", 55),
            (7, 5, "entered", 55),
        ]
        assert update[-1] == {"current_phase_id": 5, "status": "active"}

    def test_pass_no_next_marks_done(self, engine):
        group = [engine.phase_map["3"]]
        events, update = _record_calls(
            engine,
            lambda: engine._record_parallel_transition(group, "pass", None, step_history_id=55),
        )
        assert events == [(7, 5, "completed", 55)]
        assert update[-1] == {"current_phase_id": 5, "status": "done"}

    @pytest.mark.parametrize(
        ("verdict", "event_type", "task_status"),
        [("partial", None, "active"), ("blocked", "blocked", "blocked")],
    )
    def test_group_stays_on_first_phase(self, engine, verdict, event_type, task_status):
        group = [engine.phase_map["1"], engine.phase_map["2"]]
        events, update = _record_calls(
            engine,
            lambda: engine._record_parallel_transition(group, verdict, "3", step_history_id=55),
        )
        assert events == (
            [(7, 3, event_type, 55), (7, 4, event_type, 55)] if event_type else []
        )
        assert update[-1] == {"current_phase_id": 3, "status": task_status}

    def test_rollback_records_group_and_target(self, engine):
        group = [engine.phase_map["1"], engine.phase_map["2"]]
        events, update = _record_calls(
            engine,
            lambda: engine._record_parallel_transition(
                group, "rollback", None, "0", step_history_id=55
            ),
        )
        assert events == [
            (7, 3, "rolled_back", 55),
            (7, 4, "rolled_back", 55),
            (7, 2, "entered", 55),
        ]
        assert update[-1] == {"current_phase_id": 2, "status": "active"}

    @pytest.mark.parametrize(
        ("verdict", "next_phase", "rollback_target", "message"),
        [
            ("pass", "missing", None, "Следующая фаза"),
            ("rollback", None, None, "Цель отката"),
        ],
    )
    def test_invalid_parallel_target_is_rejected(self, engine, verdict, next_phase, rollback_target, message):
        group = [engine.phase_map["1"], engine.phase_map["2"]]
        with pytest.raises(ConcurrentTransitionError, match=message):
            _record_calls(
                engine,
                lambda: engine._record_parallel_transition(
                    group,
                    verdict,
                    next_phase,
                    rollback_target,
                    step_history_id=55,
                ),
            )

    def test_empty_parallel_group_is_rejected(self, engine):
        with pytest.raises(ConcurrentTransitionError, match="Параллельная группа"):
            _record_calls(
                engine,
                lambda: engine._record_parallel_transition([], "pass", None, step_history_id=55),
            )


# ═══════════════════════════════════════════════════════════════════════
#  evaluate edge cases
# ═══════════════════════════════════════════════════════════════════════


class TestEvaluateEdgeCases:
    def test_orphan_phase_returns_blocked(self):
        with nullcontext():
            engine = SupervisorEngine("RUN-1")
            engine.current_phase_code = "orphan"
            engine.phase_map = {}
            engine.all_phases = []
            engine.task = {
                "id": 7,
                "current_phase_id": 1,
                "current_phase_code": "orphan",
                "status": "active",
                "project_id": 1,
                "workflow_id": 1,
            }
            engine.db = MagicMock()
            result = engine.evaluate("report")
        assert result["verdict"] == "BLOCKED"
        assert result["blockers"] == ["phase-not-configured"]

    def test_sync_evaluate_pass(self, supervisor_llm):
        with nullcontext():
            engine = SupervisorEngine("RUN-1")
            ph = Phase(
                id=1,
                code="-1",
                name="T",
                description="",
                checks=[PhaseCheck(description="deploy")],
                evidence=[],
                instructions=[],
                parallel_with_phase_code=None,
                rollback_target_phase_code=None,
                delegate=None,
            )
            engine.phase_map = {"-1": ph}
            engine.all_phases = [ph]
            engine.current_phase_code = "-1"
            engine.task = {
                "id": 7,
                "current_phase_id": 1,
                "current_phase_code": "-1",
                "status": "active",
                "project_id": 1,
                "workflow_id": 1,
            }
            engine.db = MagicMock()
            engine._reload_evaluation_state = MagicMock()
            engine._refresh_task_state = MagicMock()
            supervisor_llm("PASS", covered=["deploy"])
            result = engine.evaluate("deploy done")
        assert result["verdict"] == "PASS"
        assert "deploy" in result["covered"]

    def test_parallel_evaluate_pass(self, supervisor_llm):
        with nullcontext():
            engine = SupervisorEngine("RUN-1")
            ph_a = Phase(
                id=1,
                code="1",
                name="A",
                description="A",
                execution_type="parallel",
                checks=[PhaseCheck(description="check-a")],
                evidence=[],
                instructions=[],
                parallel_with_phase_code="2",
                rollback_target_phase_code=None,
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
                parallel_with_phase_code="1",
                rollback_target_phase_code=None,
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
            engine.current_phase_code = "1"
            engine.task = {
                "id": 7,
                "current_phase_id": 1,
                "current_phase_code": "1",
                "status": "active",
                "project_id": 1,
                "workflow_id": 1,
            }
            engine.db = MagicMock()
            engine._reload_evaluation_state = MagicMock()
            engine._refresh_task_state = MagicMock()
            supervisor_llm("PASS", covered=["check-a", "check-b"])
            result = engine.evaluate("check-a done and check-b complete")
        assert result["verdict"] == "PASS"
        assert result["phase_name"] == "Параллельная группа: 1, 2"

    def test_parallel_evaluate_partial_stays(self, supervisor_llm):
        with nullcontext():
            engine = SupervisorEngine("RUN-1")
            ph_a = Phase(
                id=1,
                code="1",
                name="A",
                description="A",
                execution_type="parallel",
                checks=[PhaseCheck(description="deploy microservice")],
                evidence=[],
                instructions=[],
                parallel_with_phase_code="2",
                rollback_target_phase_code=None,
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
                parallel_with_phase_code="1",
                rollback_target_phase_code=None,
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
            engine.current_phase_code = "1"
            engine.task = {
                "id": 7,
                "current_phase_id": 1,
                "current_phase_code": "1",
                "status": "active",
                "project_id": 1,
                "workflow_id": 1,
            }
            engine.db = MagicMock()
            engine._reload_evaluation_state = MagicMock()
            engine._refresh_task_state = MagicMock()
            supervisor_llm("PARTIAL", covered=["deploy microservice"], missing=["write unit tests"])
            result = engine.evaluate("microservice deployed")
        assert result["verdict"] == "PARTIAL"
        assert result["next_phase_code"] is None  # non-pass: stay on group
        assert "write unit tests" in result["missing"]
