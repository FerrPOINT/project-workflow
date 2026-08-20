"""narrow supervisor verdicts

Revision ID: f61c2a7d9e04
Revises: e4a7b19c2d01
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f61c2a7d9e04"
down_revision: str | Sequence[str] | None = "e4a7b19c2d01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "project_workflow"
TABLE = "supervisor_runs"
CONSTRAINT = "ck_supervisor_runs_verdict"
CURRENT_CHECK = "verdict IN ('pass', 'partial', 'blocked', 'rollback', 'delegate')"
LEGACY_CHECK = "verdict IN ('pass', 'partial', 'soft_fail', 'hard_fail', 'blocked', 'rollback', 'delegate')"


def _schema() -> str | None:
    return SCHEMA if op.get_bind().dialect.name == "postgresql" else None


def _replace_constraint(check: str) -> None:
    schema = _schema()
    with op.batch_alter_table(TABLE, schema=schema) as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.create_check_constraint(CONSTRAINT, check)


def upgrade() -> None:
    schema = _schema()
    table = f"{schema}.{TABLE}" if schema else TABLE
    op.execute(sa.text(f"UPDATE {table} SET verdict = 'partial' WHERE verdict = 'soft_fail'"))
    op.execute(sa.text(f"UPDATE {table} SET verdict = 'blocked' WHERE verdict = 'hard_fail'"))
    _replace_constraint(CURRENT_CHECK)


def downgrade() -> None:
    _replace_constraint(LEGACY_CHECK)
