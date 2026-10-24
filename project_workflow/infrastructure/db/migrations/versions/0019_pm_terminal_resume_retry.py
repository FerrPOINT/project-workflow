"""Extend only the PM operation ledger kind; retain all existing rows."""

import sqlalchemy as sa
from alembic import op

revision = "0019_pm_terminal_resume_retry"
down_revision = "0018_identity_deletion_owner"
branch_labels = None
depends_on = None


def _kind(values: str) -> None:
    with op.batch_alter_table("pm_operations") as batch:
        batch.drop_constraint("ck_pm_operation_kind", type_="check")
        batch.create_check_constraint("ck_pm_operation_kind", f"kind IN ({values})")


def upgrade() -> None:
    _kind("'bind', 'checkpoint', 'resume', 'rebind', 'resume_retry'")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM pm_operations WHERE kind='resume_retry' LIMIT 1")).first():
        raise RuntimeError("Retained PM resume retry receipts prevent downgrade")
    _kind("'bind', 'checkpoint', 'resume', 'rebind'")
