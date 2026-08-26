"""Create the complete project-workflow schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the current application schema."""
    op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), server_default="", nullable=False),
        sa.Column("hermes_profile", sa.String(length=251), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_agents_hermes_profile", "agents", ["hermes_profile"], unique=True)

    op.create_table(
        "workflows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), server_default="", nullable=False),
        sa.Column("is_default", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("is_default IN (0, 1)", name="ck_workflows_is_default"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "phases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("min_time_min", sa.Integer(), server_default="0", nullable=False),
        sa.Column("phase_order", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=True),
        sa.Column("next_recommendation", sa.Text(), nullable=True),
        sa.Column("parallel_with", sa.String(), nullable=True),
        sa.Column("rollback_target", sa.String(), nullable=True),
        sa.Column("execution_type", sa.String(), server_default="sync", nullable=False),
        sa.Column("is_seed_managed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_blocker", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_delegated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_critic", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("execution_type IN ('sync', 'parallel')", name="ck_phases_execution_type"),
        sa.CheckConstraint("is_blocker IN (0, 1)", name="ck_phases_is_blocker"),
        sa.CheckConstraint("is_critic IN (0, 1)", name="ck_phases_is_critic"),
        sa.CheckConstraint("is_delegated IN (0, 1)", name="ck_phases_is_delegated"),
        sa.CheckConstraint("is_seed_managed IN (0, 1)", name="ck_phases_is_seed_managed"),
        sa.CheckConstraint("phase_order > 0", name="ck_phases_phase_order_positive"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "code", name="uq_phases_workflow_code"),
    )

    op.create_table(
        "instructions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=False),
        sa.Column("step_num", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("execution_type", sa.String(), server_default="sync", nullable=False),
        sa.Column("skills", sa.Text(), nullable=True),
        sa.CheckConstraint("execution_type IN ('sync', 'parallel')", name="ck_instructions_execution_type"),
        sa.CheckConstraint("step_num > 0", name="ck_instructions_step_num_positive"),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phase_id", "step_num", name="uq_instructions_phase_step"),
    )

    op.create_table(
        "checks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phase_id", "description", name="uq_checks_phase_description"),
    )

    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phase_id", "description", name="uq_evidence_phase_description"),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("key_prefixes", sa.String(), server_default="[]", nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("task_key", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("current_phase", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.CheckConstraint("length(trim(current_phase)) > 0", name="ck_tasks_current_phase_nonblank"),
        sa.CheckConstraint("status IN ('active', 'done', 'blocked')", name="ck_tasks_status"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_key"),
    )

    op.create_table(
        "task_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'done', 'partial', 'blocked', 'rollback', 'delegated')",
            name="ck_task_history_status",
        ),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "phase_id", name="uq_task_history_task_phase"),
    )

    op.create_table(
        "supervisor_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("report", sa.Text(), server_default="", nullable=False),
        sa.Column("covered", sa.Text(), server_default="[]", nullable=False),
        sa.Column("missing", sa.Text(), server_default="[]", nullable=False),
        sa.Column("blockers", sa.Text(), server_default="[]", nullable=False),
        sa.Column("next_phase_id", sa.Integer(), nullable=True),
        sa.Column("rollback_phase_id", sa.Integer(), nullable=True),
        sa.Column("report_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("context_snapshot", sa.Text(), server_default="{}", nullable=False),
        sa.Column("response", sa.Text(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.CheckConstraint(
            "verdict IN ('pass', 'partial', 'blocked', 'rollback', 'delegate')",
            name="ck_supervisor_runs_verdict",
        ),
        sa.ForeignKeyConstraint(["next_phase_id"], ["phases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rollback_phase_id"], ["phases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_supervisor_runs_task_phase_report_fingerprint",
        "supervisor_runs",
        ["task_id", "phase_id", "report_fingerprint"],
        unique=True,
    )


def downgrade() -> None:
    """Drop all application tables in reverse dependency order."""
    op.drop_index("uq_supervisor_runs_task_phase_report_fingerprint", table_name="supervisor_runs")
    op.drop_table("supervisor_runs")
    op.drop_table("task_history")
    op.drop_table("tasks")
    op.drop_table("projects")
    op.drop_table("evidence")
    op.drop_table("checks")
    op.drop_table("instructions")
    op.drop_table("phases")
    op.drop_table("workflows")
    op.drop_index("uq_agents_hermes_profile", table_name="agents")
    op.drop_table("agents")
