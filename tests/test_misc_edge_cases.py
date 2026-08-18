"""Misc edge-case tests — cli/core, cli/ui, wizard_context, wizard_prompt."""

from __future__ import annotations

from unittest.mock import MagicMock

import click
import pytest

pytestmark = [pytest.mark.cli]


# ═══════════════════════════════════════════════════════════
# cli/core.py
# ═══════════════════════════════════════════════════════════


class TestOutJson:
    def test_ok_true_exits_0(self):
        from project_workflow.interfaces.cli.core import out_json

        with pytest.raises(SystemExit) as exc:
            out_json({"ok": True})
        assert exc.value.code == 0

    def test_ok_false_exits_1(self):
        from project_workflow.interfaces.cli.core import out_json

        with pytest.raises(SystemExit) as exc:
            out_json({"ok": False})
        assert exc.value.code == 1

    def test_missing_ok_exits_0(self):
        from project_workflow.interfaces.cli.core import out_json

        with pytest.raises(SystemExit) as exc:
            out_json({"data": 1})
        assert exc.value.code == 0


class TestGetTaskKeyValidator:
    def test_no_projects_is_fail_closed(self):
        from project_workflow.interfaces.cli.core import _get_task_key_validator

        db = MagicMock()
        db.projects.list.return_value = []
        validator = _get_task_key_validator(db)
        assert not validator.validate("TASK-1").is_valid

    def test_does_not_bootstrap_default_project(self, tmp_path, monkeypatch):
        from project_workflow.interfaces.cli.core import _get_task_key_validator

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
        validator = _get_task_key_validator()
        assert not validator.validate("TASK-1").is_valid


class TestRequireValidKey:
    def test_valid_returns_normalized(self, monkeypatch):
        from project_workflow.interfaces.cli.core import _require_valid_key

        monkeypatch.setattr(
            "project_workflow.interfaces.cli.core._get_task_key_validator",
            lambda: MagicMock(validate=lambda k: MagicMock(is_valid=True, normalized=k.upper(), error_message=None)),
        )
        assert _require_valid_key("tst-1") == "TST-1"

    def test_invalid_raises_abort(self, monkeypatch):
        from project_workflow.interfaces.cli.core import _require_valid_key

        monkeypatch.setattr(
            "project_workflow.interfaces.cli.core._get_task_key_validator",
            lambda: MagicMock(validate=lambda k: MagicMock(is_valid=False, normalized=None, error_message="bad")),
        )
        with pytest.raises(click.Abort):
            _require_valid_key("bad")
