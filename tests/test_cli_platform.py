"""Retired CLI file flags cannot open a second execution transport."""

import pytest
from click.testing import CliRunner

from project_workflow.interfaces.cli import ui  # noqa: F401 -- register commands
from project_workflow.interfaces.cli.core import cli


@pytest.mark.parametrize("command", ["step", "history"])
@pytest.mark.parametrize("flag", ["--runtime-request", "--execution-token-file"])
def test_retired_file_flags_are_rejected_before_reading_private_material(tmp_path, command, flag):
    private = tmp_path / "retired-private.json"
    private.write_text("private-credential-must-not-be-read", encoding="utf-8")
    result = CliRunner().invoke(cli, ["--json", command, "--task", "RUN-7", flag, str(private)])
    assert result.exit_code == 2
    assert flag in result.output
    assert all(flag not in param.opts for param in cli.commands[command].params)
    assert "private-credential-must-not-be-read" not in result.output
