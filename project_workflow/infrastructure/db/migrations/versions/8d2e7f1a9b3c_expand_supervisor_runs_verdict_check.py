"""expand supervisor_runs verdict check for soft_fail and hard_fail

Revision ID: 8d2e7f1a9b3c
Revises: 7a1e9c3b4d5f
Create Date: 2026-06-28 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = '8d2e7f1a9b3c'
down_revision: Union[str, Sequence[str], None] = '7a1e9c3b4d5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "project_workflow"
TABLE = "supervisor_runs"
CONSTRAINT = "ck_supervisor_runs_verdict"

NEW_CHECK = "verdict IN ('pass', 'partial', 'soft_fail', 'hard_fail', 'blocked', 'rollback', 'delegate')"
OLD_CHECK = "verdict IN ('pass', 'partial', 'blocked', 'rollback', 'delegate')"


def upgrade() -> None:
    """Add soft_fail and hard_fail to the verdict check constraint."""
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute(text(f"ALTER TABLE {SCHEMA}.{TABLE} DROP CONSTRAINT IF EXISTS {CONSTRAINT}"))
        op.execute(text(f"ALTER TABLE {SCHEMA}.{TABLE} ADD CONSTRAINT {CONSTRAINT} CHECK ({NEW_CHECK})"))


def downgrade() -> None:
    """Revert the verdict check constraint."""
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute(text(f"ALTER TABLE {SCHEMA}.{TABLE} DROP CONSTRAINT IF EXISTS {CONSTRAINT}"))
        op.execute(text(f"ALTER TABLE {SCHEMA}.{TABLE} ADD CONSTRAINT {CONSTRAINT} CHECK ({OLD_CHECK})"))
