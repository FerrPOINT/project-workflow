"""Misc edge-case tests — cli/core, cli/ui, supervisor_context, supervisor_prompt."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

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


@pytest.mark.parametrize("command", ["step", "history"])
def test_unconfigured_cli_rejects_without_opening_database_or_network(monkeypatch, command):
    from project_workflow.interfaces.cli import ui  # noqa: F401 -- register commands
    from project_workflow.interfaces.cli.core import cli

    def forbidden(*args, **kwargs):
        raise AssertionError("Missing CLI configuration must not open a DB or network")

    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "platform")
    monkeypatch.delenv("PROJECT_WORKFLOW_URL", raising=False)
    monkeypatch.setattr("project_workflow.infrastructure.db.uow.SAUnitOfWork.__init__", forbidden)
    monkeypatch.setattr("requests.Session.request", forbidden)
    result = CliRunner().invoke(cli, ["--json", command, "--task", "RUN-1"])
    assert result.exit_code != 0
    assert json.loads(result.output)["error_code"] == "configuration-or-input-invalid"


class TestRequireValidKey:
    def test_valid_returns_normalized(self):
        from project_workflow.interfaces.cli.core import _require_valid_key

        assert _require_valid_key("TST-1") == "TST-1"

    def test_invalid_raises_validation_error(self):
        from project_workflow.domain.validation import TaskKeyValidationError
        from project_workflow.interfaces.cli.core import _require_valid_key

        with pytest.raises(TaskKeyValidationError, match="строчные буквы"):
            _require_valid_key("bad")
