"""Read-only namespace binding on the existing managed catalog, without adoption."""

from project_workflow.application.base_source import load_base_source
from project_workflow.domain.base_binding import BaseNamespaceBinding
from project_workflow.domain.base_catalog import BASE_CATALOG_ARTIFACTS
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.project_theme import MANAGED_PROFESSION_PRESENTATION
from project_workflow.infrastructure.db.managed_catalog import ManagedCatalog, validate_managed_catalog_state
from project_workflow.infrastructure.db.uow import SAUnitOfWork


def _installed_candidate(uow: SAUnitOfWork, catalog: ManagedCatalog) -> None:
    workflows = {workflow.key: workflow for workflow in uow.workflows.list()}
    for definition in catalog.workflows:
        actual = workflows.get(definition.key)
        if actual is None or actual.id is None or actual.active_catalog_version != catalog.catalog_version:
            raise ConflictError(f"Complete active Base candidate v{catalog.catalog_version} required")
        if any(mode.catalog_version != catalog.catalog_version for mode in uow.workflows.list_modes(
            actual.id, catalog_version=catalog.catalog_version,
        )):
            raise ConflictError("Active Base mode version mismatch")
    try:
        if not validate_managed_catalog_state(uow, catalog):
            raise ConflictError("Base candidate is not installed")
    except ValueError as exc:
        raise ConflictError("Installed Base candidate differs from pinned source") from exc


def _persisted_binding(
    uow: SAUnitOfWork, catalog: ManagedCatalog, namespace_id: int, catalog_sha256: str,
) -> BaseNamespaceBinding:
    namespace = uow.projects.get_persisted_identity(namespace_id)
    if namespace is None or type(namespace["workflow_id"]) is not int or namespace["workflow_id"] <= 0:
        raise ConflictError("Persisted Base namespace/workflow binding required")
    workflow = uow.workflows.get_by_id(namespace["workflow_id"])
    definition = next((item for item in catalog.workflows if workflow is not None and item.key == workflow.key), None)
    if workflow is None or workflow.id is None or definition is None:
        raise ConflictError("Persisted workflow is not a Base candidate role")
    if (
        (catalog.catalog_version == 3 and namespace["name"] not in {
            definition.hermes_namespace, MANAGED_PROFESSION_PRESENTATION[definition.role_key][0],
        })
        or namespace["cli_command"] != f"workflow-{definition.role_key}"
        or namespace.get("launch_profile") != definition.hermes_profile
    ):
        raise ConflictError("Persisted Base namespace/role/profile mismatch")
    return BaseNamespaceBinding.model_validate({
        "schema": "base-sdlc/workflow-binding/v1", "namespace_id": str(namespace_id),
        "namespace_name": definition.hermes_namespace, "workflow_id": str(workflow.id), "workflow_key": workflow.key,
        "role_key": definition.role_key, "profile": namespace["launch_profile"],
        "catalog_version": catalog.catalog_version,
        "catalog_sha256": catalog_sha256, "skills_revision": catalog.skills_source.revision, "runtime_ready": False,
    })


def observe_base_namespace_binding(uow: SAUnitOfWork, namespace_id: int) -> BaseNamespaceBinding:
    """No caller mapping/proof; verify the complete persisted and immutable sources."""
    if type(namespace_id) is not int or not 0 < namespace_id <= 2**63 - 1:
        raise ValueError("Positive canonical database ID required")
    uow.lock_catalog_state(shared=True)
    uow.refresh()
    identity = uow.projects.get_persisted_identity(namespace_id)
    workflow = uow.workflows.get_by_id(identity["workflow_id"]) if identity else None
    # Historical v3 remains observable; an unknown/legacy version still fails the installed guard.
    version = workflow.active_catalog_version if workflow is not None else 3
    catalog, source = load_base_source(4 if version == 4 else 3)
    artifact = "project_workflow/references/" + BASE_CATALOG_ARTIFACTS[catalog.catalog_version]
    catalog_sha256 = source["workflowCatalogSourceArtifacts"][artifact]
    before = _persisted_binding(uow, catalog, namespace_id, catalog_sha256)
    _installed_candidate(uow, catalog)
    # Discard cached rows before final validation/readback, under the same catalog lock.
    uow.refresh()
    _installed_candidate(uow, catalog)
    after = _persisted_binding(uow, catalog, namespace_id, catalog_sha256)
    if after != before:
        raise ConflictError("Base namespace binding changed during observation")
    return after
