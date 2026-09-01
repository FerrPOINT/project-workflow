"""Tests for interfaces.ui.cli_reference."""

from __future__ import annotations

from project_workflow.interfaces.ui.cli_reference import _load_cli_reference


def test_cli_reference_loads_commands():
    commands = _load_cli_reference()
    assert isinstance(commands, list)
    assert len(commands) > 0
    # Hidden/internal commands are skipped.
    names = [cmd["name"] for cmd in commands]
    assert "ui" not in names
    for cmd in commands:
        assert "name" in cmd
        assert "usage" in cmd
        assert "summary" in cmd
        assert "help" in cmd
        assert "options" in cmd
        assert isinstance(cmd["options"], list)


def test_cli_reference_can_render_namespace_entrypoint():
    commands = _load_cli_reference(entrypoint="workflow-qa")

    usages = {cmd["name"]: cmd["usage"] for cmd in commands}
    assert usages["step"] == "workflow-qa step"
    assert usages["history"] == "workflow-qa history"
    assert all(not usage.startswith("project-workflow ") for usage in usages.values())
