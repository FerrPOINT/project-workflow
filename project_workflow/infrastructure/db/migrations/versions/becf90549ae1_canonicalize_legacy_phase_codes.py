"""canonicalize legacy phase codes

Revision ID: becf90549ae1
Revises: 75bc288f78c6
Create Date: 2026-07-09 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "becf90549ae1"
down_revision: str | Sequence[str] | None = "75bc288f78c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_LEGACY_REDIRECTS = {
    "0.01a": "0.00",
    "0.01b": "0.00",
    "0": "0.00",
}


def upgrade() -> None:
    """Canonicalize legacy Task.current_phase values."""
    conn = op.get_bind()
    for old_code, new_code in _LEGACY_REDIRECTS.items():
        conn.execute(
            text("UPDATE tasks SET current_phase = :new WHERE current_phase = :old"),
            {"old": old_code, "new": new_code},
        )


def downgrade() -> None:
    """Restore legacy codes for known values.

    This is not a perfect reversal; it rewrites all rows matching the canonical
    target back to the first legacy code in the original map.
    """
    conn = op.get_bind()
    reverse = {}
    for old, new in _LEGACY_REDIRECTS.items():
        if new not in reverse:
            reverse[new] = old
    for new_code, old_code in reverse.items():
        conn.execute(
            text("UPDATE tasks SET current_phase = :old WHERE current_phase = :new"),
            {"old": old_code, "new": new_code},
        )
