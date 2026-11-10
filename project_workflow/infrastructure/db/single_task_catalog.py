"""Install/read back a separate profile using the existing catalog transaction."""

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import event, func, inspect, select
from sqlalchemy.engine import Connection
from sqlalchemy.sql import Delete, Insert, Select, Update, visitors
from sqlalchemy.sql.elements import TextClause

from project_workflow import config
from project_workflow.domain.namespace import legacy_code_from_cli_command
from project_workflow.domain.project_theme import DEFAULT_PROJECT_COLOR, DEFAULT_PROJECT_ICON, MANAGED_PROFESSION_THEMES
from project_workflow.domain.single_task_profile import (
    CATALOG_SHA256,
    MANIFEST_SHA256,
    PROFILE,
    RETAINED_PROFILE_CATALOGS,
    ROLE_MODES,
    valid_profession_key,
    SUPPORTED_MANIFESTS,
    SingleTaskInstallation,
    is_single_task_key,
)
from project_workflow.infrastructure.db import models as m
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
    "workflow_catalog_publications",
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
    roles = [w["role_key"] for w in catalog["workflows"]]
    if (len(set(roles)) != len(roles) or not set(ROLE_MODES) <= set(roles)
            or set(manifest["roles"]) != set(roles) or not all(map(valid_profession_key, roles))):
        raise ValueError("Single-task role inventory mismatch")
    for workflow in catalog["workflows"]:
        role = workflow["role_key"]
        modes = {m["key"]: m["execution_scopes"] for m in workflow["modes"]}
        if (not modes or len(modes) != len(workflow["modes"])
                or role in ROLE_MODES and modes != ROLE_MODES[role]
                or any(scopes not in (["business"], ["delivery"]) for scopes in modes.values())):
            raise ValueError("Single-task mode/scope inventory mismatch")
        for mode in workflow["modes"]:
            ManagedMode.model_validate(mode)
    return catalog, manifest


def _manifest_digest(manifest: dict) -> str:
    return {CATALOG_SHA256: MANIFEST_SHA256,
            **{digest: key for key, digest in RETAINED_PROFILE_CATALOGS.items()}}[
                manifest["workflow_catalog"]["sha256"]]


def observe_installation(uow: SAUnitOfWork) -> SingleTaskInstallation:
    """Validate the persisted profession inventory before returning any binding."""
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
    # Published source baselines and operator publications share one monotonic pointer.
    connection = uow.session.connection()
    schema = config.get_settings().DB_SCHEMA if connection.dialect.name == "postgresql" else None
    if inspect(connection).has_table("workflow_catalog_publications", schema=schema):
        pointers = uow.session.execute(select(m.Workflow.id, m.Workflow.active_catalog_version,
            func.max(m.WorkflowCatalogPublication.catalog_version)).join(
                m.WorkflowCatalogPublication, m.WorkflowCatalogPublication.workflow_id == m.Workflow.id
            ).where(m.Workflow.key.startswith(PROFILE + ":")).group_by(
                m.Workflow.id, m.Workflow.active_catalog_version)).all()
        if any(active != latest for _, active, latest in pointers):
            raise ValueError("Active publication pointer changed outside publication")
    elif any(w.get("previous_baseline_manifest_sha256") for w in load_profile()[0]["workflows"]):
        raise ValueError("Current sealed baselines require the publication ledger")
    failures: list[ValueError] = []
    for digest in SUPPORTED_MANIFESTS:
        catalog, manifest = load_profile(digest)
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
    manifest_sha256 = _manifest_digest(manifest)
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
        if (workflow is None or workflow.id is None
            or workflow.name != config.MANAGED_NAMESPACE_WORKFLOW_NAME
            or workflow.description != definition["description"]):
            raise ValueError("Single-task installed workflow missing or divergent")
        from project_workflow.application.catalog_publication import sealed_baseline

        baseline, baseline_version = (
            sealed_baseline(uow, workflow) if workflow.active_catalog_version > 1 else ({}, 1)
        )
        if workflow.active_catalog_version < baseline_version:
            raise ValueError("Active instruction revision precedes its sealed baseline")
        if baseline_version > 1 and baseline["modes"] != definition["modes"]:
            raise ValueError("Sealed baseline source differs from the requested catalog")
        expected = _ArchivedWorkflowDefinition(
            key=definition["key"], name=definition["name"], description=definition["description"], role_key=role,
            modes=[ManagedMode.model_validate(mode) for mode in definition["modes"]],
        )
        _assert_existing_workflow(uow, workflow, expected, catalog_version=baseline_version)
        if workflow.active_catalog_version > baseline_version:
            # Baseline provenance is immutable. Text publications have their own
            # receipts; never stamp mutable editor rows with the sealed baseline hash.
            from project_workflow.application.catalog_publication import read_revision

            read_revision(uow, workflow, workflow.active_catalog_version, selected=True)
        namespace = definition["namespace"]
        project = uow.projects.get_by_cli_command(namespace["cli_command"])
        identity = uow.projects.get_persisted_identity(project.id) if project and project.id else None
        icon, color = MANAGED_PROFESSION_THEMES.get(role, (DEFAULT_PROJECT_ICON, DEFAULT_PROJECT_COLOR))
        if (identity is None or identity.get("launch_profile") != namespace["launch_profile"]
            or not _namespace_has_identity(
                identity, workflow_id=workflow.id, code=legacy_code_from_cli_command(namespace["cli_command"]),
                name=namespace["name"], description=definition["description"], cli_command=namespace["cli_command"],
                key_prefixes=[], theme_icon=icon, theme_color=color, check_theme=False,
            ) or project is None or project.id is None
            or not uow.workflows.belongs_to_profession(workflow.id, project.id)
            or memberships.get(workflow.id) != 1):
            raise ValueError("Single-task installed namespace missing or divergent")
        modes = []
        for mode, source_mode in zip(
            uow.workflows.list_modes(workflow.id, catalog_version=baseline_version), definition["modes"], strict=True,
        ):
            if mode.id is None or mode.catalog_version != baseline_version or mode.name != source_mode["name"]:
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
        "workflow_catalog_sha256": catalog_sha256, "bindings": bindings, **manifest["inventory"],
    })


def ensure_single_task_catalog(uow: SAUnitOfWork) -> SingleTaskInstallation:
    """No commits: the existing initialization transaction owns atomicity."""
    uow.lock_catalog_state()
    catalog, manifest = load_profile()
    existing = {workflow.key for workflow in uow.workflows.list()}
    pending = catalog["workflows"]
    if any(is_single_task_key(key) for key in existing):
        installed = observe_installation(uow)
        if installed.instruction_manifest_sha256 == _manifest_digest(manifest):
            return installed
        previous, previous_manifest = load_profile(installed.instruction_manifest_sha256)
        current_by_key = {w["key"]: w for w in catalog["workflows"]}
        for definition in previous["workflows"]:
            role = definition["role_key"]
            if (current_by_key.get(definition["key"]) != definition
                    or manifest["roles"].get(role) != previous_manifest["roles"][role]):
                raise ValueError("Existing professions must be unchanged for an additive installation")
        pending = [w for w in catalog["workflows"] if w["key"] not in existing]
        if not pending:
            return installed
    for definition in pending:
        command = definition["namespace"]["cli_command"]
        if uow.projects.get_by_cli_command(command) or uow.projects.get_by_code(legacy_code_from_cli_command(command)):
            raise ValueError("Single-task namespace identity is already owned")
    has_default = uow.workflows.get_default() is not None
    for definition in pending:
        role = definition["role_key"]
        workflow_id = uow.workflows.create({
            "key": definition["key"], "name": config.MANAGED_NAMESPACE_WORKFLOW_NAME,
            "description": definition["description"], "is_default": not has_default and role == "project_manager",
            "create_default_mode": False,
        })
        if definition.get("previous_baseline_manifest_sha256"):
            from project_workflow.application.catalog_publication import publish_baseline

            publish_baseline(uow, uow.workflows.get_by_id(workflow_id), _manifest_digest(manifest))
        else:
            for mode in definition["modes"]:
                _persist_mode(uow, workflow_id=workflow_id, role_key=role,
                              mode=ManagedMode.model_validate(mode), catalog_version=1)
        namespace = definition["namespace"]
        icon, color = MANAGED_PROFESSION_THEMES.get(role, (DEFAULT_PROJECT_ICON, DEFAULT_PROJECT_COLOR))
        project_id = uow.projects.create({
            "workflow_id": workflow_id, "code": legacy_code_from_cli_command(namespace["cli_command"]),
            "name": namespace["name"], "description": definition["description"],
            "cli_command": namespace["cli_command"], "launch_profile": namespace["launch_profile"],
            "theme_icon": icon, "theme_color": color, "key_prefixes": [],
        })
        uow.workflows.assign_profession(workflow_id, project_id)
    return observe_installation(uow)
