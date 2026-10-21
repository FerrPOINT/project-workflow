"""Install/read back a separate profile using the existing catalog transaction."""

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.sql import Delete, Insert, Select, Update, visitors
from sqlalchemy.sql.elements import TextClause

from project_workflow import config
from project_workflow.domain.namespace import legacy_code_from_cli_command
from project_workflow.domain.project_theme import MANAGED_PROFESSION_THEMES
from project_workflow.domain.single_task_profile import (
    CATALOG_SHA256,
    MANIFEST_SHA256,
    PROFILE,
    RETAINED_PROFILE_CATALOGS,
    ROLE_MODES,
    SUPPORTED_MANIFESTS,
    SingleTaskInstallation,
    is_single_task_key,
)
from project_workflow.infrastructure.db.managed_catalog import (
    ManagedMode,
    _ArchivedWorkflowDefinition,
    _assert_existing_workflow,
    _namespace_has_identity,
    _persist_mode,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork

REFERENCES = Path(__file__).resolve().parents[2] / "references"
_RUNTIME_READ = "single_task_runtime_catalog_read"
_CATALOG_TABLES = frozenset({
    "workflows", "workflow_modes", "profession_workflows", "projects", "phases",
    "phase_instructions", "phase_checks", "phase_evidence_requirements",
})


@dataclass
class _RuntimeCatalogRead:
    transaction: tuple[object, object] | None = None
    installation: SingleTaskInstallation | None = None


@contextmanager
def runtime_catalog_read(uow: SAUnitOfWork):
    """Reuse only catalog validation within one explicitly scoped runtime call."""
    session = uow.session
    if _RUNTIME_READ in session.info:
        yield
        return
    scope = _RuntimeCatalogRead()
    session.info[_RUNTIME_READ] = scope
    connections: list[Connection] = []

    def before_sql(_connection, _cursor, _sql, _parameters, context, _many):
        statement = getattr(context.compiled, "statement", None)
        if isinstance(statement, (Select, Insert, Update, Delete)):
            for node in visitors.iterate(statement):
                if (isinstance(node, TextClause)
                    or isinstance(node, (Insert, Update, Delete)) and node.table.name in _CATALOG_TABLES):
                    break
            else:
                return
        # Includes direct Connection writes, opaque SQL and writable CTEs.
        scope.installation = None

    def watch(_session, _transaction, connection):
        if connection not in connections:
            event.listen(connection, "before_cursor_execute", before_sql)
            connections.append(connection)

    event.listen(session, "after_begin", watch)
    try:
        if session.in_transaction():
            watch(session, None, session.connection())
        yield
    finally:
        event.remove(session, "after_begin", watch)
        for connection in connections:
            event.remove(connection, "before_cursor_execute", before_sql)
        del session.info[_RUNTIME_READ]


def load_profile(manifest_sha256: str = MANIFEST_SHA256) -> tuple[dict, dict]:
    if manifest_sha256 not in SUPPORTED_MANIFESTS:
        raise ValueError("Unsupported single-task profile manifest")
    retained = manifest_sha256 in RETAINED_PROFILE_CATALOGS
    root = REFERENCES / "retained" / manifest_sha256 if retained else REFERENCES
    catalog_sha256 = RETAINED_PROFILE_CATALOGS[manifest_sha256] if retained else CATALOG_SHA256
    values = []
    for filename, expected in (("single_task_catalog_v1.json", catalog_sha256),
                               ("single_task_manifest_v1.json", manifest_sha256)):
        path = root / filename
        if path.is_symlink():
            raise ValueError("Profile source must be a regular artifact")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError("Single-task profile source hash mismatch")
        values.append(json.loads(content))
    catalog, manifest = values
    if (catalog["schema"] != "single-task-sdlc/workflow-catalog/v1"
        or manifest["schema"] != "single-task-sdlc/profile-manifest/v1"
        or catalog["instruction_profile"] != PROFILE or manifest["instruction_profile"] != PROFILE
        or catalog["catalog_version"] != 1 or manifest["profile_version"] != 1 or manifest["proposal"] is not False
        or manifest["workflow_catalog"]["sha256"] != catalog_sha256):
        raise ValueError("Single-task profile generation mismatch")
    if [w["role_key"] for w in catalog["workflows"]] != list(ROLE_MODES):
        raise ValueError("Single-task role inventory mismatch")
    for workflow in catalog["workflows"]:
        role = workflow["role_key"]
        if {m["key"]: m["execution_scopes"] for m in workflow["modes"]} != ROLE_MODES[role]:
            raise ValueError("Single-task mode/scope inventory mismatch")
        for mode in workflow["modes"]:
            ManagedMode.model_validate(mode)
    return catalog, manifest


def observe_installation(uow: SAUnitOfWork) -> SingleTaskInstallation:
    """Validate all seven persisted professions before returning any binding."""
    session = uow.session
    scope = session.info.get(_RUNTIME_READ)
    transaction = (session.get_transaction(), session.get_nested_transaction())
    if scope is not None:
        if any(row.__table__.name in _CATALOG_TABLES for row in session.new | session.dirty | session.deleted):
            scope.installation = None
        if scope.installation is not None and scope.transaction == transaction:
            return scope.installation.model_copy(deep=True)
    uow.lock_catalog_state(shared=True)
    uow.refresh()
    # Match a complete sealed family, never stamp old rows with the current hash.
    profiles = [load_profile(digest) for digest in SUPPORTED_MANIFESTS]
    failures: list[ValueError] = []
    for catalog, manifest in profiles:
        try:
            result = _observe_profile(uow, catalog, manifest)
            if scope is not None:
                scope.transaction = (session.get_transaction(), session.get_nested_transaction())
                scope.installation = result.model_copy(deep=True)
            return result
        except ValueError as exc:
            failures.append(exc)
    raise failures[0]


def _observe_profile(uow: SAUnitOfWork, catalog: dict, manifest: dict) -> SingleTaskInstallation:
    catalog_sha256 = manifest["workflow_catalog"]["sha256"]
    manifest_sha256 = {
        CATALOG_SHA256: MANIFEST_SHA256,
        **{digest: key for key, digest in RETAINED_PROFILE_CATALOGS.items()},
    }[catalog_sha256]
    installed_workflows = {workflow.key: workflow for workflow in uow.workflows.list()}
    if {key for key in installed_workflows if is_single_task_key(key)} != {w["key"] for w in catalog["workflows"]}:
        raise ValueError("Single-task installed workflow inventory mismatch")
    expected_commands = {w["namespace"]["cli_command"] for w in catalog["workflows"]}
    installed_commands = {p.cli_command for p in uow.projects.list()
                          if p.cli_command.startswith("workflow-single-task-")}
    if installed_commands != expected_commands:
        raise ValueError("Single-task installed namespace inventory mismatch")
    bindings = []
    memberships = uow.workflows.count_professions_by_workflow()
    for definition in catalog["workflows"]:
        role = definition["role_key"]
        workflow = installed_workflows.get(definition["key"])
        if (workflow is None or workflow.id is None or workflow.active_catalog_version != 1
            or workflow.name != config.MANAGED_NAMESPACE_WORKFLOW_NAME
            or workflow.description != definition["description"]):
            raise ValueError("Single-task installed workflow missing or divergent")
        expected = _ArchivedWorkflowDefinition(
            key=definition["key"], name=definition["name"], description=definition["description"], role_key=role,
            modes=[ManagedMode.model_validate(mode) for mode in definition["modes"]],
        )
        _assert_existing_workflow(uow, workflow, expected)
        namespace = definition["namespace"]
        project = uow.projects.get_by_cli_command(namespace["cli_command"])
        identity = uow.projects.get_persisted_identity(project.id) if project and project.id else None
        icon, color = MANAGED_PROFESSION_THEMES[role]
        if (identity is None or identity.get("launch_profile") != namespace["launch_profile"]
            or not _namespace_has_identity(
                identity, workflow_id=workflow.id, code=legacy_code_from_cli_command(namespace["cli_command"]),
                name=namespace["name"], description=definition["description"], cli_command=namespace["cli_command"],
                key_prefixes=[], theme_icon=icon, theme_color=color,
            ) or project is None or project.id is None
            or not uow.workflows.belongs_to_profession(workflow.id, project.id)
            or memberships.get(workflow.id) != 1):
            raise ValueError("Single-task installed namespace missing or divergent")
        modes = []
        for mode, source_mode in zip(uow.workflows.list_modes(workflow.id), definition["modes"], strict=True):
            if mode.id is None or mode.catalog_version != 1 or mode.name != source_mode["name"]:
                raise ValueError("Single-task installed mode identity mismatch")
            modes.append({"mode_id": str(mode.id), "key": mode.key, "execution_scopes": mode.execution_scopes,
                          "phase_ids": [str(p.id) for p in uow.phases.list(workflow.id, mode_id=mode.id)]})
        bindings.append({
            "schema": "single-task-sdlc/workflow-binding/v1", "instruction_manifest_sha256": manifest_sha256,
            "workflow_catalog_sha256": catalog_sha256, "namespace_id": str(project.id),
            "namespace_name": identity["name"], "namespace_cli_command": identity["cli_command"],
            "workflow_id": str(workflow.id), "workflow_key": workflow.key, "role_key": role,
            "profile": identity["launch_profile"], "modes": modes,
            "role_instructions_sha256": manifest["roles"][role]["role_instructions_sha256"],
        })
    return SingleTaskInstallation.model_validate({
        "schema": "single-task-sdlc/installation/v1", "instruction_manifest_sha256": manifest_sha256,
        "workflow_catalog_sha256": catalog_sha256, "bindings": bindings,
    })


def ensure_single_task_catalog(uow: SAUnitOfWork) -> SingleTaskInstallation:
    """No commits: the existing initialization transaction owns atomicity."""
    uow.lock_catalog_state()
    catalog, _ = load_profile()
    existing = {workflow.key for workflow in uow.workflows.list()}
    if any(is_single_task_key(key) for key in existing):
        return observe_installation(uow)  # A partial install/drift must fail, not silently repair.
    for definition in catalog["workflows"]:
        command = definition["namespace"]["cli_command"]
        if uow.projects.get_by_cli_command(command) or uow.projects.get_by_code(legacy_code_from_cli_command(command)):
            raise ValueError("Single-task namespace identity is already owned")
    has_default = uow.workflows.get_default() is not None
    for definition in catalog["workflows"]:
        role = definition["role_key"]
        workflow_id = uow.workflows.create({
            "key": definition["key"], "name": config.MANAGED_NAMESPACE_WORKFLOW_NAME,
            "description": definition["description"], "is_default": not has_default and role == "project_manager",
            "active_catalog_version": 1, "create_default_mode": False,
        })
        for mode in definition["modes"]:
            _persist_mode(uow, workflow_id=workflow_id, role_key=role,
                          mode=ManagedMode.model_validate(mode), catalog_version=1)
        namespace = definition["namespace"]
        icon, color = MANAGED_PROFESSION_THEMES[role]
        project_id = uow.projects.create({
            "workflow_id": workflow_id, "code": legacy_code_from_cli_command(namespace["cli_command"]),
            "name": namespace["name"], "description": definition["description"],
            "cli_command": namespace["cli_command"], "launch_profile": namespace["launch_profile"],
            "theme_icon": icon, "theme_color": color, "key_prefixes": [],
        })
        uow.workflows.assign_profession(workflow_id, project_id)
    return observe_installation(uow)
