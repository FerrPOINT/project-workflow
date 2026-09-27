"""Add durable Hermes bind finalization to runtime assignments.

Revision ID: 0003_runtime_assignment_bind
Revises: 0002_workflow_modes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_runtime_assignment_bind"
down_revision: str | Sequence[str] | None = "0002_workflow_modes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    """Add bind idempotency metadata without rewriting existing real refs."""
    with op.batch_alter_table(
        "task_runtime_assignments", recreate="always" if _is_sqlite() else "auto"
    ) as batch:
        batch.drop_constraint(
            "ck_task_runtime_assignments_binding_complete", type_="check"
        )
        batch.add_column(sa.Column("bind_operation_key", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("bind_request_sha256", sa.String(length=64), nullable=True))
        batch.create_unique_constraint(
            "uq_task_runtime_assignments_bind_operation_key", ["bind_operation_key"]
        )
        batch.create_check_constraint(
            "ck_task_runtime_assignments_binding_complete",
            "(workflow_key IS NULL AND role_key IS NULL AND execution_scope IS NULL AND stage_key IS NULL AND "
            "attempt_number IS NULL AND business_task_ref IS NULL AND root_task_ref IS NULL AND "
            "work_item_ref IS NULL AND work_item_revision IS NULL AND queue_item_ref IS NULL AND "
            "task_workspace_ref IS NULL AND workspace_revision IS NULL AND "
            "tech_execution_workspace_ref IS NULL AND tech_execution_attempt_ref IS NULL AND "
            "decomposition_revision_ref IS NULL AND stage_revision IS NULL AND assignment_ref IS NULL AND "
            "binding_ref IS NULL AND hermes_run_ref IS NULL AND bind_operation_key IS NULL AND "
            "bind_request_sha256 IS NULL AND workspace_generation IS NULL AND "
            "lease_generation IS NULL AND exact_input_refs IS NULL AND payload_sha256 IS NULL) OR "
            "(workflow_key IS NOT NULL AND role_key IS NOT NULL AND execution_scope IS NOT NULL AND "
            "stage_key IS NOT NULL AND attempt_number IS NOT NULL AND business_task_ref IS NOT NULL AND "
            "root_task_ref IS NOT NULL AND work_item_ref IS NOT NULL AND work_item_revision IS NOT NULL AND "
            "queue_item_ref IS NOT NULL AND task_workspace_ref IS NOT NULL AND workspace_revision IS NOT NULL AND "
            "decomposition_revision_ref IS NOT NULL AND stage_revision IS NOT NULL AND assignment_ref IS NOT NULL AND "
            "workspace_generation IS NOT NULL AND lease_generation IS NOT NULL AND "
            "exact_input_refs IS NOT NULL AND payload_sha256 IS NOT NULL AND "
            "((binding_ref IS NULL AND hermes_run_ref IS NULL AND bind_operation_key IS NULL AND "
            "bind_request_sha256 IS NULL) OR (binding_ref IS NOT NULL AND hermes_run_ref IS NOT NULL AND "
            "((bind_operation_key IS NULL AND bind_request_sha256 IS NULL) OR "
            "(bind_operation_key IS NOT NULL AND bind_request_sha256 IS NOT NULL)))))",
        )
        batch.create_check_constraint(
            "ck_task_runtime_assignments_bind_request_sha256",
            "bind_request_sha256 IS NULL OR length(bind_request_sha256) = 64",
        )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade from runtime assignment bind finalization is intentionally refused: "
        "it would discard durable bind idempotency metadata."
    )
