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
    op.create_index("uq_agents_name", "agents", ["name"], unique=True)
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
        sa.Column("phase_order", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=True),
        sa.Column("parallel_with_phase_id", sa.Integer(), nullable=True),
        sa.Column("rollback_target_phase_id", sa.Integer(), nullable=True),
        sa.Column("execution_type", sa.String(), server_default="sync", nullable=False),
        sa.CheckConstraint("execution_type IN ('sync', 'parallel')", name="ck_phases_execution_type"),
        sa.CheckConstraint("phase_order > 0", name="ck_phases_phase_order_positive"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["parallel_with_phase_id", "workflow_id"],
            ["phases.id", "phases.workflow_id"],
            name="fk_phases_parallel_with_workflow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rollback_target_phase_id", "workflow_id"],
            ["phases.id", "phases.workflow_id"],
            name="fk_phases_rollback_target_workflow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workflow_id", name="uq_phases_id_workflow"),
        sa.UniqueConstraint("workflow_id", "code", name="uq_phases_workflow_code"),
        sa.UniqueConstraint("workflow_id", "phase_order", name="uq_phases_workflow_order"),
    )

    op.create_table(
        "phase_instructions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=False),
        sa.Column("step_num", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("execution_type", sa.String(), server_default="sync", nullable=False),
        sa.Column("skills", sa.Text(), nullable=True),
        sa.CheckConstraint("execution_type IN ('sync', 'parallel')", name="ck_phase_instructions_execution_type"),
        sa.CheckConstraint("step_num > 0", name="ck_phase_instructions_step_num_positive"),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phase_id", "step_num", name="uq_phase_instructions_phase_step"),
    )

    op.create_table(
        "phase_checks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phase_id", "description", name="uq_phase_checks_description"),
    )

    op.create_table(
        "phase_evidence_requirements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "phase_id", "description", name="uq_phase_evidence_requirements_description"
        ),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("theme_icon", sa.String(length=32), server_default="folder", nullable=False),
        sa.Column("theme_color", sa.String(length=7), server_default="#5E6AD2", nullable=False),
        sa.Column("cli_command", sa.String(length=64), nullable=False),
        sa.Column("key_prefixes", sa.String(), server_default="[]", nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("cli_command"),
        sa.UniqueConstraint("id", "workflow_id", name="uq_projects_id_workflow"),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("task_key", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("current_phase_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.CheckConstraint("status IN ('active', 'done', 'blocked')", name="ck_tasks_status"),
        sa.ForeignKeyConstraint(
            ["project_id", "workflow_id"],
            ["projects.id", "projects.workflow_id"],
            name="fk_tasks_project_workflow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_phase_id", "workflow_id"],
            ["phases.id", "phases.workflow_id"],
            name="fk_tasks_current_phase_workflow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workflow_id", name="uq_tasks_id_workflow"),
        sa.UniqueConstraint("project_id", "task_key", name="uq_tasks_project_task_key"),
    )
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])
    op.create_index("ix_tasks_workflow_id", "tasks", ["workflow_id"])
    op.create_index("ix_tasks_current_phase_id", "tasks", ["current_phase_id"])

    op.create_table(
        "task_step_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("worker_report", sa.Text(), server_default="", nullable=False),
        sa.Column("covered_item_ids", sa.Text(), server_default="[]", nullable=False),
        sa.Column("missing_item_ids", sa.Text(), server_default="[]", nullable=False),
        sa.Column("blocker_messages", sa.Text(), server_default="[]", nullable=False),
        sa.Column("next_phase_id", sa.Integer(), nullable=True),
        sa.Column("rollback_phase_id", sa.Integer(), nullable=True),
        sa.Column("replay_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("evaluation_snapshot", sa.Text(), server_default="{}", nullable=False),
        sa.Column("supervisor_response", sa.Text(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "verdict IN ('pass', 'partial', 'blocked', 'rollback', 'delegate')",
            name="ck_task_step_history_verdict",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "workflow_id"],
            ["tasks.id", "tasks.workflow_id"],
            name="fk_task_step_history_task_workflow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["phase_id", "workflow_id"],
            ["phases.id", "phases.workflow_id"],
            name="fk_task_step_history_phase_workflow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["next_phase_id", "workflow_id"],
            ["phases.id", "phases.workflow_id"],
            name="fk_task_step_history_next_phase_workflow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rollback_phase_id", "workflow_id"],
            ["phases.id", "phases.workflow_id"],
            name="fk_task_step_history_rollback_phase_workflow",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "task_id", name="uq_task_step_history_id_task"),
    )
    op.create_index(
        "uq_task_step_history_replay",
        "task_step_history",
        ["task_id", "phase_id", "replay_fingerprint"],
        unique=True,
    )
    op.create_index("ix_task_step_history_phase_id", "task_step_history", ["phase_id"])
    op.create_index("ix_task_step_history_next_phase_id", "task_step_history", ["next_phase_id"])
    op.create_index("ix_task_step_history_rollback_phase_id", "task_step_history", ["rollback_phase_id"])

    op.create_table(
        "task_phase_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=False),
        sa.Column("step_history_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('entered', 'completed', 'blocked', 'resumed', 'rolled_back')",
            name="ck_task_phase_events_event_type",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "workflow_id"],
            ["tasks.id", "tasks.workflow_id"],
            name="fk_task_phase_events_task_workflow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["phase_id", "workflow_id"],
            ["phases.id", "phases.workflow_id"],
            name="fk_task_phase_events_phase_workflow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["step_history_id", "task_id"],
            ["task_step_history.id", "task_step_history.task_id"],
            name="fk_task_phase_events_step_task",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_phase_events_task_id_id", "task_phase_events", ["task_id", "id"])
    op.create_index("ix_task_phase_events_phase_id", "task_phase_events", ["phase_id"])
    op.create_index("ix_task_phase_events_step_history_id", "task_phase_events", ["step_history_id"])


def downgrade() -> None:
    """Drop all application tables in reverse dependency order."""
    op.drop_index("ix_task_phase_events_step_history_id", table_name="task_phase_events")
    op.drop_index("ix_task_phase_events_phase_id", table_name="task_phase_events")
    op.drop_index("ix_task_phase_events_task_id_id", table_name="task_phase_events")
    op.drop_table("task_phase_events")
    op.drop_index("ix_task_step_history_rollback_phase_id", table_name="task_step_history")
    op.drop_index("ix_task_step_history_next_phase_id", table_name="task_step_history")
    op.drop_index("ix_task_step_history_phase_id", table_name="task_step_history")
    op.drop_index("uq_task_step_history_replay", table_name="task_step_history")
    op.drop_table("task_step_history")
    op.drop_index("ix_tasks_current_phase_id", table_name="tasks")
    op.drop_index("ix_tasks_workflow_id", table_name="tasks")
    op.drop_index("ix_tasks_project_id", table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("projects")
    op.drop_table("phase_evidence_requirements")
    op.drop_table("phase_checks")
    op.drop_table("phase_instructions")
    op.drop_table("phases")
    op.drop_table("workflows")
    op.drop_index("uq_agents_hermes_profile", table_name="agents")
    op.drop_index("uq_agents_name", table_name="agents")
    op.drop_table("agents")
