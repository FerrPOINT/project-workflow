"""Name the built-in namespace workflows without changing execution identity."""

import sqlalchemy as sa
from alembic import op

revision = "0010_namespace_default_names"
down_revision = "0009_pm_draft_assignment"
branch_labels = None
depends_on = None

# Frozen presentation migration; keys and all task/phase/history IDs stay intact.
_ROLES = ("project_manager", "analyst", "architect", "developer", "reviewer", "tester", "devops")


def upgrade() -> None:
    workflows = sa.table("workflows", sa.column("key", sa.String()), sa.column("name", sa.String()))
    op.get_bind().execute(
        workflows.update()
        .where(workflows.c.key.in_([f"hermes-sdlc:{role}" for role in _ROLES]))
        .values(name="Дефолтный")
    )


def downgrade() -> None:
    # There is no schema change to undo. Retain the requested display names
    # rather than guessing earlier user edits or deleting seeded namespaces.
    pass
