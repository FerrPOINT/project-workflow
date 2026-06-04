"""Test engine.py helpers.

Import-only для подъёма покрытия.
"""
import os
import pytest
from unittest.mock import patch, MagicMock
from wartz_workflow.models import Phase, PhaseCheck
from wartz_workflow.engine import run_checks, _run_single_check


class TestRunChecks:
    def test_run_checks_file_exist(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")
        phase = Phase(
            id=1, code="0", name="A",
            checks=[PhaseCheck(type="file_exists", path="test.txt")],
        )
        ok, results = run_checks(str(tmp_path), phase, {})
        assert ok is True
        assert len(results) == 1
        assert results[0]["ok"] is True

    def test_run_checks_file_missing(self, tmp_path):
        phase = Phase(
            id=1, code="0", name="A",
            checks=[PhaseCheck(type="file_exists", path="noexist.txt")],
        )
        ok, results = run_checks(str(tmp_path), phase, {})
        assert ok is False
        assert results[0]["ok"] is False

    def test_run_checks_env_var(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "ok")
        phase = Phase(
            id=1, code="0", name="A",
            checks=[PhaseCheck(type="env_var", expected=["MY_VAR"])],
        )
        ok, results = run_checks("/tmp", phase, {})
        assert ok is True
        assert results[0]["ok"] is True

    def test_run_checks_env_var_missing(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        phase = Phase(
            id=1, code="0", name="A",
            checks=[PhaseCheck(type="env_var", expected=["MISSING_VAR"])],
        )
        ok, results = run_checks("/tmp", phase, {})
        assert ok is False
        assert results[0]["ok"] is False

    def test_run_checks_script_pass(self, tmp_path):
        (tmp_path / "run.sh").write_text("#!/bin/bash\necho ok")
        os.chmod(str(tmp_path / "run.sh"), 0o755)
        phase = Phase(
            id=1, code="0", name="A",
            checks=[PhaseCheck(type="script_pass", command=f"{tmp_path / 'run.sh'}")],
        )
        ok, results = run_checks(str(tmp_path), phase, {})
        assert ok is True
        assert results[0]["ok"] is True

    def test_run_checks_dir_exists(self, tmp_path):
        (tmp_path / "somedir").mkdir()
        phase = Phase(
            id=1, code="0", name="A",
            checks=[PhaseCheck(type="dir_exists", path="somedir")],
        )
        ok, results = run_checks(str(tmp_path), phase, {})
        assert ok is True
        assert results[0]["ok"] is True

    @patch("wartz_workflow.adapters.http.jira.JiraAdapter.get_status")
    def test_run_checks_jira_status(self, mock_status):
        mock_status.return_value = "In Progress"
        phase = Phase(
            id=1, code="0", name="A",
            checks=[PhaseCheck(type="jira_status", expected=["In Progress"])],
        )
        ok, results = run_checks("/tmp", phase, {"task_key": "AAT-1"})
        assert ok is True
        assert results[0]["ok"] is True

    def test_run_checks_jira_status_no_match(self):
        phase = Phase(
            id=1, code="0", name="A",
            checks=[PhaseCheck(type="jira_status", expected=["Done"])],
        )
        ok, results = run_checks("/tmp", phase, {"task_key": "AAT-1"})
        assert ok is False
        assert results[0]["ok"] is False


class TestSingleCheck:
    def test_script_pass_no_command(self):
        check = PhaseCheck(type="script_pass")
        ok, detail = _run_single_check("/tmp", check, {})
        assert ok is True

    def test_unknown_check(self):
        check = PhaseCheck(type="unknown")
        ok, detail = _run_single_check("/tmp", check, {})
        assert ok is True
        assert "unknown" in detail.lower()
