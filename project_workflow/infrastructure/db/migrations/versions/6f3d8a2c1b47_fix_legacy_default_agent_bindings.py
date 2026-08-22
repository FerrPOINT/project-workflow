"""fix legacy default workflow agent bindings

Revision ID: 6f3d8a2c1b47
Revises: 4d7c2a9e6b10
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6f3d8a2c1b47"
down_revision: str | Sequence[str] | None = "4d7c2a9e6b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "project_workflow"


def _table(name: str) -> str:
    return f"{SCHEMA}.{name}" if op.get_bind().dialect.name == "postgresql" else name


def upgrade() -> None:
    conn = op.get_bind()
    workflows = _table("workflows")
    phases = _table("phases")
    agents = _table("agents")

    orchestrator_id = conn.execute(
        sa.text(
            f"SELECT id FROM {agents} WHERE hermes_profile = 'sdlc-orchestrator' "
            "ORDER BY id LIMIT 1"
        )
    ).scalar()
    if orchestrator_id is None:
        return

    conn.execute(
        sa.text(
            f"UPDATE {phases} SET agent_id = :orchestrator_id, is_delegated = 1 "
            "WHERE is_seed_managed = 1 AND code IN ('-1', '10') "
            f"AND workflow_id IN (SELECT id FROM {workflows} WHERE is_default = 1) "
            f"AND agent_id IN (SELECT id FROM {agents} WHERE name = 'None' "
            "AND description = 'Seed agent for -1' AND hermes_profile IS NULL)"
        ),
        {"orchestrator_id": orchestrator_id},
    )
    conn.execute(
        sa.text(
            f"UPDATE {phases} SET agent_id = :orchestrator_id, is_delegated = 1 "
            "WHERE is_seed_managed = 1 AND code = '9' "
            f"AND workflow_id IN (SELECT id FROM {workflows} WHERE is_default = 1) "
            f"AND agent_id IN (SELECT id FROM {agents} WHERE name = 'coder' "
            "AND description = 'Seed agent for 9' AND hermes_profile = 'sdlc-coder')"
        ),
        {"orchestrator_id": orchestrator_id},
    )
    conn.execute(
        sa.text(
            f"DELETE FROM {agents} WHERE name = 'None' "
            "AND description = 'Seed agent for -1' AND hermes_profile IS NULL "
            f"AND NOT EXISTS (SELECT 1 FROM {phases} WHERE agent_id = {agents}.id)"
        )
    )


def downgrade() -> None:
    # The corrected bindings are indistinguishable from later UI selections.
    pass
