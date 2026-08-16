"""Tests for the canonical project-workflow CLI."""

from __future__ import annotations

import subprocess
import sys

from click.testing import CliRunner

from project_workflow.interfaces.cli import cli


def test_cli_group_sets_json_mode():
    result = CliRunner().invoke(cli, ["--json", "catalog"])
    assert result.exit_code == 0
    assert '"ok": true' in result.output


def test_cli_exposes_only_canonical_controller_commands():
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    for command in ("catalog", "start", "current", "submit", "history", "evidence-export"):
        assert command in result.output
    assert "step" not in result.output
    assert "v2" not in result.output


def test_fresh_process_can_import_uow_bootstrap_without_wizard_cycle():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
