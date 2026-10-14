"""Allow retained sequential PM executions of one Tracker task, not replacement."""

from alembic import op

revision = "0016_pm_review_executions"
down_revision = "0015_single_task_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("pm_executions") as batch:
        batch.drop_constraint("uq_pm_task_agent", type_="unique")
        batch.create_index("ix_pm_task_agent", ["tracker_instance_ref", "task_ref", "agent_ref"])


def downgrade() -> None:
    raise RuntimeError("PM review execution/history must be preserved; restore a pre-migration backup")
