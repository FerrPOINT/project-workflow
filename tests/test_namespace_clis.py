"""Tests for configured CLI wrapper installer."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from project_workflow.application.project import ProjectService
from project_workflow.application.workflow import WorkflowService
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.cli.core import CLI_ENTRYPOINT_ENV_VAR, NAMESPACE_ENV_VAR
from scripts.install_namespace_clis import MANIFEST_NAME, WRAPPER_COMMAND_ERROR, install_namespace_clis

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_install_namespace_clis_generates_wrappers_for_all_records(tmp_path):
    with SAUnitOfWork() as uow:
        default_namespace = uow.projects.get_by_code("RUN")
        assert default_namespace is not None and default_namespace.id is not None
        qa_workflow = WorkflowService(uow).create_workflow({"name": "QA wrappers flow"})
        qa_namespace = ProjectService(uow).create_project(
            {
                "code": "QAWRAP",
                "name": "QA Wrappers",
                "workflow_id": qa_workflow["id"],
                "cli_command": "workflow-qa-wrap",
                "key_prefixes": ["RUN"],
            }
        )
        default_namespace_id = default_namespace.id
        qa_namespace_id = qa_namespace["id"]

    generated = install_namespace_clis(tmp_path)

    assert tmp_path / "workflow-run" in generated
    assert tmp_path / "workflow-run.cmd" in generated
    assert tmp_path / "workflow-run.ps1" in generated
    assert tmp_path / "workflow-qa-wrap" in generated
    assert tmp_path / "workflow-qa-wrap.cmd" in generated
    assert tmp_path / "workflow-qa-wrap.ps1" in generated
    assert f"{NAMESPACE_ENV_VAR}={default_namespace_id}" in (tmp_path / "workflow-run").read_text(encoding="utf-8")
    qa_posix = (tmp_path / "workflow-qa-wrap").read_text(encoding="utf-8")
    assert f"{NAMESPACE_ENV_VAR}={qa_namespace_id}" in qa_posix
    assert f"{CLI_ENTRYPOINT_ENV_VAR}=workflow-qa-wrap" in qa_posix
    assert f'set "{NAMESPACE_ENV_VAR}={qa_namespace_id}"' in (tmp_path / "workflow-qa-wrap.cmd").read_text(
        encoding="utf-8"
    )
    assert f'set "{CLI_ENTRYPOINT_ENV_VAR}=workflow-qa-wrap"' in (
        tmp_path / "workflow-qa-wrap.cmd"
    ).read_text(encoding="utf-8")
    assert f"$env:{NAMESPACE_ENV_VAR} = \"{qa_namespace_id}\"" in (tmp_path / "workflow-qa-wrap.ps1").read_text(
        encoding="utf-8"
    )
    assert f"$env:{CLI_ENTRYPOINT_ENV_VAR} = \"workflow-qa-wrap\"" in (
        tmp_path / "workflow-qa-wrap.ps1"
    ).read_text(encoding="utf-8")


def test_install_namespace_clis_wrappers_allow_only_step_history_and_builtin_help(tmp_path):
    generated = install_namespace_clis(tmp_path)
    assert tmp_path / "workflow-run" in generated

    posix = (tmp_path / "workflow-run").read_text(encoding="utf-8")
    cmd = (tmp_path / "workflow-run.cmd").read_text(encoding="utf-8")
    ps1 = (tmp_path / "workflow-run.ps1").read_text(encoding="utf-8")

    assert '"${1:-}" != "step"' in posix
    assert '"${1:-}" != "history"' in posix
    assert '"${1:-}" != "--help"' in posix
    assert '"${1:-}" != "--version"' in posix
    assert WRAPPER_COMMAND_ERROR in posix
    assert 'if "%~1"=="step" goto run' in cmd
    assert 'if "%~1"=="history" goto run' in cmd
    assert 'if "%~1"=="--help" goto run' in cmd
    assert 'if "%~1"=="--version" goto run' in cmd
    assert "exit /b 2" in cmd
    assert WRAPPER_COMMAND_ERROR in cmd
    assert '$args[0] -ne "step"' in ps1
    assert '$args[0] -ne "history"' in ps1
    assert '$args[0] -ne "--help"' in ps1
    assert '$args[0] -ne "--version"' in ps1
    assert "exit 2" in ps1
    assert WRAPPER_COMMAND_ERROR in ps1


@pytest.mark.parametrize("suffix", ["", ".cmd", ".ps1"])
def test_install_namespace_clis_refuses_to_overwrite_unmanaged_command_file(tmp_path, suffix):
    protected = tmp_path / f"workflow-run{suffix}"
    protected.write_text("user-owned", encoding="utf-8")

    with pytest.raises(ValueError, match="уже существует"):
        install_namespace_clis(tmp_path)

    assert protected.read_text(encoding="utf-8") == "user-owned"
    for generated_suffix in ("", ".cmd", ".ps1"):
        generated = tmp_path / f"workflow-run{generated_suffix}"
        if generated != protected:
            assert not generated.exists()


def test_install_namespace_clis_removes_renamed_managed_wrappers(tmp_path):
    with SAUnitOfWork() as uow:
        default_namespace = uow.projects.get_by_code("RUN")
        assert default_namespace is not None and default_namespace.id is not None
        ProjectService(uow).update_project(default_namespace.id, {"cli_command": "workflow-before"})

    unmanaged_file = tmp_path / "workflow-user-script"
    unmanaged_file.write_text("user-owned", encoding="utf-8")
    install_namespace_clis(tmp_path)
    assert (tmp_path / "workflow-before").is_file()
    assert (tmp_path / "workflow-before.cmd").is_file()
    assert (tmp_path / "workflow-before.ps1").is_file()

    with SAUnitOfWork() as uow:
        default_namespace = uow.projects.get_by_code("RUN")
        assert default_namespace is not None and default_namespace.id is not None
        ProjectService(uow).update_project(default_namespace.id, {"cli_command": "workflow-after"})

    install_namespace_clis(tmp_path)

    assert (tmp_path / "workflow-after").is_file()
    assert (tmp_path / "workflow-after.cmd").is_file()
    assert (tmp_path / "workflow-after.ps1").is_file()
    assert not (tmp_path / "workflow-before").exists()
    assert not (tmp_path / "workflow-before.cmd").exists()
    assert not (tmp_path / "workflow-before.ps1").exists()
    assert unmanaged_file.read_text(encoding="utf-8") == "user-owned"


def test_install_namespace_clis_does_not_remove_unmarked_manifest_file(tmp_path):
    protected_file = tmp_path / "workflow-protected"
    protected_file.write_text("user-owned", encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(
        json.dumps({"managed_files": ["workflow-protected"]}),
        encoding="utf-8",
    )

    install_namespace_clis(tmp_path)

    assert protected_file.read_text(encoding="utf-8") == "user-owned"


def test_install_namespace_clis_missing_database_url_fails_without_traceback(tmp_path):
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.update({"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252"})

    result = subprocess.run(
        [sys.executable, "scripts/install_namespace_clis.py", "--bin-dir", str(tmp_path)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 1
    assert result.stderr.decode("utf-8").strip() == "Переменная DATABASE_URL обязательна"
    assert b"Traceback" not in result.stderr
