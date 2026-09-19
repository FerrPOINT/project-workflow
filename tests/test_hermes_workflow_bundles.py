from __future__ import annotations

from pathlib import Path

import pytest

from project_workflow.infrastructure.db.uow import SAUnitOfWork
from scripts.install_hermes_workflow import install, load_bundle

CONFIG_ROOT = Path(__file__).resolve().parents[1] / "configs" / "hermes"
LOCAL_RUNTIME_SKILLS = {
    "relevanter-business-operator",
    "relevanter-project-context",
    "relevanter-tech-operator",
    "project-workflow-executor",
    "deployed-acceptance",
    "exact-sha-deployment",
}


def test_seven_clean_role_namespace_bundles_are_complete() -> None:
    paths = sorted(CONFIG_ROOT.glob("*.json"))
    assert [path.stem for path in paths] == [
        "analyst",
        "architect",
        "developer",
        "devops",
        "project_manager",
        "reviewer",
        "tester",
    ]
    bundles = [load_bundle(path) for path in paths]
    assert len({bundle["namespace"] for bundle in bundles}) == 7
    assert all(bundle["skillsHub"]["commit"] == "50b92c54e0e04c510c9669dfb52dab0d4632d028" for bundle in bundles)
    developer = next(bundle for bundle in bundles if bundle["role"] == "developer")
    assert [mode["key"] for mode in developer["workflow"]["modes"]] == ["initial", "rework"]
    assert all(mode["key"] != "default" for bundle in bundles for mode in bundle["workflow"]["modes"])


def test_every_terminal_phase_prepares_handoff_before_terminal_action() -> None:
    for path in CONFIG_ROOT.glob("*.json"):
        bundle = load_bundle(path)
        for mode in bundle["workflow"]["modes"]:
            terminal = mode["phases"][-1]
            text = " ".join(item["text"] for item in terminal["instructions"]).lower()
            assert "markdown" in text or "комментар" in text, f"{path.name}/{mode['key']}"
            assert "workflow_phase complete" in text, f"{path.name}/{mode['key']}"
            assert "terminal action не вызывать" in text, f"{path.name}/{mode['key']}"
            assert "publish_task_draft" not in text, f"{path.name}/{mode['key']}"
            assert "complete_assigned_stage" not in text, f"{path.name}/{mode['key']}"


def test_project_manager_publication_hands_backlog_to_analyst_automatically() -> None:
    bundle = load_bundle(CONFIG_ROOT / "project_manager.json")
    terminal = bundle["workflow"]["modes"][0]["phases"][-1]
    text = " ".join(item["text"] for item in terminal["instructions"]).lower()

    assert "task ещё не публиковать" in text
    assert "workflow_phase complete" in text
    assert "terminal action не вызывать" in text


def test_every_instruction_skill_is_pinned_or_supplied_by_the_runtime() -> None:
    for path in CONFIG_ROOT.glob("*.json"):
        bundle = load_bundle(path)
        allowed = set(bundle["skillsHub"]["hashes"]) | LOCAL_RUNTIME_SKILLS
        for mode in bundle["workflow"]["modes"]:
            for phase in mode["phases"]:
                for instruction in phase["instructions"]:
                    assert set(instruction["skills"]).issubset(allowed), (
                        path.name,
                        mode["key"],
                        phase["code"],
                        set(instruction["skills"]) - allowed,
                    )


def test_bundle_loader_rejects_mode_without_task_intake_and_unused_skill(tmp_path: Path) -> None:
    import json

    bundle = json.loads((CONFIG_ROOT / "developer.json").read_text(encoding="utf-8"))
    bundle["workflow"]["modes"][1]["phases"][0]["instructions"][0]["text"] = "Начать исправление"
    broken = tmp_path / "developer.json"
    broken.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="must begin"):
        load_bundle(broken)

    bundle = json.loads((CONFIG_ROOT / "analyst.json").read_text(encoding="utf-8"))
    bundle["skillsHub"]["hashes"]["unused-skill"] = "a" * 64
    broken.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="unused Skills Hub"):
        load_bundle(broken)


def test_dev_topology_declares_exactly_seven_private_runtime_services() -> None:
    root = CONFIG_ROOT.parents[1]
    compose = (root / "deploy" / "hermes-namespaces.compose.yml").read_text(encoding="utf-8")
    installer = (root / "scripts" / "install_hermes_namespaces.py").read_text(encoding="utf-8")
    for role in (
        "project-manager",
        "analyst",
        "architect",
        "developer",
        "reviewer",
        "tester",
        "devops",
    ):
        assert f"  project-workflow-{role}:" in compose
    assert "ports:" not in compose
    assert "PROJECT_WORKFLOW_RUNTIME_REQUIRED" in compose
    assert compose.count('PROJECT_WORKFLOW_MANAGED_CONFIGURATION: "1"') == 7
    assert compose.count('DB_POOL_SIZE: "1"') == 7
    assert compose.count('DB_MAX_OVERFLOW: "0"') == 7
    assert "config root must contain exactly seven canonical role bundles" in installer


def test_installer_applies_and_verifies_exact_bundle(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'analyst.db').as_posix()}"
    bundle = load_bundle(CONFIG_ROOT / "analyst.json")

    installed = install(bundle, check_only=False, database_url=database_url)
    checked = install(bundle, check_only=True, database_url=database_url)

    assert installed["checked"] is False
    assert checked["checked"] is True

    with SAUnitOfWork(database_url) as uow:
        workflow = uow.workflows.get_by_name("Hermes Analyst")
        assert workflow is not None and workflow.id is not None
        uow.workflows.update(workflow.id, {"description": "drift"})
        uow.commit()

    with pytest.raises(RuntimeError, match="workflow description"):
        install(bundle, check_only=True, database_url=database_url)


def test_managed_installer_removes_only_empty_bootstrap_workflows(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'managed.db').as_posix()}"
    with SAUnitOfWork(database_url) as uow:
        uow.init()
    monkeypatch.setenv("PROJECT_WORKFLOW_MANAGED_CONFIGURATION", "1")

    bundle = load_bundle(CONFIG_ROOT / "analyst.json")
    install(bundle, check_only=False, database_url=database_url)

    with SAUnitOfWork(database_url) as uow:
        assert [workflow.name for workflow in uow.workflows.list()] == ["Hermes Analyst"]
        assert list(uow.projects.list()) == []
        assert list(uow.agents.list()) == []
