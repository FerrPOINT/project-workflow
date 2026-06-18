"""Misc edge-case tests — cli/core, cli/ui, wizard_context, wizard_prompt."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner


# ═══════════════════════════════════════════════════════════
# cli/core.py
# ═══════════════════════════════════════════════════════════

class TestOutJson:
    def test_ok_true_exits_0(self):
        from wartz_workflow.cli.core import out_json
        with pytest.raises(SystemExit) as exc:
            out_json({"ok": True})
        assert exc.value.code == 0

    def test_ok_false_exits_1(self):
        from wartz_workflow.cli.core import out_json
        with pytest.raises(SystemExit) as exc:
            out_json({"ok": False})
        assert exc.value.code == 1

    def test_missing_ok_exits_0(self):
        from wartz_workflow.cli.core import out_json
        with pytest.raises(SystemExit) as exc:
            out_json({"data": 1})
        assert exc.value.code == 0


class TestGetTaskKeyValidator:
    def test_no_projects_fallback(self, monkeypatch):
        from wartz_workflow.cli.core import _get_task_key_validator
        db = MagicMock()
        db.get_projects.return_value = []
        monkeypatch.setattr("wartz_workflow.db.WorkflowDB", lambda: db)
        validator = _get_task_key_validator()
        # should not raise and have default patterns
        assert validator is not None


class TestRequireValidKey:
    def test_valid_returns_normalized(self, monkeypatch):
        from wartz_workflow.cli.core import _require_valid_key
        monkeypatch.setattr(
            "wartz_workflow.cli.core._get_task_key_validator",
            lambda: MagicMock(validate=lambda k: MagicMock(is_valid=True, normalized=k.upper(), error_message=None))
        )
        assert _require_valid_key("tst-1") == "TST-1"

    def test_invalid_raises_abort(self, monkeypatch):
        from wartz_workflow.cli.core import _require_valid_key
        monkeypatch.setattr(
            "wartz_workflow.cli.core._get_task_key_validator",
            lambda: MagicMock(validate=lambda k: MagicMock(is_valid=False, normalized=None, error_message="bad"))
        )
        with pytest.raises(click.Abort):
            _require_valid_key("bad")
