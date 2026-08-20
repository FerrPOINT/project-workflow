"""backfill default workflow skill recommendations

Revision ID: b7f3c9d2a641
Revises: e92c4f7a1b63
Create Date: 2026-08-20
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7f3c9d2a641"
down_revision: str | Sequence[str] | None = "e92c4f7a1b63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "project_workflow"

PHASE_SKILLS: dict[str, list[list[str]]] = {
    "0.9": [
        ["agent-workflow-patterns"],
        ["workflow-systematic-debugging"],
        ["agent-workflow-patterns"],
    ],
    "0.6": [
        ["workflow-code-intelligence"],
        ["workflow-code-intelligence"],
        ["workflow-systematic-debugging"],
    ],
    "1.5": [
        ["workflow-code-intelligence"],
        ["workflow-code-intelligence"],
        ["workflow-systematic-debugging"],
    ],
    "3.5": [
        ["agent-workflow-patterns"],
        ["workflow-systematic-debugging"],
        ["workflow-writing-plans"],
    ],
    "4.5": [
        ["agent-workflow-patterns"],
        ["workflow-systematic-debugging"],
        ["test-driven-development"],
    ],
    "7.5": [
        ["repo-workflow"],
        ["workflow-systematic-debugging"],
        ["test-driven-development"],
    ],
    "7.6": [["test-driven-development"], ["workflow-systematic-debugging"]],
    "7.6.R": [["workflow-code-intelligence"], ["workflow-systematic-debugging"]],
    "7.7": [
        ["agent-workflow-patterns"],
        ["workflow-systematic-debugging"],
        ["agent-workflow-patterns"],
    ],
    "8": [["repo-workflow"], ["repo-workflow"], ["agent-workflow-patterns"]],
    "9": [
        ["agent-workflow-patterns"],
        ["workflow-code-intelligence"],
        ["workflow-writing-plans"],
    ],
}


def _table(name: str) -> str:
    return f"{SCHEMA}.{name}" if op.get_bind().dialect.name == "postgresql" else name


def upgrade() -> None:
    conn = op.get_bind()
    workflows = _table("workflows")
    phases = _table("phases")
    instructions = _table("instructions")

    for code, skill_steps in PHASE_SKILLS.items():
        phase_id = conn.execute(
            sa.text(
                f"SELECT p.id FROM {phases} p "
                f"JOIN {workflows} w ON w.id = p.workflow_id "
                "WHERE w.is_default = 1 AND p.is_seed_managed = 1 AND p.code = :code"
            ),
            {"code": code},
        ).scalar()
        if phase_id is None:
            continue

        for step_num, skills in enumerate(skill_steps, start=1):
            conn.execute(
                sa.text(
                    f"UPDATE {instructions} SET skills = :skills "
                    "WHERE phase_id = :phase_id AND step_num = :step_num "
                    "AND (skills IS NULL OR trim(skills) IN ('', '[]'))"
                ),
                {
                    "phase_id": phase_id,
                    "step_num": step_num,
                    "skills": json.dumps(skills, ensure_ascii=False),
                },
            )


def downgrade() -> None:
    # User-managed instruction values cannot be distinguished after the backfill.
    pass
