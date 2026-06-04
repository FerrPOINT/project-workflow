"""Тесты модуля phases.py."""

import pytest

from wartz_workflow import phases
from wartz_workflow.config import PHASE_ORDER


class TestGetNextPhase:
    def test_next(self):
        assert phases.get_next_phase("-1") == "0.0a"
        assert phases.get_next_phase("0.0a") == "0.01"
        assert phases.get_next_phase("8") == "9"
        assert phases.get_next_phase("9") == "10"

    def test_last(self):
        assert phases.get_next_phase("10") is None

    def test_unknown(self):
        assert phases.get_next_phase("999") is None


class TestGetPhaseChecklistRaw:
    def test_known_phase(self):
        items = phases.get_phase_checklist_raw("0")
        assert len(items) >= 3
        assert "Jira" in items[0]

    def test_unknown_phase(self):
        items = phases.get_phase_checklist_raw("nonexistent")
        assert items == []


class TestConditionalDelegateJump:
    def test_no_condition_returns_false(self):
        jumped, msg, target = phases.conditional_delegate_jump(
            "/tmp", "AAT-123", "5", None, None, {}
        )
        assert jumped is False
        assert "No delegate condition" in msg
        assert target is None

    def test_false_condition_no_jump(self, monkeypatch):
        def fake_eval(condition, repo, task_key, context):
            return False
        monkeypatch.setattr(phases, "_evaluate_condition", fake_eval)

        jumped, msg, target = phases.conditional_delegate_jump(
            "/tmp", "AAT-123", "5", "test -f /nonexistent", "7", {}
        )
        assert jumped is False
        assert "Condition false" in msg
        assert target is None

    def test_forward_jump_marks_intermediate(self, tmp_path, monkeypatch):
        from pathlib import Path
        # Setup fake state
        repo = str(tmp_path / "repo")
        task_key = "AAT-999"
        state_dir = Path.home() / ".wartz-workflow" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / f"{task_key}.json").write_text(
            '{"task_key":"AAT-999","phases_completed":[],"current_phase":"5"}',
            encoding="utf-8"
        )

        # Patch progress.json helpers to avoid needing repo/info structure
        import wartz_workflow.state as state_mod
        monkeypatch.setattr(state_mod, "update_task_progress", lambda repo, task_key, phase, evidence: None)

        def fake_eval(condition, repo, task_key, context):
            return True
        monkeypatch.setattr(phases, "_evaluate_condition", fake_eval)

        jumped, msg, target = phases.conditional_delegate_jump(
            repo, task_key, "5", "true", "7", {}
        )
        assert jumped is True
        assert target == "7"
        st = phases.state.load_state(repo, task_key)
        assert st is not None
        completed = st.get("phases_completed", [])
        assert "5" in completed
        assert "6" in completed
        assert "7" in completed

    def test_backward_jump_unmarks_phases(self, tmp_path, monkeypatch):
        from pathlib import Path
        repo = str(tmp_path / "repo")
        task_key = "AAT-998"
        state_dir = Path.home() / ".wartz-workflow" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / f"{task_key}.json").write_text(
            '{"task_key":"AAT-998","phases_completed":["5","6","7"],"current_phase":"7"}',
            encoding="utf-8"
        )

        import wartz_workflow.state as state_mod
        monkeypatch.setattr(state_mod, "_set_phase_progress_status", lambda repo, task_key, phase, status: None)

        def fake_eval(condition, repo, task_key, context):
            return True
        monkeypatch.setattr(phases, "_evaluate_condition", fake_eval)

        jumped, msg, target = phases.conditional_delegate_jump(
            repo, task_key, "7", "true", "5", {}
        )
        assert jumped is True
        assert target == "5"
        st = phases.state.load_state(repo, task_key)
        assert st is not None
        completed = set(st.get("phases_completed", []))
        assert "6" not in completed
        assert "7" not in completed
        assert st.get("current_phase") == "5"


class TestEvaluateCondition:
    def test_true_command(self):
        assert phases._evaluate_condition("true", "/tmp", "AAT-1", {}) is True

    def test_false_command(self):
        assert phases._evaluate_condition("false", "/tmp", "AAT-1", {}) is False

    def test_context_substitution(self):
        assert phases._evaluate_condition("test -d {repo}", "/tmp", "AAT-1", {"repo": "/tmp"}) is True
        assert phases._evaluate_condition("test -d {repo}", "/tmp", "AAT-1", {"repo": "/nonexistent"}) is False
