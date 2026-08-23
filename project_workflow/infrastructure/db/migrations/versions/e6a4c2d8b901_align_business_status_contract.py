"""Align Business status contract with the default project catalog.

Revision ID: e6a4c2d8b901
Revises: d4e8f1a2b703
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6a4c2d8b901"
down_revision: str | Sequence[str] | None = "d4e8f1a2b703"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "project_workflow"
WORKFLOW_NAME = "sdlc-business-tech-v1"
PHASE_CODE = "9.PR"

OLD_INSTRUCTION = "Перевести Business-задачу в In Review и проверить activity"
NEW_INSTRUCTION = (
    "Подтвердить, что Business-задача остаётся In Progress, и проверить activity"
)
OLD_CHECK = "Business status равен In Review"
NEW_CHECK = "Business status равен In Progress"


def _table(name: str) -> str:
    return f"{SCHEMA}.{name}" if op.get_bind().dialect.name == "postgresql" else name


def _replace_exact(table_name: str, old: str, new: str) -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            f"SELECT item.id FROM {_table(table_name)} item "
            f"JOIN {_table('phases')} p ON p.id = item.phase_id "
            f"JOIN {_table('workflows')} w ON w.id = p.workflow_id "
            "WHERE w.name = :workflow_name AND p.code = :phase_code "
            "AND p.is_seed_managed = 1 AND item.description = :old"
        ),
        {"workflow_name": WORKFLOW_NAME, "phase_code": PHASE_CODE, "old": old},
    ).scalars()
    for item_id in rows:
        conn.execute(
            sa.text(f"UPDATE {_table(table_name)} SET description = :new WHERE id = :item_id"),
            {"new": new, "item_id": item_id},
        )


def upgrade() -> None:
    _replace_exact("instructions", OLD_INSTRUCTION, NEW_INSTRUCTION)
    _replace_exact("checks", OLD_CHECK, NEW_CHECK)


def downgrade() -> None:
    _replace_exact("instructions", NEW_INSTRUCTION, OLD_INSTRUCTION)
    _replace_exact("checks", NEW_CHECK, OLD_CHECK)
