"""Tests for config.py env overrides and constants."""

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow import config as cfg_module


class TestConfigEnvOverrides:
    def _reload_config(self):
        import importlib

        from project_workflow import config as cfg_module

        cfg_module.get_settings.cache_clear()
        importlib.reload(cfg_module)
        return cfg_module

    def test_workflow_dir_env_override(self, monkeypatch):
        monkeypatch.setenv("WORKFLOW_DIR", "/tmp/custom-workflow")
        cfg_module = self._reload_config()
        assert cfg_module.get_settings().WORKFLOW_DIR == "/tmp/custom-workflow"

    def test_ui_port_env_override(self, monkeypatch):
        monkeypatch.setenv("UI_PORT", "9999")
        cfg_module = self._reload_config()
        assert cfg_module.get_settings().UI_PORT == 9999

    def test_ui_host_env_override(self, monkeypatch):
        monkeypatch.setenv("UI_HOST", "127.0.0.1")
        cfg_module = self._reload_config()
        assert cfg_module.get_settings().UI_HOST == "127.0.0.1"

    def test_jira_base_url_env_override(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://jira.example.com")
        cfg_module = self._reload_config()
        assert cfg_module.get_settings().JIRA_BASE_URL == "https://jira.example.com"

    def test_gitlab_base_url_env_override(self, monkeypatch):
        monkeypatch.setenv("GITLAB_BASE_URL", "https://gitlab.example.com")
        cfg_module = self._reload_config()
        assert cfg_module.get_settings().GITLAB_BASE_URL == "https://gitlab.example.com"


class TestConfigConstants:
    def test_phase_order_nonempty(self):
        assert len(cfg_module.PHASE_ORDER) > 0
        assert "-1" in cfg_module.PHASE_ORDER

    def test_critic_phases_subset_of_order(self):
        for ph in cfg_module.CRITIC_PHASES:
            assert ph in cfg_module.PHASE_ORDER

    def test_delegated_phases_subset_of_order(self):
        for ph in cfg_module.DELEGATED_PHASES:
            assert ph in cfg_module.PHASE_ORDER


class TestSettingsHelpers:
    def test_read_raw_settings_missing_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WORKFLOW_DIR", str(tmp_path / "nonexistent"))
        cfg_module.get_settings.cache_clear()
        raw = cfg_module._read_raw_settings()
        assert raw == {}

    def test_read_raw_settings_bad_json_returns_empty(self, tmp_path, monkeypatch):
        bad_dir = tmp_path / "bad-settings"
        bad_dir.mkdir()
        (bad_dir / "settings.json").write_text("not json")
        monkeypatch.setenv("WORKFLOW_DIR", str(bad_dir))
        cfg_module.get_settings.cache_clear()
        raw = cfg_module._read_raw_settings()
        assert raw == {}

    def test_default_task_key_prefixes(self):
        assert cfg_module.DEFAULT_TASK_KEY_PREFIXES == ["TASK"]

    def test_smoke_task_key_prefixes(self):
        assert cfg_module.SMOKE_TASK_KEY_PREFIXES == ["SMOKE"]
