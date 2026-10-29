"""Add publication receipts without rewriting any installed catalog/history."""

import sqlalchemy as sa
from alembic import op

revision = "0022_catalog_publication"
down_revision = "0021_profession_task_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_catalog_publications",
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflows.id"), primary_key=True),
        sa.Column("catalog_version", sa.Integer(), primary_key=True),
        sa.Column("parent_version", sa.Integer(), nullable=False),
        sa.Column("operation_key", sa.String(128), nullable=False, unique=True),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "catalog_version > parent_version AND parent_version > 0", name="ck_catalog_publication_order",
        ),
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM workflow_catalog_publications LIMIT 1")).first():
        raise RuntimeError("Published instruction history is forward-only")
    op.drop_table("workflow_catalog_publications")
