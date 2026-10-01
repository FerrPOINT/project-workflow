"""Decouple mode from scope; legacy policies remain read-only.

Revision ID: 0005_mode_execution_scopes
Revises: 0004_wide_work_item_revision
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_mode_execution_scopes"
down_revision: str | Sequence[str] | None = "0004_wide_work_item_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_modes") as batch:
        batch.add_column(sa.Column("execution_scopes", sa.JSON(none_as_null=True), nullable=True))
        batch.drop_constraint("ck_workflow_modes_policy_complete", type_="check")
        batch.create_check_constraint(
            "ck_workflow_modes_policy_complete",
            "(role_key IS NULL AND execution_scope IS NULL AND execution_scopes IS NULL "
            "AND tech_workspace_policy IS NULL) OR "
            "(role_key IS NOT NULL AND (execution_scope IS NOT NULL OR execution_scopes IS NOT NULL) "
            "AND tech_workspace_policy IS NOT NULL)",
        )


def downgrade() -> None:
    raise RuntimeError("Scope-set policies cannot safely be downgraded to a single scope")
