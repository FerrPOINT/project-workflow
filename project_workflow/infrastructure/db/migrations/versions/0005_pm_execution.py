"""Persist PM execution identity, checkpoints, run proof and command results."""

import sqlalchemy as sa
from alembic import op

revision = "0005_pm_execution"
down_revision = "0004_wide_work_item_revision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("task_runtime_assignments") as batch:
        batch.add_column(sa.Column("concrete_agent_ref", sa.String(36), nullable=True))
        batch.create_check_constraint(
            "ck_task_runtime_assignments_concrete_agent_binding",
            "concrete_agent_ref IS NULL OR (length(concrete_agent_ref) = 36 AND "
            "concrete_agent_ref = lower(concrete_agent_ref) AND binding_ref IS NOT NULL AND "
            "hermes_run_ref IS NOT NULL AND bind_operation_key IS NOT NULL AND bind_request_sha256 IS NOT NULL)",
        )
    op.create_table(
        "pm_executions",
        sa.Column("execution_ref", sa.String(512), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("assignment_id", sa.Integer(),
                  sa.ForeignKey("task_runtime_assignments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False),
        *[sa.Column(name, sa.String(512), nullable=False) for name in (
            "tracker_instance_ref", "tracker_project_ref", "task_ref", "root_ref", "agent_ref")],
        sa.Column("session_run_id", sa.String(36), nullable=False),
        sa.Column("identity_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("fence", sa.BigInteger(), nullable=False),
        sa.Column("phase_id", sa.Integer(), sa.ForeignKey("phases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("checkpoint_json", sa.Text(), nullable=True),
        sa.Column("resume_operation_key", sa.String(128), nullable=True),
        sa.Column("resume_session_run_id", sa.String(36), nullable=True),
        sa.UniqueConstraint("task_id"),
        sa.UniqueConstraint("resume_session_run_id"),
        sa.UniqueConstraint("tracker_instance_ref", "task_ref", "agent_ref", name="uq_pm_task_agent"),
        sa.CheckConstraint("state IN ('active', 'waiting', 'resume_pending')", name="ck_pm_state"),
        sa.CheckConstraint("version > 0 AND fence > 0", name="ck_pm_versions"),
        sa.CheckConstraint("state = 'active' OR checkpoint_json IS NOT NULL", name="ck_pm_checkpoint"),
        sa.CheckConstraint(
            "state != 'resume_pending' OR (resume_operation_key IS NOT NULL AND resume_session_run_id IS NOT NULL)",
            name="ck_pm_resume",
        ),
    )
    op.create_table(
        "pm_runs",
        sa.Column("session_run_id", sa.String(36), primary_key=True),
        sa.Column("run_ref", sa.String(512), nullable=False),
        sa.Column("execution_ref", sa.String(512),
                  sa.ForeignKey("pm_executions.execution_ref", ondelete="RESTRICT"), nullable=False),
        sa.Column("binding_ref", sa.String(512), nullable=False),
        sa.Column("fence", sa.BigInteger(), nullable=False),
        sa.Column("observation_json", sa.Text(), nullable=False),
        sa.Column("terminal_json", sa.Text(), nullable=True),
        sa.UniqueConstraint("execution_ref", "fence", name="uq_pm_run_fence"),
        sa.CheckConstraint("fence > 0", name="ck_pm_run_fence"),
    )
    op.create_table(
        "pm_operations",
        sa.Column("operation_key", sa.String(128), primary_key=True),
        sa.Column("execution_ref", sa.String(512),
                  sa.ForeignKey("pm_executions.execution_ref", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.CheckConstraint("kind IN ('bind', 'checkpoint', 'resume', 'rebind')", name="ck_pm_operation_kind"),
        sa.CheckConstraint("length(request_sha256) = 64", name="ck_pm_operation_hash"),
    )


def downgrade() -> None:
    raise RuntimeError("PM execution downgrade refused: durable execution and replay evidence would be lost")
