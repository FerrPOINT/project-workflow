"""Install editable background defaults without activating agent execution."""

from __future__ import annotations

import json
from pathlib import Path

from project_workflow.domain.repositories import UnitOfWork

CATALOG_PATH = Path(__file__).resolve().parents[2] / "references/background_professions_v1.json"


def definition(workflow_key: str | None) -> dict | None:
    """The background execution scope carries no Tracker stage permissions."""
    for profession in json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["professions"]:
        workflow = profession["workflow"]
        if workflow["key"] == workflow_key:
            return {"key": workflow_key, "name": workflow["name"], "description": workflow["description"],
                    "role_key": profession["code"].lower(),
                    "modes": [{**workflow["mode"], "mode_order": 1, "execution_scopes": ["background"]}]}
    return None


def ensure_background_professions(uow: UnitOfWork) -> dict[str, int]:
    """Provision once in the caller's transaction; preserve existing author edits.

    Platform initialization calls this alongside the seven SDLC professions.
    This is not a managed task-role assignment or an activation operation.
    """
    definitions = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["professions"]
    uow.lock_catalog_state()
    workflows = {workflow.key: workflow for workflow in uow.workflows.list()}
    existing_ids: dict[str, int] = {}
    # Validate every identity before writing any record, including legacy clashes.
    for definition in definitions:
        profession = uow.projects.get_by_code(definition["code"])
        by_cli = uow.projects.get_by_cli_command(definition["cli_command"])
        workflow = workflows.get(definition["workflow"]["key"])
        if profession is None and by_cli is None and workflow is None:
            continue
        if (
            profession is None or by_cli is None or workflow is None
            or profession.id is None or workflow.id is None
            or profession.id != by_cli.id
            or profession.workflow_id != workflow.id
            or not uow.workflows.belongs_to_profession(workflow.id, profession.id)
        ):
            raise ValueError(
                f"Конфликт фоновой профессии {definition['code']}; "
                "существующие записи сохранены, требуется явный переход владельца"
            )
        existing_ids[definition["code"]] = profession.id

    for definition in definitions:
        code = definition["code"]
        if code in existing_ids:
            continue
        workflow_data = definition["workflow"]
        workflow_id = uow.workflows.create({
            "key": workflow_data["key"], "name": workflow_data["name"],
            "description": workflow_data["description"], "create_default_mode": False,
        })
        mode = workflow_data["mode"]
        mode_id = uow.workflows.create_mode({
            "workflow_id": workflow_id, "key": mode["key"],
            "name": mode["name"], "mode_order": 1,
        })
        for phase in mode["phases"]:
            phase_id = uow.phases.create({
                "workflow_id": workflow_id, "mode_id": mode_id,
                **{key: phase[key] for key in ("code", "name", "phase_order", "execution_type")},
            })
            for item in phase["instructions"]:
                uow.phase_instructions.create(phase_id, item)
            for item in phase["checks"]:
                uow.phase_checks.create(phase_id, item)
            for item in phase["evidence"]:
                uow.phase_evidence_requirements.create(phase_id, item)
        profession_id = uow.projects.create({
            "workflow_id": workflow_id,
            **{key: definition[key] for key in (
                "code", "name", "description", "cli_command", "theme_icon", "theme_color",
            )},
        })
        uow.workflows.assign_profession(workflow_id, profession_id)
        existing_ids[code] = profession_id
    from project_workflow.application.catalog_publication import ensure_background_publication

    for profession_id in existing_ids.values():
        profession = uow.projects.get_by_id(profession_id)
        assert profession is not None and profession.workflow_id is not None
        ensure_background_publication(uow, profession.workflow_id)
    return existing_ids


def background_catalog(uow: UnitOfWork) -> dict[str, list[dict]]:
    """Read installed background identities; never provision during a GET.

    Names and phase content remain editable. Stable identities and ownership
    must match; a legacy profession cannot authorize a new default binding.
    """
    definitions = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["professions"]
    workflows = {workflow.key: workflow for workflow in uow.workflows.list()}
    namespaces, selected_workflows = [], []
    for definition in definitions:
        profession = uow.projects.get_by_code(definition["code"])
        workflow = workflows.get(definition["workflow"]["key"])
        if profession is None and workflow is None:
            continue
        if (profession is None or workflow is None
            or profession.id is None or workflow.id is None
            or profession.cli_command != definition["cli_command"]
            or profession.workflow_id != workflow.id
            or not uow.workflows.belongs_to_profession(workflow.id, profession.id)):
            raise ValueError(f"Background profession identity conflict: {definition['code']}")
        namespaces.append({
            "id": profession.id, "name": profession.name,
            "cli_command": profession.cli_command, "workflow_id": workflow.id,
        })
        selected_workflows.append({"id": workflow.id, "key": workflow.key, "name": workflow.name})
    return {"namespaces": namespaces, "workflows": selected_workflows}
