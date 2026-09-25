"""initial schema

Revision ID: 57316bf44b1a
Revises:
Create Date: 2026-06-21 14:43:30.436445

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "57316bf44b1a"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all tables from ORM models in the project_workflow schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS project_workflow")
    op.execute("SET search_path TO project_workflow")
    # Import models here so Base.metadata sees them.
    from project_workflow.infrastructure.db import models  # noqa: F401
    from project_workflow.infrastructure.db.models import Base

    bind = op.get_bind()
    # This historical revision imports current metadata. Keep newly introduced
    # mode foreign keys nullable only while reconstructing the legacy schema so
    # older seed migrations can insert rows before the mode backfill revision.
    # Restore metadata immediately; the head migration makes the DB columns
    # non-null after backfill.
    mode_columns = [
        Base.metadata.tables[table_name].c.mode_id
        for table_name in ("phases", "tasks", "task_history", "supervisor_runs")
        if "mode_id" in Base.metadata.tables[table_name].c
    ]
    previous_nullable = [column.nullable for column in mode_columns]
    try:
        for column in mode_columns:
            column.nullable = True
        Base.metadata.create_all(bind)
    finally:
        for column, nullable in zip(mode_columns, previous_nullable, strict=True):
            column.nullable = nullable


def downgrade() -> None:
    """Drop all tables."""
    op.execute("SET search_path TO project_workflow")
    from project_workflow.infrastructure.db import models  # noqa: F401
    from project_workflow.infrastructure.db.models import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind)
    op.execute("DROP SCHEMA IF NOT EXISTS project_workflow CASCADE")
