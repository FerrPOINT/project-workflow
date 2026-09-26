from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_workflow.infrastructure.db.uow import SAUnitOfWork
from scripts.export_business_workflow_catalog import ROLE_ORDER, build_catalog, write_json
from scripts.install_hermes_workflow import (
    LEGACY_MODE_ALIASES,
    LOCAL_RUNTIME_SKILLS,
    ROLE_MODES,
    ROLE_PHYSICAL_SKILLS,
    install,
    load_bundle,
)

CONFIG_ROOT = Path(__file__).resolve().parents[1] / "configs" / "hermes"


def _skills_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "skills.json"
    path.write_text(
        json.dumps(
            {
                "schema": "relevanter-hermes-role-skills/v3",
                "roles": {
                    role: {
                        "namespace": f"hermes-{role.replace('_', '-')}",
                        "profile": f"hermes-sdlc-{role.replace('_', '-')}",
                        "modes": modes,
                        "physicalSkills": sorted(ROLE_PHYSICAL_SKILLS[role]),
                    }
                    for role, modes in ROLE_MODES.items()
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


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
    assert sum(len(bundle["workflow"]["modes"]) for bundle in bundles) == 13
    assert {
        bundle["role"]: [mode["key"] for mode in bundle["workflow"]["modes"]]
        for bundle in bundles
    } == ROLE_MODES
    assert all(mode["key"] != "default" for bundle in bundles for mode in bundle["workflow"]["modes"])


def test_business_export_is_exact_full_registry_with_phase_instructions(tmp_path: Path) -> None:
    workflow_revision = "a" * 40
    skills_revision = "b" * 40
    catalog, phase_source = build_catalog(
        config_root=CONFIG_ROOT,
        skills_manifest_path=_skills_manifest(tmp_path),
        workflow_revision=workflow_revision,
        skills_revision=skills_revision,
    )

    assert list(catalog["roles"]) == ROLE_ORDER
    assert sum(len(role["modes"]) for role in catalog["roles"].values()) == 13
    assert catalog["workflowCatalogRevision"] == workflow_revision
    assert phase_source["workflowCatalogRevision"] == workflow_revision
    assert all(
        phase["instructions"] and phase["checks"] and phase["evidence"]
        for phases in phase_source["phase_sets"].values()
        for phase in phases
    )
    terminal_text = " ".join(
        item["text"]
        for phases in phase_source["phase_sets"].values()
        for item in phases[-1]["instructions"]
    )
    assert terminal_text.count("project-workflow step --report") == 13
    assert "workflow_phase" not in terminal_text

    output = tmp_path / "catalog.json"
    digest = write_json(output, catalog)
    assert len(digest) == 64
    assert b"\r\n" not in output.read_bytes()


def test_delivery_and_aggregate_modes_are_distinct_and_not_aliased() -> None:
    architect = load_bundle(CONFIG_ROOT / "architect.json")
    assert [mode["key"] for mode in architect["workflow"]["modes"]] == ["decomposition"]
    assert "DecompositionRevision" in json.dumps(architect, ensure_ascii=False)

    for role in ("developer", "reviewer", "tester", "devops"):
        bundle = load_bundle(CONFIG_ROOT / f"{role}.json")
        modes = {mode["key"]: mode for mode in bundle["workflow"]["modes"]}
        assert "integration" in modes
        assert modes["integration"]["phases"] != modes[next(key for key in modes if key != "integration")]["phases"]
        assert "головн" in json.dumps(modes["integration"], ensure_ascii=False).lower()


def test_every_terminal_phase_prepares_handoff_before_terminal_action() -> None:
    for path in CONFIG_ROOT.glob("*.json"):
        bundle = load_bundle(path)
        for mode in bundle["workflow"]["modes"]:
            terminal = mode["phases"][-1]
            text = " ".join(item["text"] for item in terminal["instructions"]).lower()
            assert "markdown" in text or "комментар" in text, f"{path.name}/{mode['key']}"
            assert "project-workflow step --report" in text, f"{path.name}/{mode['key']}"
            assert "complete=true" in text, f"{path.name}/{mode['key']}"
            assert "terminal action не вызывать" in text, f"{path.name}/{mode['key']}"
            assert "workflow_phase" not in text, f"{path.name}/{mode['key']}"
            assert "publish_task_draft" not in text, f"{path.name}/{mode['key']}"
            assert "complete_assigned_stage" not in text, f"{path.name}/{mode['key']}"


def test_project_manager_publication_hands_backlog_to_analyst_automatically() -> None:
    bundle = load_bundle(CONFIG_ROOT / "project_manager.json")
    terminal = bundle["workflow"]["modes"][0]["phases"][-1]
    text = " ".join(item["text"] for item in terminal["instructions"]).lower()

    assert "task ещё не публиковать" in text
    assert "project-workflow step --report" in text
    assert "complete=true" in text
    assert "workflow_phase" not in text
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
            used = {
                skill
                for mode in bundle["workflow"]["modes"]
                for phase in mode["phases"]
                for instruction in phase["instructions"]
                for skill in instruction["skills"]
            }
            assert used == ROLE_PHYSICAL_SKILLS[bundle["role"]]


def test_bundle_loader_rejects_mode_without_task_intake_and_unused_skill(tmp_path: Path) -> None:
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


@pytest.mark.parametrize("role", sorted(LEGACY_MODE_ALIASES))
def test_installer_migrates_known_legacy_mode_without_losing_phases(tmp_path: Path, role: str) -> None:
    database_url = f"sqlite:///{(tmp_path / f'{role}.db').as_posix()}"
    bundle = load_bundle(CONFIG_ROOT / f"{role}.json")
    install(bundle, check_only=False, database_url=database_url)
    legacy_key, canonical_key = next(iter(LEGACY_MODE_ALIASES[role].items()))

    with SAUnitOfWork(database_url) as uow:
        workflow = uow.workflows.get_by_name(bundle["workflow"]["name"])
        assert workflow is not None and workflow.id is not None
        canonical = next(
            mode for mode in uow.workflow_modes.list(workflow.id) if mode.key == canonical_key
        )
        assert canonical.id is not None
        phase_ids = [phase.id for phase in uow.phases.list(workflow.id, canonical.id)]
        uow.workflow_modes.update(canonical.id, {"key": legacy_key})
        uow.commit()

    install(bundle, check_only=False, database_url=database_url)
    with SAUnitOfWork(database_url) as uow:
        workflow = uow.workflows.get_by_name(bundle["workflow"]["name"])
        assert workflow is not None and workflow.id is not None
        migrated = next(
            mode for mode in uow.workflow_modes.list(workflow.id) if mode.key == canonical_key
        )
        assert migrated.id is not None
        assert [phase.id for phase in uow.phases.list(workflow.id, migrated.id)] == phase_ids


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
