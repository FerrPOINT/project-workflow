"""add report fingerprint

Revision ID: e4a7b19c2d01
Revises: becf90549ae1
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4a7b19c2d01"
down_revision: str | Sequence[str] | None = "becf90549ae1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "project_workflow"
TABLE = "supervisor_runs"
INDEX = "uq_supervisor_runs_task_report_fingerprint"


def _schema() -> str | None:
    return SCHEMA if op.get_bind().dialect.name == "postgresql" else None


def upgrade() -> None:
    schema = _schema()
    if schema:
        op.execute(f"SET search_path TO {schema}")
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(TABLE, schema=schema)}
    if "report_fingerprint" not in columns:
        op.add_column(
            TABLE,
            sa.Column("report_fingerprint", sa.String(length=64), nullable=True),
            schema=schema,
        )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(TABLE, schema=schema)}
    if INDEX not in indexes:
        op.create_index(
            INDEX,
            TABLE,
            ["task_id", "report_fingerprint"],
            unique=True,
            schema=schema,
        )


def downgrade() -> None:
    schema = _schema()
    if schema:
        op.execute(f"SET search_path TO {schema}")
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes(TABLE, schema=schema)}
    if INDEX in indexes:
        op.drop_index(INDEX, table_name=TABLE, schema=schema)
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(TABLE, schema=schema)}
    if "report_fingerprint" in columns:
        op.drop_column(TABLE, "report_fingerprint", schema=schema)
