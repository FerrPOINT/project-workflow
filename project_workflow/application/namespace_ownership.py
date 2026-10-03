"""Write-once namespace authority under the catalog/project enrollment lock."""

from uuid import uuid4

from sqlalchemy import select

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.namespace_ownership import NamespaceOwnershipReadback, NamespaceOwnershipRequest
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.namespace_auth import NamespacePrincipal


class NamespaceOwnershipService:
    def __init__(self, uow: SAUnitOfWork):
        self.uow = uow

    def lock_namespace(self, namespace_id: int) -> None:
        self.uow.lock_catalog_state(shared=True)
        project = self.uow.projects.lock_pm_namespace(namespace_id)
        if project is None:
            raise NotFoundError("Namespace not found")
        workflow = self.uow.workflows.get_by_id(project.workflow_id)
        if (
            project.cli_command != "workflow-project_manager" or workflow is None
            or workflow.key != "hermes-sdlc:project_manager"
        ):
            raise ConflictError("Canonical managed PM namespace required")

    def get(self, namespace_id: int) -> NamespaceOwnershipReadback:
        row = self.uow.projects.get_pm_ownership(namespace_id)
        if row is None:
            raise NotFoundError("PM namespace ownership not provisioned")
        return NamespaceOwnershipReadback.model_validate(row)

    def provision(
        self, namespace_id: int, request: NamespaceOwnershipRequest, principal: NamespacePrincipal,
    ) -> tuple[NamespaceOwnershipReadback, bool]:
        self.lock_namespace(namespace_id)
        existing = self.uow.projects.get_pm_ownership(namespace_id)
        if existing is not None:
            result = NamespaceOwnershipReadback.model_validate(existing)
            if (
                result.tracker_instance_ref != request.tracker_instance_ref
                or result.tracker_project_ref != request.tracker_project_ref
                or result.authority_issuer != principal.issuer
                or result.provisioner_subject != principal.subject
            ):
                raise ConflictError("PM namespace ownership is immutable")
            return result, False
        foreign = self.uow.projects.get_pm_ownership_by_tracker(
            request.tracker_instance_ref, request.tracker_project_ref,
        )
        if foreign is not None:
            raise ConflictError("Tracker project already has a PM namespace")
        mismatch = self.uow.session.scalar(select(m.PMExecution.execution_ref).join(m.Task).where(
            m.Task.project_id == namespace_id,
            (m.PMExecution.tracker_instance_ref != request.tracker_instance_ref)
            | (m.PMExecution.tracker_project_ref != request.tracker_project_ref),
        ).limit(1))
        if mismatch is not None:
            raise ConflictError("Existing PM enrollment belongs to another Tracker project")
        self.uow.projects.create_pm_ownership({
            **request.model_dump(), "ownership_ref": str(uuid4()), "namespace_id": namespace_id,
            "authority_issuer": principal.issuer, "provisioner_subject": principal.subject,
        })
        return self.get(namespace_id), True
