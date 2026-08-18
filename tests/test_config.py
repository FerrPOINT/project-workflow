"""Tests for config.py env overrides and constants."""

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow import config as cfg_module


class TestConfigEnvOverrides:
    def _reload_config(self):
        import importlib


        cfg_module.get_settings.cache_clear()
        importlib.reload(cfg_module)
        return cfg_module

    def test_ui_port_env_override(self, monkeypatch):
        monkeypatch.setenv("UI_PORT", "9999")
        cfg_module = self._reload_config()
        assert cfg_module.get_settings().UI_PORT == 9999

    def test_ui_host_env_override(self, monkeypatch):
        monkeypatch.setenv("UI_HOST", "127.0.0.1")
        cfg_module = self._reload_config()
        assert cfg_module.get_settings().UI_HOST == "127.0.0.1"
