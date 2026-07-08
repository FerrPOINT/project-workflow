"""rename projects key_patterns to key_prefixes (no-op)

Revision ID: 7a1e9c3b4d5f
Revises: 57316bf44b1a
Create Date: 2026-06-22 02:30:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "7a1e9c3b4d5f"
down_revision: str | Sequence[str] | None = "57316bf44b1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: the initial schema already creates projects.key_prefixes."""


def downgrade() -> None:
    """No-op reverse."""
