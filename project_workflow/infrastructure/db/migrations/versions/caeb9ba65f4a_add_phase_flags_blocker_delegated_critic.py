"""add phase flags blocker delegated critic

Revision ID: caeb9ba65f4a
Revises: 8d2e7f1a9b3c
Create Date: 2026-07-06 05:03:16.507000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = 'caeb9ba65f4a'
down_revision: Union[str, Sequence[str], None] = '8d2e7f1a9b3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "project_workflow"
TABLE = "phases"


def _column_exists(column: str) -> bool:
    """Return True if the column already exists in the phases table."""
    bind = op.get_bind()
    result = bind.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = :schema
              AND table_name = :table
              AND column_name = :column
            """
        ),
        {"schema": SCHEMA, "table": TABLE, "column": column},
    )
    return result.scalar() is not None


def upgrade() -> None:
    """Add is_blocker, is_delegated, is_critic boolean columns to phases."""
    op.execute(f"SET search_path TO {SCHEMA}")
    for column in ("is_blocker", "is_delegated", "is_critic"):
        if not _column_exists(column):
            op.execute(
                f"ALTER TABLE {TABLE} ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"
            )
            op.execute(
                f"ALTER TABLE {TABLE} ADD CONSTRAINT ck_phases_{column} CHECK ({column} IN (0, 1))"
            )


def downgrade() -> None:
    """Drop the boolean flag columns added in this migration."""
    op.execute(f"SET search_path TO {SCHEMA}")
    for column in ("is_blocker", "is_delegated", "is_critic"):
        if _column_exists(column):
            op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS ck_phases_{column}")
            op.execute(f"ALTER TABLE {TABLE} DROP COLUMN {column}")
