"""Store PDLC execution context independently from CLI projects and profiles."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_resource_execution_contexts"
down_revision: str | Sequence[str] | None = "0006_versioned_mode_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resource_execution_contexts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("operation_id", sa.String(36), nullable=False, unique=True),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("verified_projection", sa.JSON(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflows.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("mode_id", sa.Integer(), sa.ForeignKey("workflow_modes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by_subject", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("Execution context history requires a compatible rollback cohort")
