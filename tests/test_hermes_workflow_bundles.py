from __future__ import annotations

import json
import shutil
import subprocess
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


def _source_repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "source"
    shutil.copytree(CONFIG_ROOT, repository / "configs" / "hermes")
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "add", "configs/hermes"], check=True)
    subprocess.run(
        [
            "git", "-C", str(repository), "-c", "user.name=Workflow Tests",
            "-c", "user.email=workflow-tests@example.invalid", "commit", "-qm", "fixture",
        ],
        check=True,
    )
    revision = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repository, revision


def _skills_repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "skills-source"
    path = repository / "manifests" / "hermes-workflow-role-skills.v1.json"
    path.parent.mkdir(parents=True)
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
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "add", "manifests"], check=True)
    subprocess.run(
        [
            "git", "-C", str(repository), "-c", "user.name=Skills Tests",
            "-c", "user.email=skills-tests@example.invalid", "commit", "-qm", "fixture",
        ],
        check=True,
    )
    revision = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repository, revision


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
    assert all(
        bundle["businessWorkflowKey"] == f"hermes-sdlc:{bundle['role']}"
        for bundle in bundles
    )
    assert all(mode["key"] != "default" for bundle in bundles for mode in bundle["workflow"]["modes"])


def test_business_export_is_exact_full_registry_with_phase_instructions(tmp_path: Path) -> None:
    repository, workflow_revision = _source_repository(tmp_path)
    skills_repository, skills_revision = _skills_repository(tmp_path)
    catalog, phase_source = build_catalog(
        repository_root=repository,
        skills_repository_root=skills_repository,
        workflow_revision=workflow_revision,
        skills_revision=skills_revision,
    )

    assert list(catalog["roles"]) == ROLE_ORDER
    assert sum(len(role["modes"]) for role in catalog["roles"].values()) == 13
    assert catalog["workflowCatalogRevision"] == workflow_revision
    assert phase_source["workflowCatalogRevision"] == workflow_revision
    assert {
        role: definition["workflow"] for role, definition in catalog["roles"].items()
    } == {role: f"hermes-sdlc:{role}" for role in ROLE_ORDER}
    assert catalog["roles"]["developer"]["workflowName"] == "Hermes Developer"
    assert all(
        phase["execution_type"] == "sync"
        and phase["instructions"]
        and all(item["execution_type"] == "sync" for item in phase["instructions"])
        and phase["checks"] and phase["evidence"]
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


def test_business_export_rejects_unproven_revision_and_dirty_tree(tmp_path: Path) -> None:
    repository, workflow_revision = _source_repository(tmp_path)
    skills_repository, skills_revision = _skills_repository(tmp_path)
    arguments = {
        "repository_root": repository,
        "skills_repository_root": skills_repository,
        "skills_revision": skills_revision,
    }
    with pytest.raises(ValueError, match="does not match repository HEAD"):
        build_catalog(workflow_revision="a" * 40, **arguments)

    (repository / "configs" / "hermes" / "analyst.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="tree must be clean"):
        build_catalog(workflow_revision=workflow_revision, **arguments)


def test_business_export_rejects_unproven_skills_manifest(tmp_path: Path) -> None:
    workflow_repository, workflow_revision = _source_repository(tmp_path)
    skills_repository, skills_revision = _skills_repository(tmp_path)
    arguments = {
        "repository_root": workflow_repository,
        "workflow_revision": workflow_revision,
    }
    with pytest.raises(ValueError, match="does not match repository HEAD"):
        build_catalog(
            skills_repository_root=skills_repository,
            skills_revision="b" * 40,
            **arguments,
        )

    manifest = skills_repository / "manifests" / "hermes-workflow-role-skills.v1.json"
    manifest.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="skills repository tree must be clean"):
        build_catalog(
            skills_repository_root=skills_repository,
            skills_revision=skills_revision,
            **arguments,
        )

    clean_repository, clean_revision = _skills_repository(tmp_path / "outside")
    with pytest.raises(ValueError, match="exact Git top level"):
        build_catalog(
            skills_repository_root=clean_repository / "manifests",
            skills_revision=clean_revision,
            **arguments,
        )
    with pytest.raises(ValueError, match="normalized repo-relative"):
        build_catalog(
            skills_repository_root=clean_repository,
            skills_revision=clean_revision,
            skills_manifest_relative_path=str(manifest.resolve()),
            **arguments,
        )


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
    publish = bundle["workflow"]["modes"][0]["phases"][-1]
    publish_text = json.dumps(publish, ensure_ascii=False).lower()
    assert "бэклог/waiting" in publish_text
    assert "durable scanner" in publish_text
    assert "прямой запуск analyst" in publish_text
    draft = json.dumps(bundle["workflow"]["modes"][0], ensure_ascii=False).lower()
    for forbidden in ("parent", "зависим", "подзадач", "техническ"):
        assert forbidden not in draft


def test_integration_rework_is_strictly_frozen_finding_driven() -> None:
    bundle = load_bundle(CONFIG_ROOT / "developer.json")
    mode = next(item for item in bundle["workflow"]["modes"] if item["key"] == "integration_rework")
    assert [phase["code"] for phase in mode["phases"]] == [
        "integration_rework.context",
        "integration_rework.reproduce",
        "integration_rework.regression",
        "integration_rework.fix",
        "integration_rework.closure",
        "integration_rework.retest",
        "integration_rework.handoff",
    ]
    text = json.dumps(mode, ensure_ascii=False).lower()
    for required in ("frozen finding", "воспроиз", "regression", "closure", "aggregate retest"):
        assert required in text
    assert "initial integration" not in text
    assert "обнаруженные gaps" not in text


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

    bundle = json.loads((CONFIG_ROOT / "analyst.json").read_text(encoding="utf-8"))
    bundle["businessWorkflowKey"] = "Hermes Analyst"
    broken.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="Business workflow key"):
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
        workflow = uow.workflows.get_by_name(bundle["businessWorkflowKey"])
        assert workflow is not None and workflow.id is not None
        uow.workflows.update(workflow.id, {"description": "drift"})
        uow.commit()

    with pytest.raises(RuntimeError, match="workflow description"):
        install(bundle, check_only=True, database_url=database_url)


def test_installer_refuses_in_place_legacy_mode_reuse(tmp_path: Path) -> None:
    role = "architect"
    database_url = f"sqlite:///{(tmp_path / 'legacy-populated.db').as_posix()}"
    bundle = load_bundle(CONFIG_ROOT / "architect.json")
    install(bundle, check_only=False, database_url=database_url)
    legacy_key, canonical_key = next(iter(LEGACY_MODE_ALIASES[role].items()))

    with SAUnitOfWork(database_url) as uow:
        workflow = uow.workflows.get_by_name(bundle["businessWorkflowKey"])
        assert workflow is not None and workflow.id is not None
        canonical = next(
            mode for mode in uow.workflow_modes.list(workflow.id) if mode.key == canonical_key
        )
        assert canonical.id is not None
        uow.workflow_modes.update(canonical.id, {"key": legacy_key})
        uow.commit()

    with pytest.raises(RuntimeError, match="requires audited migration.*phases"):
        install(bundle, check_only=False, database_url=database_url)


def _add_empty_legacy_mode(database_url: str) -> tuple[dict, int, int, int, int]:
    bundle = load_bundle(CONFIG_ROOT / "reviewer.json")
    install(bundle, check_only=False, database_url=database_url)
    with SAUnitOfWork(database_url) as uow:
        workflow = uow.workflows.get_by_name(bundle["businessWorkflowKey"])
        assert workflow is not None and workflow.id is not None
        delivery = uow.workflow_modes.get_by_key(workflow.id, "delivery")
        assert delivery is not None and delivery.id is not None
        legacy_id = uow.workflow_modes.create(
            {"workflow_id": workflow.id, "key": "review", "name": "Legacy Review"}
        )
        project_id = uow.projects.create(
            {"workflow_id": workflow.id, "code": "LEGACY", "name": "Legacy audit", "key_prefixes": []}
        )
        uow.commit()
    return bundle, int(workflow.id), int(delivery.id), legacy_id, project_id


def test_installer_replaces_only_empty_unreferenced_legacy_mode_with_fresh_id(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'legacy-empty.db').as_posix()}"
    bundle, workflow_id, delivery_id, legacy_id, _project_id = _add_empty_legacy_mode(database_url)

    install(bundle, check_only=False, database_url=database_url)
    with SAUnitOfWork(database_url) as uow:
        assert uow.workflow_modes.get_by_id(legacy_id) is None
        delivery = uow.workflow_modes.get_by_key(workflow_id, "delivery")
        assert delivery is not None and delivery.id == delivery_id


def test_installer_creates_fresh_canonical_id_after_auditing_empty_legacy_mode(tmp_path: Path) -> None:
    from project_workflow.application.workflow import WorkflowService
    from project_workflow.infrastructure.db.session import ensure_schema, get_engine

    database_url = f"sqlite:///{(tmp_path / 'legacy-only.db').as_posix()}"
    ensure_schema(get_engine(database_url))
    bundle = load_bundle(CONFIG_ROOT / "architect.json")
    with SAUnitOfWork(database_url) as uow:
        created = WorkflowService(uow).create_workflow(
            {
                "name": bundle["businessWorkflowKey"],
                "description": bundle["workflow"]["description"],
                "_skip_default_phase": True,
                "_default_mode_key": "architecture",
                "_default_mode_name": "Legacy Architecture",
            }
        )
        legacy = uow.workflow_modes.get_by_key(int(created["id"]), "architecture")
        assert legacy is not None and legacy.id is not None
        workflow_id, legacy_id = int(created["id"]), int(legacy.id)

    install(bundle, check_only=False, database_url=database_url)
    with SAUnitOfWork(database_url) as uow:
        assert uow.workflow_modes.get_by_id(legacy_id) is None
        canonical = uow.workflow_modes.get_by_key(workflow_id, "decomposition")
        assert canonical is not None and canonical.id is not None and canonical.id != legacy_id


@pytest.mark.parametrize("reference", ["tasks", "task_history", "supervisor_runs"])
def test_installer_fails_closed_for_every_legacy_mode_reference(tmp_path: Path, reference: str) -> None:
    from project_workflow.infrastructure.db import models as m

    database_url = f"sqlite:///{(tmp_path / f'legacy-{reference}.db').as_posix()}"
    bundle, workflow_id, delivery_id, legacy_id, project_id = _add_empty_legacy_mode(database_url)
    with SAUnitOfWork(database_url) as uow:
        phase = uow.phases.list(workflow_id, delivery_id)[0]
        assert phase.id is not None
        task_id = uow.tasks.create(
            {"project_id": project_id, "task_key": f"LEGACY-{reference}", "current_mode_id": delivery_id}
        )
        if reference == "tasks":
            uow.tasks.update(task_id, {"current_mode_id": legacy_id})
        elif reference == "task_history":
            uow.session.add(m.TaskHistory(
                task_id=task_id, phase_id=phase.id, mode_id=legacy_id, cycle_number=0, status="pending"
            ))
        else:
            uow.session.add(m.SupervisorRun(
                task_id=task_id, phase_id=phase.id, mode_id=legacy_id, cycle_number=0,
                attempt_number=1, verdict="pass", report="", covered="[]", missing="[]",
                blockers="[]", context_snapshot="{}", response="{}",
            ))
        uow.commit()

    with pytest.raises(RuntimeError, match=rf"requires audited migration.*'{reference}': 1"):
        install(bundle, check_only=False, database_url=database_url)


def test_managed_installer_removes_only_empty_bootstrap_workflows(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'managed.db').as_posix()}"
    with SAUnitOfWork(database_url) as uow:
        uow.init()
    monkeypatch.setenv("PROJECT_WORKFLOW_MANAGED_CONFIGURATION", "1")

    bundle = load_bundle(CONFIG_ROOT / "analyst.json")
    install(bundle, check_only=False, database_url=database_url)

    with SAUnitOfWork(database_url) as uow:
        assert [workflow.name for workflow in uow.workflows.list()] == [bundle["businessWorkflowKey"]]
        assert list(uow.projects.list()) == []
        assert list(uow.agents.list()) == []
