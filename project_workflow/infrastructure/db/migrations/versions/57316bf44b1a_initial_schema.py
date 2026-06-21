"""initial schema

Revision ID: 57316bf44b1a
Revises:
Create Date: 2026-06-21 14:43:30.436445

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '57316bf44b1a'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables from ORM models in the project_workflow schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS project_workflow")
    op.execute("SET search_path TO project_workflow")
    # Import models here so Base.metadata sees them.
    from project_workflow.infrastructure.db import models  # noqa: F401
    from project_workflow.infrastructure.db.models import Base
    bind = op.get_bind()
    Base.metadata.create_all(bind)


def downgrade() -> None:
    """Drop all tables."""
    op.execute("SET search_path TO project_workflow")
    from project_workflow.infrastructure.db import models  # noqa: F401
    from project_workflow.infrastructure.db.models import Base
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
    op.execute("DROP SCHEMA IF NOT EXISTS project_workflow CASCADE")
