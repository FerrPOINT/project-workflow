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
        assert cfg_module.WORKFLOW_DIR == "/tmp/custom-workflow"

    def test_ui_port_env_override(self, monkeypatch):
        monkeypatch.setenv("UI_PORT", "9999")
        cfg_module = self._reload_config()
        assert cfg_module.UI_PORT == 9999

    def test_ui_host_env_override(self, monkeypatch):
        monkeypatch.setenv("UI_HOST", "127.0.0.1")
        cfg_module = self._reload_config()
        assert cfg_module.UI_HOST == "127.0.0.1"

    def test_jira_base_url_env_override(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://jira.example.com")
        cfg_module = self._reload_config()
        assert cfg_module.JIRA_BASE_URL == "https://jira.example.com"

    def test_gitlab_base_url_env_override(self, monkeypatch):
        monkeypatch.setenv("GITLAB_BASE_URL", "https://gitlab.example.com")
        cfg_module = self._reload_config()
        assert cfg_module.GITLAB_BASE_URL == "https://gitlab.example.com"


class TestConfigConstants:
    def test_phase_order_nonempty(self):
        assert len(cfg_module.PHASE_ORDER) > 0
        assert "-1" in cfg_module.PHASE_ORDER

    def test_legacy_redirects(self):
        assert cfg_module.LEGACY_PHASE_REDIRECTS["0"] == "0.00"

    def test_critic_phases_subset_of_order(self):
        for ph in cfg_module.CRITIC_PHASES:
            assert ph in cfg_module.PHASE_ORDER

    def test_delegated_phases_subset_of_order(self):
        for ph in cfg_module.DELEGATED_PHASES:
            assert ph in cfg_module.PHASE_ORDER


class TestSettingsHelpers:
    def test_read_raw_settings_missing_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg_module, "SETTINGS_PATH", str(tmp_path / "no_settings.json"))
        raw = cfg_module._read_raw_settings()
        assert raw == {}

    def test_read_raw_settings_bad_json_returns_empty(self, tmp_path, monkeypatch):
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        monkeypatch.setattr(cfg_module, "SETTINGS_PATH", str(bad))
        raw = cfg_module._read_raw_settings()
        assert raw == {}

    def test_default_task_key_prefixes(self):
        assert cfg_module.DEFAULT_TASK_KEY_PREFIXES == ["TASK"]

    def test_smoke_task_key_prefixes(self):
        assert cfg_module.SMOKE_TASK_KEY_PREFIXES == ["SMOKE"]
