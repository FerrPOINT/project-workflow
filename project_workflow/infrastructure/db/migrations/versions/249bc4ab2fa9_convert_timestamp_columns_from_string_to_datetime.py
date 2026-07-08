"""convert timestamp columns from string to datetime

Revision ID: 249bc4ab2fa9
Revises: caeb9ba65f4a
Create Date: 2026-07-06 05:55:13.894

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "249bc4ab2fa9"
down_revision: str | None = "caeb9ba65f4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES_COLUMNS = [
    ("tasks", "created_at"),
    ("tasks", "updated_at"),
    ("task_history", "completed_at"),
    ("supervisor_runs", "created_at"),
    ("cli_history", "created_at"),
    ("wizard_memories", "created_at"),
]


def _convert_text_to_timestamp(table: str, column: str) -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        # Drop the old text default first; it cannot be cast to timestamp.
        op.execute(sa.text(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT"))
        # Normalize placeholder values to a valid timestamp string.
        op.execute(
            sa.text(
                f"UPDATE {table} SET {column} = NOW() "
                f"WHERE {column} = 'CURRENT_TIMESTAMP' OR {column} = 'CURRENT_TIMESTAM' "
                f"OR {column} IS NULL"
            )
        )
        # Cast remaining textual timestamps.
        op.execute(
            sa.text(
                f"ALTER TABLE {table} ALTER COLUMN {column} TYPE TIMESTAMP WITH TIME ZONE "
                f"USING CASE WHEN {column} IS NULL THEN NOW() ELSE {column}::timestamp with time zone END"
            )
        )
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(timezone=True),
            existing_nullable=True,
            server_default=sa.text("now()"),
        )
    else:
        # SQLite path: recreate column via batch alter.
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                column,
                existing_type=sa.String(),
                type_=sa.DateTime(timezone=True),
                existing_nullable=True,
            )


def _revert_timestamp_to_text(table: str, column: str) -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            type_=sa.String(),
            existing_nullable=True,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )
    else:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                column,
                existing_type=sa.DateTime(timezone=True),
                type_=sa.String(),
                existing_nullable=True,
            )


def upgrade() -> None:
    for table, column in _TABLES_COLUMNS:
        _convert_text_to_timestamp(table, column)


def downgrade() -> None:
    for table, column in reversed(_TABLES_COLUMNS):
        _revert_timestamp_to_text(table, column)
