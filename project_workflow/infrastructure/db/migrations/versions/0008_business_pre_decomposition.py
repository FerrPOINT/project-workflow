"""Add an explicit business-only assignment shape; retain all published payloads/pins."""

import sqlalchemy as sa
from alembic import op

from project_workflow.infrastructure.db.assignment_binding_schema import (
    ASSIGNMENT_SHAPE_V1_SQL,
    PRE_DECOMPOSITION_BINDING_V1_SQL,
)

revision = "0008_business_pre_decomposition"
down_revision = "0007_pm_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("task_runtime_assignments") as batch:
        batch.drop_constraint("ck_task_runtime_assignments_binding_complete", type_="check")
        batch.add_column(sa.Column("assignment_shape", sa.String(32), nullable=True))
        batch.create_check_constraint("ck_task_runtime_assignments_assignment_shape", ASSIGNMENT_SHAPE_V1_SQL)
        batch.create_check_constraint("ck_task_runtime_assignments_binding_complete", PRE_DECOMPOSITION_BINDING_V1_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "Business pre-decomposition downgrade refused: it would discard immutable assignment shape/history"
    )
