"""Tests for configured CLI wrapper installer."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from project_workflow.application.project import ProjectService
from project_workflow.application.workflow import WorkflowService
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.cli.core import CLI_ENTRYPOINT_ENV_VAR, NAMESPACE_ENV_VAR
from scripts.install_namespace_clis import WRAPPER_COMMAND_ERROR, install_namespace_clis

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


def test_install_namespace_clis_wrappers_allow_only_step_and_history(tmp_path):
    generated = install_namespace_clis(tmp_path)
    assert tmp_path / "workflow-run" in generated

    posix = (tmp_path / "workflow-run").read_text(encoding="utf-8")
    cmd = (tmp_path / "workflow-run.cmd").read_text(encoding="utf-8")
    ps1 = (tmp_path / "workflow-run.ps1").read_text(encoding="utf-8")

    assert '"${1:-}" != "step"' in posix
    assert '"${1:-}" != "history"' in posix
    assert WRAPPER_COMMAND_ERROR in posix
    assert 'if "%~1"=="step" goto run' in cmd
    assert 'if "%~1"=="history" goto run' in cmd
    assert "exit /b 2" in cmd
    assert WRAPPER_COMMAND_ERROR in cmd
    assert '$args[0] -ne "step"' in ps1
    assert '$args[0] -ne "history"' in ps1
    assert "exit 2" in ps1
    assert WRAPPER_COMMAND_ERROR in ps1


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
