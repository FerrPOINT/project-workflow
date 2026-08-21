"""add agent Hermes profile binding

Revision ID: c31a9f6d4e20
Revises: b7f3c9d2a641
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c31a9f6d4e20"
down_revision: str | Sequence[str] | None = "b7f3c9d2a641"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "project_workflow"
TABLE = "agents"
INDEX = "uq_agents_hermes_profile"


def _schema() -> str | None:
    return SCHEMA if op.get_bind().dialect.name == "postgresql" else None


def upgrade() -> None:
    schema = _schema()
    if schema:
        op.execute(f"SET search_path TO {schema}")
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(TABLE, schema=schema)}
    if "hermes_profile" not in columns:
        op.add_column(TABLE, sa.Column("hermes_profile", sa.String(length=251), nullable=True), schema=schema)
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(TABLE, schema=schema)}
    if INDEX not in indexes:
        op.create_index(INDEX, TABLE, ["hermes_profile"], unique=True, schema=schema)


def downgrade() -> None:
    schema = _schema()
    if schema:
        op.execute(f"SET search_path TO {schema}")
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes(TABLE, schema=schema)}
    if INDEX in indexes:
        op.drop_index(INDEX, table_name=TABLE, schema=schema)
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(TABLE, schema=schema)}
    if "hermes_profile" in columns:
        op.drop_column(TABLE, "hermes_profile", schema=schema)
