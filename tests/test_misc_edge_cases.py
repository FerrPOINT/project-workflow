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

    def test_empty_database_accepts_generic_task_shape(self):
        from project_workflow.interfaces.cli.core import _get_task_key_validator

        uow = MagicMock()
        uow.projects.list.return_value = []
        validator = _get_task_key_validator(uow=uow)
        result = validator.validate("RUN-1")
        assert result.is_valid
        assert result.project is None


class TestRequireValidKey:
    def test_valid_returns_normalized(self):
        from project_workflow.interfaces.cli.core import _require_valid_key

        assert _require_valid_key("TST-1") == "TST-1"

    def test_invalid_raises_validation_error(self):
        from project_workflow.domain.validation import TaskKeyValidationError
        from project_workflow.interfaces.cli.core import _require_valid_key

        with pytest.raises(TaskKeyValidationError, match="строчные буквы"):
            _require_valid_key("bad")
