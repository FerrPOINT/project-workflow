"""Record publication authors without inventing authorship for earlier receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0023_catalog_publication_author"
down_revision = "0022_catalog_publication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_catalog_publications") as batch:
        batch.add_column(sa.Column("published_by_subject", sa.String(255), nullable=True))
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint(
            "ck_catalog_publication_author",
            "(published_by_subject IS NULL AND published_at IS NULL) OR "
            "(published_by_subject IS NOT NULL AND length(trim(published_by_subject)) > 0 "
            "AND published_at IS NOT NULL)",
        )


def downgrade() -> None:
    if op.get_bind().execute(sa.text(
        "SELECT 1 FROM workflow_catalog_publications WHERE published_by_subject IS NOT NULL LIMIT 1",
    )).first():
        raise RuntimeError("Published authorship is forward-only")
    with op.batch_alter_table("workflow_catalog_publications") as batch:
        batch.drop_constraint("ck_catalog_publication_author", type_="check")
        batch.drop_column("published_at")
        batch.drop_column("published_by_subject")
