"""use canonical Relevanter Tech skill name

Revision ID: d4e8f1a2b703
Revises: 9b71d2e4c6a0
Create Date: 2026-08-23
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e8f1a2b703"
down_revision: str | Sequence[str] | None = "9b71d2e4c6a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "project_workflow"
WORKFLOW_NAME = "sdlc-business-tech-v1"
def _table(name: str) -> str:
    return f"{SCHEMA}.{name}" if op.get_bind().dialect.name == "postgresql" else name


def _replace_skill(old: str, new: str) -> None:
    instructions = _table("instructions")
    phases = _table("phases")
    workflows = _table("workflows")
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            f"SELECT i.id, i.skills FROM {instructions} i "
            f"JOIN {phases} p ON p.id = i.phase_id "
            f"JOIN {workflows} w ON w.id = p.workflow_id "
            "WHERE w.name = :workflow_name AND p.is_seed_managed = 1"
        ),
        {"workflow_name": WORKFLOW_NAME},
    ).all()
    for instruction_id, raw_skills in rows:
        skills = json.loads(raw_skills or "[]")
        if not isinstance(skills, list) or old not in skills:
            continue
        updated = [new if skill == old else skill for skill in skills]
        conn.execute(
            sa.text(f"UPDATE {instructions} SET skills = :skills WHERE id = :instruction_id"),
            {
                "skills": json.dumps(updated, ensure_ascii=False),
                "instruction_id": instruction_id,
            },
        )


def upgrade() -> None:
    _replace_skill("rtech", "using-rtech")


def downgrade() -> None:
    _replace_skill("using-rtech", "rtech")
