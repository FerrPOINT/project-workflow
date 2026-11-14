"""Join the published source-baseline histories without replacing either revision."""

from alembic import op
from sqlalchemy import func, select

from project_workflow.application import catalog_publication as editor
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.managed_catalog import ManagedMode, _persist_mode
from project_workflow.infrastructure.db.session import DatabaseRecreateRequired, _metadata_is_current
from project_workflow.infrastructure.db.uow import SAUnitOfWork

revision = "0033_background_convergence"
down_revision = ("0032_current_source_baseline", "0032_current_source_defaults")
branch_labels = None
depends_on = None

PREVIOUS = "852e0647ad8645c9c6280b21c1595b9efa6ff87754d07df8dcc92bcb04f76381"
BACKGROUND = "920379c0c86455148e6fae35e2007037595c2d1cc82116c392c575c4625ffd28"


def converge_catalog(connection) -> None:
    """Seal equivalent unchanged roles while retaining every operator publication.

    The released background cutover appended only changed role definitions.
    Its unchanged roles can therefore still carry the predecessor's receipt.
    Admit only that exact content-equivalent family; never reinterpret another
    mixture or overwrite selected operator content to make the upgrade pass.
    """
    if not _metadata_is_current(connection):
        raise DatabaseRecreateRequired()
    uow = SAUnitOfWork(connection)
    try:
        uow.lock_catalog_state()
        workflows = [w for w in uow.workflows.list() if w.key and w.key.startswith("single-task-v1:")]
        if not workflows:
            return
        receipts = [editor._baseline_receipt(uow, w) for w in workflows]
        if any(receipt is None for receipt in receipts):
            raise ValueError("Missing sealed source catalog receipt")
        families = {editor._baseline_manifest(receipt) for receipt in receipts}
        if len(families) == 1:
            catalog.observe_installation(uow)
            return
        if families != {PREVIOUS, BACKGROUND}:
            raise ValueError("Unsupported mixed source catalog history")
        # This validates every role, namespace, source receipt and selected
        # publication against the exact released background definitions.
        catalog._observe_profile(uow, *catalog.load_profile(BACKGROUND))
        selected = []
        for workflow in workflows:
            if editor._baseline_manifest(editor._baseline_receipt(uow, workflow)) != PREVIOUS:
                continue
            active = editor.read_revision(uow, workflow, workflow.active_catalog_version, selected=True)
            definition = editor._definition(workflow.key, BACKGROUND)
            modes = editor._normalize(active["modes"])
            if modes != editor._normalize(definition["modes"]):
                selected.append((workflow.id, active["catalog_version"], modes))
            editor.publish_baseline(uow, workflow, BACKGROUND)
        uow.session.flush()
        catalog.observe_installation(uow)
        for workflow_id, previous_version, modes in selected:
            workflow = uow.workflows.get_by_id(workflow_id)
            version = uow.session.scalar(select(func.max(m.WorkflowMode.catalog_version)).where(
                m.WorkflowMode.workflow_id == workflow_id)) + 1
            for mode in modes:
                _persist_mode(uow, workflow_id=workflow_id, role_key=editor._definition(workflow.key)["role_key"],
                              mode=ManagedMode.model_validate(mode), catalog_version=version)
            # This is a migration receipt retaining already-published material,
            # not a new human approval or an impersonation of its original author.
            uow.session.add(m.WorkflowCatalogPublication(
                workflow_id=workflow_id, catalog_version=version, parent_version=workflow.active_catalog_version,
                operation_key=f"@background-convergence:{workflow_id}:{previous_version}",
                request_sha256=editor.payload_sha256({
                    "workflow_id": workflow_id, "retained_version": previous_version,
                }),
                content_sha256=editor.payload_sha256(modes), content=editor.canonical_json(modes),
            ))
            uow.workflows.update(workflow_id, {"active_catalog_version": version})
        uow.session.flush()
        catalog.observe_installation(uow)
    finally:
        uow.close()


def upgrade() -> None:
    converge_catalog(op.get_bind())


def downgrade() -> None:
    raise RuntimeError("Configured catalog is forward-only after source-history convergence")
