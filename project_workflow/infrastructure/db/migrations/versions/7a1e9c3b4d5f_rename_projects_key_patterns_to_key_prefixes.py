"""rename projects key_patterns to key_prefixes

Revision ID: 7a1e9c3b4d5f
Revises: 57316bf44b1a
Create Date: 2026-06-22 02:30:00.000000

"""
import json
import re
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = '7a1e9c3b4d5f'
down_revision: Union[str, Sequence[str], None] = '57316bf44b1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _patterns_to_prefixes(raw: str | None) -> list[str]:
    """Convert legacy regex pattern JSON to plain prefix list."""
    if not raw:
        return []
    try:
        patterns = json.loads(raw) if isinstance(raw, str) else []
    except Exception:
        return []
    if not isinstance(patterns, list):
        return []
    prefixes = []
    for pattern in patterns:
        match = re.search(r"\?P<prefix>([^)]+)", str(pattern))
        if match:
            prefixes.append(match.group(1))
    return prefixes


def upgrade() -> None:
    """Rename projects.key_patterns column to key_prefixes and convert data."""
    op.execute("SET search_path TO project_workflow")
    op.execute(text("ALTER TABLE projects RENAME COLUMN key_patterns TO key_prefixes"))

    conn = op.get_bind()
    rows = conn.execute(text("SELECT id, code, key_prefixes FROM projects")).fetchall()
    for row in rows:
        prefixes = _patterns_to_prefixes(row.key_prefixes)
        if not prefixes and row.code:
            prefixes = [row.code]
        conn.execute(
            text("UPDATE projects SET key_prefixes = :prefixes WHERE id = :id"),
            {"prefixes": json.dumps(prefixes, ensure_ascii=False), "id": row.id},
        )


def downgrade() -> None:
    """Rename projects.key_prefixes column back to key_patterns."""
    op.execute("SET search_path TO project_workflow")
    op.execute(text("ALTER TABLE projects RENAME COLUMN key_prefixes TO key_patterns"))
