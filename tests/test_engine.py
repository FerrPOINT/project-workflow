"""Tests for engine.py — Workflow Engine."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest

from wartz_workflow.engine import (
    build_context,
    execute_phase,
    get_delegate_command,
    get_parallel_phases,
    render_phase_playbook,
    run_checks,
    _run_single_check,
)
from wartz_workflow.schema import Phase


def _make_check(type_name, desc="", path="", cmd="", expected=None, optional=False):
    """Build a duck-typed check object (engine.py uses .type, .description, .path, .command, .expected, .optional)."""
    return SimpleNamespace(
        type=type_name, description=desc, path=path, command=cmd,
        expected=expected, optional=optional,
    )


def _make_phase(**overrides):
    defaults = {
        "id": "0",
        "name": "Setup",
        "description": "D",
        "instructions": [],
        "evidence": [],
        "checks": [],
        "skills": [],
        "is_blocker": False,
        "is_delegated": False,
        "is_critic": False,
        "next_recommendation": "",
        "delegate": None,
        "min_time_min": 0,
        "parallel_with": None,
        "execution_type": "sync",
    }
    defaults.update(overrides)
    return Phase(**defaults)


# --- build_context ---

class TestBuildContext:
    def test_keys_present(self):
        ctx = build_context("/repo", "AAT-1", "TASK-001", "sprint42")
        assert ctx["repo"] == "/repo"
        assert ctx["jira_key"] == "AAT-1"
        assert ctx["task_id"] == "TASK-001"
        assert ctx["sprint"] == "sprint42"
        assert "jira_url" in ctx
        assert "verify_suite_script" in ctx
        assert "gitlab_url" in ctx


# --- run_checks / _run_single_check ---

class TestRunChecks:
    def test_empty_checks_true(self):
        phase = _make_phase(checks=[])
        ok, results = run_checks("/repo", phase, {})
        assert ok is True
        assert results == []

    @patch("os.path.isfile", return_value=True)
    def test_file_exists_pass(self, _mock_isfile):
        check = _make_check("file_exists", path="x.txt")
        ok, detail = _run_single_check("/repo", check, {})
        assert ok is True
        assert "Found" in detail

    @patch("os.path.isdir", return_value=False)
    def test_dir_exists_fail(self, _mock_isdir):
        check = _make_check("dir_exists", path="missing")
        ok, detail = _run_single_check("/repo", check, {})
        assert ok is False
        assert "Missing" in detail

    @patch("wartz_workflow.engine.subprocess.run")
    def test_script_pass(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        check = _make_check("script_pass", cmd="echo ok")
        ok, detail = _run_single_check("/repo", check, {})
        assert ok is True
        assert "exit=0" in detail

    @patch.dict(os.environ, {"JIRA_TOKEN": "abc"}, clear=True)
    def test_env_var_pass(self):
        check = _make_check("env_var", expected=["JIRA_TOKEN"])
        ok, detail = _run_single_check("/repo", check, {})
        assert ok is True
        assert "All present" in detail

    def test_unknown_check_type(self):
        check = _make_check("mystery")
        ok, detail = _run_single_check("/repo", check, {})
        assert ok is True  # unknown → pass gracefully
        assert "Unknown check type" in detail

    @patch("wartz_workflow.engine._jira.ping", return_value=(True, "pong"))
    def test_api_ping_jira(self, mock_ping):
        check = _make_check("api_ping", desc="Check Jira ping")
        ok, detail = _run_single_check("/repo", check, {})
        assert ok is True
        assert detail == "pong"

    def test_optional_does_not_fail_all(self):
        phase = _make_phase(checks=[
            _make_check("file_exists", path="no", optional=False),
            _make_check("file_exists", path="no2", optional=True),
        ])
        with patch("os.path.isfile", return_value=False):
            ok, results = run_checks("/repo", phase, {})
        assert ok is False  # non-optional failed
        assert results[0]["optional"] is False
        assert results[1]["optional"] is True


# --- render_phase_playbook ---

class TestRenderPhasePlaybook:
    def test_basic(self):
        phase = _make_phase(
            id="0.01",
            name="Info",
            instructions=[],
            skills=["file"],
        )
        ctx = {"repo": "/repo", "jira_key": "AAT-1"}
        pb = render_phase_playbook(phase, ctx)
        assert pb["phase_id"] == "0.01"
        assert pb["is_delegated"] is False
        assert pb["delegate"] is None
        assert pb["skills"] == ["file"]

    def test_delegated(self):
        phase = _make_phase(
            id="0.6",
            name="Research",
            is_delegated=True,
            delegate=SimpleNamespace(
                agent="wartzresearcher",
                prompt_template="Research {{jira_key}}",
                toolsets=["web"],
                timeout_min=30,
            ),
        )
        ctx = {"jira_key": "AAT-1"}
        pb = render_phase_playbook(phase, ctx)
        assert pb["is_delegated"] is True
        assert pb["delegate"]["agent"] == "wartzresearcher"
        assert "AAT-1" in pb["delegate"]["prompt"]
        assert pb["delegate"]["toolsets"] == ["web"]


# --- execute_phase ---

class TestExecutePhase:
    @patch("wartz_workflow.engine.schema.get_phase")
    @patch("wartz_workflow.engine.state.load_state")
    def test_unknown_phase(self, mock_load, mock_get):
        mock_get.return_value = None
        ok, result = execute_phase("/repo", "AAT-1", "999")
        assert ok is False
        assert "Unknown phase" in result["error"]

    @patch("wartz_workflow.engine.schema.get_phase")
    @patch("wartz_workflow.engine.state.load_state")
    def test_task_not_initialized(self, mock_load, mock_get):
        mock_get.return_value = _make_phase(id="0")
        mock_load.return_value = None
        ok, result = execute_phase("/repo", "AAT-1", "0")
        assert ok is False
        assert "not initialized" in result["error"]

    @patch("wartz_workflow.engine.schema.get_phase")
    @patch("wartz_workflow.engine.state.load_state")
    @patch("wartz_workflow.engine.run_checks", return_value=(True, []))
    @patch("wartz_workflow.engine.state.mark_phase_complete")
    def test_passed_non_delegated(self, mock_mark, mock_checks, mock_load, mock_get):
        mock_get.return_value = _make_phase(id="0.01", is_delegated=False)
        mock_load.return_value = {"task_id": "TASK-001", "sprint": "s1", "title": "T"}
        ok, result = execute_phase("/repo", "AAT-1", "0.01")
        assert ok is True
        assert result["is_complete"] is True
        assert result["delegate_payload"] is None

    @patch("wartz_workflow.engine.schema.get_phase")
    @patch("wartz_workflow.engine.state.load_state")
    @patch("wartz_workflow.engine.run_checks", return_value=(False, []))
    def test_checks_fail(self, mock_checks, mock_load, mock_get):
        mock_get.return_value = _make_phase(id="0.01")
        mock_load.return_value = {"task_id": "TASK-001", "sprint": "s1", "title": "T"}
        ok, result = execute_phase("/repo", "AAT-1", "0.01")
        assert ok is False
        assert result["is_complete"] is False


# --- get_parallel_phases ---

class TestGetParallelPhases:
    @patch("wartz_workflow.engine.schema.get_phase_from_db")
    @patch("wartz_workflow.engine.schema.load_phases_from_db")
    def test_no_parallel(self, mock_load, mock_get):
        mock_get.return_value = SimpleNamespace(parallel_with=None)
        mock_load.return_value = []
        result = get_parallel_phases("1")
        assert result == []

    @patch("wartz_workflow.engine.schema.get_phase_from_db")
    @patch("wartz_workflow.engine.schema.load_phases_from_db")
    def test_with_parallel(self, mock_load, mock_get):
        phase = SimpleNamespace(parallel_with="1.5")
        phase.id = "1"
        mock_get.return_value = phase
        mock_load.return_value = []
        result = get_parallel_phases("1")
        assert result == ["1.5"]


# --- get_delegate_command ---

class TestGetDelegateCommand:
    @patch("wartz_workflow.engine.profiles.build_delegate_payload")
    def test_returns_command(self, mock_build):
        mock_build.return_value = {
            "agent": "wartzcoder",
            "role": "leaf",
            "goal": "Write code",
            "context": "Task AAT-1",
            "toolsets": ["terminal", "file"],
        }
        cmd = get_delegate_command("1", "AAT-1", "TASK-001", "Fix bug")
        assert cmd is not None
        assert cmd["tool"] == "delegate_task"
        assert cmd["role"] == "leaf"
        assert cmd["goal"] == "Write code"
        assert "terminal" in cmd["toolsets"]

    @patch("wartz_workflow.engine.profiles.build_delegate_payload")
    def test_none_when_no_payload(self, mock_build):
        mock_build.return_value = None
        cmd = get_delegate_command("0", "AAT-1", "TASK-001", "Setup")
        assert cmd is None
