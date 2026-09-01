"""Tests for configured CLI wrapper installer."""

from __future__ import annotations

from project_workflow.application.project import ProjectService
from project_workflow.application.workflow import WorkflowService
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.cli.core import NAMESPACE_ENV_VAR
from scripts.install_namespace_clis import install_namespace_clis


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
    assert f"{NAMESPACE_ENV_VAR}={qa_namespace_id}" in (tmp_path / "workflow-qa-wrap").read_text(encoding="utf-8")
    assert f'set "{NAMESPACE_ENV_VAR}={qa_namespace_id}"' in (tmp_path / "workflow-qa-wrap.cmd").read_text(
        encoding="utf-8"
    )
    assert f"$env:{NAMESPACE_ENV_VAR} = \"{qa_namespace_id}\"" in (tmp_path / "workflow-qa-wrap.ps1").read_text(
        encoding="utf-8"
    )
