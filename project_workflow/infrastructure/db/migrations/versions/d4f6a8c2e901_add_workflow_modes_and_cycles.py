"""add workflow modes and cycle-aware execution history

Revision ID: d4f6a8c2e901
Revises: becf90549ae1
Create Date: 2026-09-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4f6a8c2e901"
down_revision: str | Sequence[str] | None = "becf90549ae1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "project_workflow"


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _column_names(table: str) -> set[str]:
    schema = SCHEMA if op.get_bind().dialect.name == "postgresql" else None
    return {column["name"] for column in _inspector().get_columns(table, schema=schema)}


def _unique_names(table: str) -> set[str]:
    schema = SCHEMA if op.get_bind().dialect.name == "postgresql" else None
    return {item["name"] for item in _inspector().get_unique_constraints(table, schema=schema) if item.get("name")}


def _foreign_key_names(table: str) -> set[str]:
    schema = SCHEMA if op.get_bind().dialect.name == "postgresql" else None
    return {item["name"] for item in _inspector().get_foreign_keys(table, schema=schema) if item.get("name")}


def _foreign_key_columns(table: str) -> set[str]:
    schema = SCHEMA if op.get_bind().dialect.name == "postgresql" else None
    return {
        column
        for item in _inspector().get_foreign_keys(table, schema=schema)
        for column in item.get("constrained_columns", [])
    }


def _check_names(table: str) -> set[str]:
    schema = SCHEMA if op.get_bind().dialect.name == "postgresql" else None
    return {item["name"] for item in _inspector().get_check_constraints(table, schema=schema) if item.get("name")}


def _add_column_if_missing(table: str, column: sa.Column[object]) -> None:
    if column.name not in _column_names(table):
        op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"SET search_path TO {SCHEMA}")

    inspector = _inspector()
    schema = SCHEMA if bind.dialect.name == "postgresql" else None
    if "workflow_modes" not in inspector.get_table_names(schema=schema):
        op.create_table(
            "workflow_modes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("workflow_id", sa.Integer(), nullable=False),
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("mode_order", sa.Integer(), nullable=False, server_default="1"),
            sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("workflow_id", "key", name="uq_workflow_modes_workflow_key"),
            sa.UniqueConstraint("workflow_id", "mode_order", name="uq_workflow_modes_workflow_order"),
        )

    op.execute(
        sa.text(
            """
            INSERT INTO workflow_modes (workflow_id, key, name, mode_order)
            SELECT w.id, 'default', 'Default', 1
            FROM workflows w
            WHERE NOT EXISTS (
                SELECT 1 FROM workflow_modes wm
                WHERE wm.workflow_id = w.id AND wm.key = 'default'
            )
            """
        )
    )

    _add_column_if_missing("phases", sa.Column("mode_id", sa.Integer(), nullable=True))
    _add_column_if_missing("tasks", sa.Column("current_mode_id", sa.Integer(), nullable=True))
    _add_column_if_missing("tasks", sa.Column("cycle_number", sa.Integer(), nullable=True, server_default="0"))
    _add_column_if_missing("task_history", sa.Column("mode_id", sa.Integer(), nullable=True))
    _add_column_if_missing(
        "task_history", sa.Column("cycle_number", sa.Integer(), nullable=True, server_default="0")
    )
    _add_column_if_missing("supervisor_runs", sa.Column("mode_id", sa.Integer(), nullable=True))
    _add_column_if_missing(
        "supervisor_runs", sa.Column("cycle_number", sa.Integer(), nullable=True, server_default="0")
    )
    _add_column_if_missing(
        "supervisor_runs", sa.Column("attempt_number", sa.Integer(), nullable=True, server_default="1")
    )

    op.execute(
        sa.text(
            """
            UPDATE phases
            SET mode_id = (
                SELECT wm.id FROM workflow_modes wm
                WHERE wm.workflow_id = phases.workflow_id AND wm.key = 'default'
            )
            WHERE mode_id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE tasks
            SET current_mode_id = (
                SELECT wm.id
                FROM projects p
                JOIN workflow_modes wm ON wm.workflow_id = p.workflow_id AND wm.key = 'default'
                WHERE p.id = tasks.project_id
            )
            WHERE current_mode_id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE task_history
            SET mode_id = (SELECT p.mode_id FROM phases p WHERE p.id = task_history.phase_id),
                cycle_number = COALESCE(cycle_number, 0)
            WHERE mode_id IS NULL OR cycle_number IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE supervisor_runs
            SET mode_id = (SELECT p.mode_id FROM phases p WHERE p.id = supervisor_runs.phase_id),
                cycle_number = COALESCE(cycle_number, 0),
                attempt_number = COALESCE(attempt_number, 1)
            WHERE mode_id IS NULL OR cycle_number IS NULL OR attempt_number IS NULL
            """
        )
    )
    op.execute(sa.text("UPDATE tasks SET cycle_number = COALESCE(cycle_number, 0)"))

    phase_uniques = _unique_names("phases")
    phase_fks = _foreign_key_names("phases")
    phase_fk_columns = _foreign_key_columns("phases")
    with op.batch_alter_table("phases") as batch:
        batch.alter_column("mode_id", existing_type=sa.Integer(), nullable=False)
        if "uq_phases_workflow_code" in phase_uniques:
            batch.drop_constraint("uq_phases_workflow_code", type_="unique")
        if "uq_phases_mode_code" not in phase_uniques:
            batch.create_unique_constraint("uq_phases_mode_code", ["mode_id", "code"])
        if "fk_phases_mode_id_workflow_modes" not in phase_fks and "mode_id" not in phase_fk_columns:
            batch.create_foreign_key(
                "fk_phases_mode_id_workflow_modes", "workflow_modes", ["mode_id"], ["id"], ondelete="CASCADE"
            )

    task_fks = _foreign_key_names("tasks")
    task_fk_columns = _foreign_key_columns("tasks")
    task_checks = _check_names("tasks")
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column("cycle_number", existing_type=sa.Integer(), nullable=False, server_default="0")
        if "fk_tasks_current_mode_id_workflow_modes" not in task_fks and "current_mode_id" not in task_fk_columns:
            batch.create_foreign_key(
                "fk_tasks_current_mode_id_workflow_modes",
                "workflow_modes",
                ["current_mode_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "ck_tasks_cycle_number" not in task_checks:
            batch.create_check_constraint("ck_tasks_cycle_number", "cycle_number >= 0")

    history_uniques = _unique_names("task_history")
    history_fks = _foreign_key_names("task_history")
    history_fk_columns = _foreign_key_columns("task_history")
    history_checks = _check_names("task_history")
    with op.batch_alter_table("task_history") as batch:
        batch.alter_column("mode_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("cycle_number", existing_type=sa.Integer(), nullable=False, server_default="0")
        if "uq_task_history_task_phase" in history_uniques:
            batch.drop_constraint("uq_task_history_task_phase", type_="unique")
        if "uq_task_history_task_mode_cycle_phase" not in history_uniques:
            batch.create_unique_constraint(
                "uq_task_history_task_mode_cycle_phase", ["task_id", "mode_id", "cycle_number", "phase_id"]
            )
        if "fk_task_history_mode_id_workflow_modes" not in history_fks and "mode_id" not in history_fk_columns:
            batch.create_foreign_key(
                "fk_task_history_mode_id_workflow_modes", "workflow_modes", ["mode_id"], ["id"]
            )
        if "ck_task_history_cycle_number" not in history_checks:
            batch.create_check_constraint("ck_task_history_cycle_number", "cycle_number >= 0")

    run_fks = _foreign_key_names("supervisor_runs")
    run_fk_columns = _foreign_key_columns("supervisor_runs")
    run_checks = _check_names("supervisor_runs")
    with op.batch_alter_table("supervisor_runs") as batch:
        batch.alter_column("mode_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("cycle_number", existing_type=sa.Integer(), nullable=False, server_default="0")
        batch.alter_column("attempt_number", existing_type=sa.Integer(), nullable=False, server_default="1")
        if "fk_supervisor_runs_mode_id_workflow_modes" not in run_fks and "mode_id" not in run_fk_columns:
            batch.create_foreign_key(
                "fk_supervisor_runs_mode_id_workflow_modes", "workflow_modes", ["mode_id"], ["id"]
            )
        if "ck_supervisor_runs_cycle_number" not in run_checks:
            batch.create_check_constraint("ck_supervisor_runs_cycle_number", "cycle_number >= 0")
        if "ck_supervisor_runs_attempt_number" not in run_checks:
            batch.create_check_constraint("ck_supervisor_runs_attempt_number", "attempt_number >= 1")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"SET search_path TO {SCHEMA}")

    with op.batch_alter_table("supervisor_runs") as batch:
        batch.drop_column("attempt_number")
        batch.drop_column("cycle_number")
        batch.drop_column("mode_id")
    with op.batch_alter_table("task_history") as batch:
        batch.drop_constraint("uq_task_history_task_mode_cycle_phase", type_="unique")
        batch.create_unique_constraint("uq_task_history_task_phase", ["task_id", "phase_id"])
        batch.drop_column("cycle_number")
        batch.drop_column("mode_id")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("cycle_number")
        batch.drop_column("current_mode_id")
    with op.batch_alter_table("phases") as batch:
        batch.drop_constraint("uq_phases_mode_code", type_="unique")
        batch.create_unique_constraint("uq_phases_workflow_code", ["workflow_id", "code"])
        batch.drop_column("mode_id")
    op.drop_table("workflow_modes")
