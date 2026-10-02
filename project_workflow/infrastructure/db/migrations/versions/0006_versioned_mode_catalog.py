"""Version mode catalogs without modifying pinned assignments or phases."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_versioned_mode_catalog"
down_revision: str | Sequence[str] | None = "0005_mode_execution_scopes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workflows") as batch:
        batch.add_column(sa.Column("active_catalog_version", sa.Integer(), nullable=False, server_default="1"))
        batch.create_check_constraint("ck_workflows_catalog_version", "active_catalog_version > 0")
    with op.batch_alter_table("workflow_modes") as batch:
        batch.add_column(sa.Column("catalog_version", sa.Integer(), nullable=False, server_default="1"))
        batch.drop_constraint("uq_workflow_modes_workflow_key", type_="unique")
        batch.drop_constraint("uq_workflow_modes_workflow_order", type_="unique")
        batch.create_unique_constraint("uq_workflow_modes_workflow_key", ["workflow_id", "key", "catalog_version"])
        batch.create_unique_constraint(
            "uq_workflow_modes_workflow_order", ["workflow_id", "mode_order", "catalog_version"]
        )
        batch.create_check_constraint("ck_workflow_modes_catalog_version", "catalog_version > 0")


def downgrade() -> None:
    raise RuntimeError("Versioned mode history cannot be safely flattened")
