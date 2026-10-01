"""Store native Business work item revisions without 32-bit truncation.

Revision ID: 0004_wide_work_item_revision
Revises: 0003_runtime_assignment_bind
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_wide_work_item_revision"
down_revision: str | Sequence[str] | None = "0003_runtime_assignment_bind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("task_runtime_assignments") as batch:
        batch.alter_column(
            "work_item_revision", existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=True
        )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade from wide Business revisions is intentionally refused: "
        "it could truncate native work item revisions."
    )
