"""One forward adoption of the exact retired Base-v4 profession catalog."""

import hashlib

from sqlalchemy import or_, select

from project_workflow import config
from project_workflow.domain.base_catalog import BASE_CATALOG_BLOBS
from project_workflow.domain.namespace import legacy_code_from_cli_command
from project_workflow.domain.project_theme import MANAGED_PROFESSION_PRESENTATION
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.managed_catalog import load_managed_catalog, validate_managed_catalog_state
from project_workflow.infrastructure.db.single_task_catalog import (
    REFERENCES,
    _observe_profile,
    load_profile,
    observe_installation,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork


def adopt_legacy_professions(uow: SAUnitOfWork, target_manifest: str) -> None:
    """The initialization/migration transaction owns every write and its rollback."""
    uow.lock_catalog_state()
    workflows = list(uow.workflows.list())
    if any(w.key and w.key.startswith("single-task-v1:") for w in workflows):
        # A current installation, including accepted older publications, is not
        # a candidate for reassigning its professions or changing its history.
        observe_installation(uow)
        return
    present = {w.key for w in workflows if w.key and w.key.startswith("hermes-sdlc:")}
    if not present:
        return  # Normal fresh bootstrap owns creation, not this transition.
    source = REFERENCES / "base_sdlc_catalog_v2.json"
    content = source.read_bytes().replace(b"\r\n", b"\n")
    blob = b"blob " + str(len(content)).encode() + b"\0" + content
    if hashlib.sha1(blob).hexdigest() != BASE_CATALOG_BLOBS[4]:
        raise ValueError("Legacy Base-v4 source differs from its immutable published identity")
    legacy = load_managed_catalog(source)
    expected = {definition.key for definition in legacy.workflows}
    if present != expected:
        raise ValueError("Legacy profession transition requires the complete exact Base-v4 catalog")
    if not validate_managed_catalog_state(uow, legacy):
        raise ValueError("Legacy profession transition requires a verified Base-v4 catalog")
    catalog, manifest = load_profile(target_manifest)
    targets = {definition["role_key"]: definition for definition in catalog["workflows"]}
    if set(targets) != {definition.role_key for definition in legacy.workflows}:
        raise ValueError("Legacy profession transition role inventory differs from the sealed target")
    by_key = {w.key: w for w in workflows}
    memberships = uow.workflows.count_professions_by_workflow()
    prepared = []
    for definition in legacy.workflows:
        workflow = by_key[definition.key]
        project = uow.projects.get_by_cli_command(f"workflow-{definition.role_key}")
        if project is None or project.id is None or workflow.id is None:
            raise ValueError("Legacy profession transition identity is missing")
        name, description = MANAGED_PROFESSION_PRESENTATION[definition.role_key]
        if (workflow.name not in {definition.name, config.MANAGED_NAMESPACE_WORKFLOW_NAME}
                or workflow.description != definition.description
                or project.name not in {definition.hermes_namespace, name}
                or project.description not in {description, definition.description,
                                               f"Managed namespace for {definition.key}"}
                or project.launch_profile != definition.hermes_profile
                or memberships.get(workflow.id) != 1
                or {w.id for w in uow.workflows.list_by_profession(project.id)} != {workflow.id}):
            raise ValueError("Legacy profession transition refuses customized or ambiguous ownership")
        target = targets[definition.role_key]
        command = target["namespace"]["cli_command"]
        if (uow.projects.get_by_cli_command(command)
                or uow.projects.get_by_code(legacy_code_from_cli_command(command))):
            raise ValueError("Legacy profession transition target namespace identity is already owned")
        prepared.append((project.id, workflow.id, target))
    profession_ids = [project for project, _, _ in prepared]
    workflow_ids = [workflow for _, workflow, _ in prepared]
    task_scope = or_(m.Task.project_id.in_(profession_ids), m.Task.workflow_id.in_(workflow_ids))
    if uow.session.scalar(select(m.Task.id).where(task_scope, m.Task.status != "done").limit(1)) is not None:
        raise ValueError("Legacy profession transition refuses active tasks or runtime bindings")
    if uow.session.scalar(select(m.PMRun.session_run_id).join(m.PMExecution).join(m.Task).where(
            task_scope, m.PMRun.terminal_json.is_(None)).limit(1)) is not None:
        raise ValueError("Legacy profession transition requires the original PM terminal receipt")
    if uow.session.scalar(select(m.PMNamespaceOwnership.ownership_ref).where(
            m.PMNamespaceOwnership.namespace_id.in_(profession_ids)).limit(1)) is not None:
        raise ValueError("Legacy profession transition refuses project-owned namespace bindings")
    # Every source, target and active-work check precedes the first write.
    from project_workflow.application.catalog_publication import publish_baseline

    selected = uow.workflows.get_default()
    selected_id = selected.id if selected is not None and selected.id in workflow_ids else None
    if selected_id is not None:
        uow.workflows.update(selected_id, {"is_default": False})
        uow.session.flush()  # Release the unique current-selection flag first.
    for project_id, previous_id, definition in prepared:
        workflow_id = uow.workflows.create({
            "key": definition["key"], "name": config.MANAGED_NAMESPACE_WORKFLOW_NAME,
            "description": definition["description"], "is_default": previous_id == selected_id,
            "create_default_mode": False,
        })
        publish_baseline(uow, uow.workflows.get_by_id(workflow_id), target_manifest)
        uow.workflows.assign_profession(workflow_id, project_id)
        namespace = definition["namespace"]
        uow.projects.update(project_id, {
            "workflow_id": workflow_id, "code": legacy_code_from_cli_command(namespace["cli_command"]),
            "name": namespace["name"], "description": definition["description"],
            "cli_command": namespace["cli_command"], "launch_profile": namespace["launch_profile"],
        })
    uow.session.flush()
    _observe_profile(uow, catalog, manifest)
