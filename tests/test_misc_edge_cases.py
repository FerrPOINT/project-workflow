"""Misc edge-case tests — cli/core, cli/ui, supervisor_context, supervisor_prompt."""

from __future__ import annotations

from unittest.mock import MagicMock

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
    def test_no_projects_fallback(self, monkeypatch):
        from project_workflow.interfaces.cli.core import _get_task_key_validator

        db = MagicMock()
        db.get_projects.return_value = []
        monkeypatch.setattr("project_workflow.infrastructure.db.uow.SAUnitOfWork", lambda: db)
        validator = _get_task_key_validator()
        # should not raise and have default patterns
        assert validator is not None

    def test_empty_database_does_not_invent_task_prefixes(self):
        from project_workflow.interfaces.cli.core import _get_task_key_validator

        uow = MagicMock()
        uow.projects.list.return_value = []
        validator = _get_task_key_validator(uow=uow)
        result = validator.validate("RUN-1")
        assert not result.is_valid


class TestRequireValidKey:
    def test_valid_returns_normalized(self, monkeypatch):
        from project_workflow.interfaces.cli.core import _require_valid_key

        monkeypatch.setattr(
            "project_workflow.interfaces.cli.core._get_task_key_validator",
            lambda: MagicMock(validate=lambda k: MagicMock(is_valid=True, normalized=k.upper(), error_message=None)),
        )
        assert _require_valid_key("tst-1") == "TST-1"

    def test_invalid_raises_validation_error(self, monkeypatch):
        from project_workflow.domain.validation import TaskKeyValidationError
        from project_workflow.interfaces.cli.core import _require_valid_key

        monkeypatch.setattr(
            "project_workflow.interfaces.cli.core._get_task_key_validator",
            lambda: MagicMock(validate=lambda k: MagicMock(is_valid=False, normalized=None, error_message="bad")),
        )
        with pytest.raises(TaskKeyValidationError, match="bad"):
            _require_valid_key("bad")
