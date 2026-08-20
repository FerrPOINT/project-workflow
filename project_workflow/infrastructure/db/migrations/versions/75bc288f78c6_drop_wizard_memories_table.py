"""drop wizard_memories table

Revision ID: 75bc288f78c6
Revises: 249bc4ab2fa9
Create Date: 2026-07-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "75bc288f78c6"
down_revision: str | Sequence[str] | None = "249bc4ab2fa9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop unused wizard_memories table."""
    op.execute("SET search_path TO project_workflow")
    if sa.inspect(op.get_bind()).has_table("wizard_memories", schema="project_workflow"):
        op.drop_table("wizard_memories")


def downgrade() -> None:
    """Recreate wizard_memories table."""
    op.execute("SET search_path TO project_workflow")
    if sa.inspect(op.get_bind()).has_table("wizard_memories", schema="project_workflow"):
        return
    op.create_table(
        "wizard_memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("memory_type", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.CheckConstraint("memory_type IN ('correction', 'lesson', 'blocker_pattern', 'preference')"),
    )
    op.create_index("ix_wizard_memories_task_id", "wizard_memories", ["task_id"])
