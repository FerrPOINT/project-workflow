"""Read-only namespace binding on the existing managed catalog, without adoption."""

from project_workflow.application.base_source import load_base_source
from project_workflow.domain.base_admission import BASE_SKILLS_REVISION
from project_workflow.domain.base_binding import BaseNamespaceBinding
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db.managed_catalog import ManagedCatalog, validate_managed_catalog_state
from project_workflow.infrastructure.db.uow import SAUnitOfWork


def _installed_candidate(uow: SAUnitOfWork, catalog: ManagedCatalog) -> None:
    workflows = {workflow.key: workflow for workflow in uow.workflows.list()}
    for definition in catalog.workflows:
        actual = workflows.get(definition.key)
        if actual is None or actual.id is None or actual.active_catalog_version != 3:
            raise ConflictError("Complete active Base candidate v3 required")
        if any(mode.catalog_version != 3 for mode in uow.workflows.list_modes(actual.id, catalog_version=3)):
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
    agent = uow.agents.get_by_name(definition.role_key)
    if (
        namespace["name"] != definition.hermes_namespace
        or namespace["cli_command"] != f"workflow-{definition.role_key}"
        or agent is None or agent.id is None or agent.hermes_profile != definition.hermes_profile
    ):
        raise ConflictError("Persisted Base namespace/role/profile mismatch")
    return BaseNamespaceBinding.model_validate({
        "schema": "base-sdlc/workflow-binding/v1", "namespace_id": str(namespace_id),
        "namespace_name": namespace["name"], "workflow_id": str(workflow.id), "workflow_key": workflow.key,
        "role_key": agent.name, "profile": agent.hermes_profile, "catalog_version": 3,
        "catalog_sha256": catalog_sha256, "skills_revision": BASE_SKILLS_REVISION, "runtime_ready": False,
    })


def observe_base_namespace_binding(uow: SAUnitOfWork, namespace_id: int) -> BaseNamespaceBinding:
    """No caller mapping/proof; verify the complete persisted and immutable sources."""
    if type(namespace_id) is not int or not 0 < namespace_id <= 2**63 - 1:
        raise ValueError("Positive canonical database ID required")
    catalog, source = load_base_source()
    catalog_sha256 = source["workflowCatalogSourceArtifacts"]["project_workflow/references/base_sdlc_catalog_v1.json"]
    uow.lock_catalog_state(shared=True)
    uow.refresh()
    before = _persisted_binding(uow, catalog, namespace_id, catalog_sha256)
    _installed_candidate(uow, catalog)
    # Discard cached rows before final validation/readback, under the same catalog lock.
    uow.refresh()
    _installed_candidate(uow, catalog)
    after = _persisted_binding(uow, catalog, namespace_id, catalog_sha256)
    if after != before:
        raise ConflictError("Base namespace binding changed during observation")
    return after
