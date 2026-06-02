"""Tests for rollback.py — Rollback Engine."""

import pytest

from wartz_workflow import rollback, schema, state


class TestGetPhasesBetween:
    def test_normal_range(self):
        result = rollback.get_phases_between("3", "4.5")
        assert "3" in result
        assert "3.5" in result
        assert "4" in result
        assert "4.5" in result
        assert "5" not in result

    def test_same_phase(self):
        result = rollback.get_phases_between("3.5", "3.5")
        assert result == ["3.5"]

    def test_unknown_phase(self):
        assert rollback.get_phases_between("999", "1000") == []


class TestGetRollbackPlan:
    def test_35_rolls_to_3(self):
        target, clear = rollback.get_rollback_plan("3.5")
        assert target == "3"
        assert "3" in clear
        assert "3.5" in clear
        assert "4" not in clear

    def test_45_rolls_to_4(self):
        target, clear = rollback.get_rollback_plan("4.5")
        assert target == "4"

    def test_75_rolls_to_4(self):
        target, clear = rollback.get_rollback_plan("7.5")
        assert target == "4"
        assert "4" in clear
        assert "7.5" in clear
        assert "8" not in clear

    def test_phase_without_rollback(self):
        target, clear = rollback.get_rollback_plan("0")
        assert target is None
        assert clear == []


class TestCanRollback:
    def test_yes(self):
        assert rollback.can_rollback("3.5")
        assert rollback.can_rollback("4.5")
        assert rollback.can_rollback("7.5")
        assert rollback.can_rollback("7.6")

    def test_no(self):
        assert not rollback.can_rollback("0")
        assert not rollback.can_rollback("1")
        assert not rollback.can_rollback("8")


class TestPerformRollback:
    def test_successful_rollback(self, tmp_path):
        repo = str(tmp_path / "repo")
        # Setup repo/info structure
        (tmp_path / "repo" / "info" / "sprint1").mkdir(parents=True)
        # Setup state
        state.save_state(repo, "AAT-RB", "TASK-001", "sprint1", "7.5")
        st = state.load_state(repo, "AAT-RB")
        st["phases_completed"] = ["0", "1", "2", "3", "3.5", "4", "4.5", "5", "5.5", "6", "7", "7.5"]
        state_dir = tmp_path / ".wartz-workflow" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        import json
        with open(state_dir / "AAT-RB.json", "w") as f:
            json.dump(st, f)

        # Mock WARTZ_DIR
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(state, "WARTZ_DIR", str(tmp_path / ".wartz-workflow"))
            mp.setattr(rollback.state, "WARTZ_DIR", str(tmp_path / ".wartz-workflow"))

            result = rollback.perform_rollback(repo, "AAT-RB", "7.5", "QA FAIL: login broken")

            assert result["from_phase"] == "7.5"
            assert result["to_phase"] == "4"
            assert "7.5" in result["cleared_phases"]
            assert "4.5" in result["cleared_phases"]
            assert "4" in result["cleared_phases"]  # included
            assert result["rollback_count"] == 1

            # Verify state updated
            new_st = state.load_state(repo, "AAT-RB")
            assert new_st["current_phase"] == "4"
            assert "7.5" not in new_st.get("phases_completed", [])
            assert "4.5" not in new_st.get("phases_completed", [])
            assert new_st["rollback_count"] == 1

    def test_no_rollback_target_raises(self, tmp_path):
        repo = str(tmp_path / "repo")
        state.save_state(repo, "AAT-NO", "TASK-002", "sprint1", "0")

        with pytest.raises(rollback.RollbackError):
            rollback.perform_rollback(repo, "AAT-NO", "0", "reason")

    def test_max_cycles(self, tmp_path):
        repo = str(tmp_path / "repo")
        state.save_state(repo, "AAT-MC", "TASK-003", "sprint1", "7.6")
        st = state.load_state(repo, "AAT-MC")
        st["rollback_count"] = 3

        state_dir = tmp_path / ".wartz-workflow" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        import json
        with open(state_dir / "AAT-MC.json", "w") as f:
            json.dump(st, f)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(state, "WARTZ_DIR", str(tmp_path / ".wartz-workflow"))
            info = rollback.get_cycle_info("AAT-MC")
            assert info["cycles"] == 3
            assert info["remaining"] == 0


class TestGetCycleInfo:
    def test_no_state(self):
        info = rollback.get_cycle_info("AAT-NO-STATE")
        assert info["cycles"] == 0
        assert info["max_cycles"] == 3
        assert info["remaining"] == 3
