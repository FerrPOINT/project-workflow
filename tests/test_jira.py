"""Test Jira HTTP adapter with mocked _request."""

from unittest.mock import Mock, patch
import pytest

from wartz_workflow.adapters.http.jira import JiraAdapter


class TestJiraAdapter:
    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch):
        monkeypatch.setenv("JIRA_USER", "testuser")
        monkeypatch.setenv("JIRA_TOKEN", "testtoken")

    def _make_ok(self, data):
        m = Mock()
        m._request.return_value = (True, data)
        return m

    def test_get_status_success(self):
        adapter = JiraAdapter()
        with patch.object(adapter, "_request", return_value=(True, {"fields": {"status": {"name": "Open"}}})):
            assert adapter.get_status("AAT-1") == "Open"

    def test_get_status_failure(self):
        adapter = JiraAdapter()
        with patch.object(adapter, "_request", return_value=(False, {})):
            assert adapter.get_status("AAT-999") is None

    def test_get_task_info(self):
        adapter = JiraAdapter()
        data = {"key": "AAT-1", "fields": {"summary": "T", "description": "D", "status": {"name": "Open"}}}
        with patch.object(adapter, "_request", return_value=(True, data)):
            info = adapter.get_task_info("AAT-1")
            assert info["key"] == "AAT-1"
            assert info["summary"] == "T"

    def test_get_transitions(self):
        adapter = JiraAdapter()
        data = {"transitions": [{"id": "31", "name": "In Progress"}]}
        with patch.object(adapter, "_request", return_value=(True, data)):
            transitions = adapter.get_transitions("AAT-1")
            assert len(transitions) == 1
            assert transitions[0]["name"] == "In Progress"

    def test_transition(self):
        adapter = JiraAdapter()
        with patch.object(adapter, "_request") as mock_req:
            mock_req.side_effect = [
                (True, {"transitions": [{"id": "31", "name": "In Progress"}]}),
                (True, {}),
            ]
            ok, msg = adapter.transition("AAT-1", "In Progress")
            assert ok is True

    def test_ping(self):
        adapter = JiraAdapter()
        with patch.object(adapter, "_request", return_value=(True, {"key": "AAT-1"})):
            ok, msg = adapter.ping()
            assert ok is True
