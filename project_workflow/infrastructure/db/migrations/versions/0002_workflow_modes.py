"""Add workflow-owned execution modes and cycle-aware task history.

The migration deliberately creates one neutral ``default`` catalog per
workflow before backfilling all technical cursors and append-only records. No
seed/catalog content is introduced here.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_workflow_modes"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    if _is_sqlite():
        # SQLite needs this disabled while Alembic rebuilds the referenced
        # phases table; it is restored after all dependent tables are rebuilt.
        op.execute("PRAGMA foreign_keys=OFF")
    op.create_table(
        "workflow_modes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("mode_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("mode_order > 0", name="ck_workflow_modes_order_positive"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workflow_id", name="uq_workflow_modes_id_workflow"),
        sa.UniqueConstraint("workflow_id", "key", name="uq_workflow_modes_workflow_key"),
        sa.UniqueConstraint("workflow_id", "mode_order", name="uq_workflow_modes_workflow_order"),
    )

    for table in ("phases", "tasks", "task_step_history", "task_phase_events"):
        op.add_column(table, sa.Column("mode_id", sa.Integer(), nullable=True))
    for table in ("tasks", "task_step_history", "task_phase_events"):
        op.add_column(table, sa.Column("cycle_number", sa.Integer(), server_default="0", nullable=True))

    # SQLite and PostgreSQL both support this INSERT ... SELECT form.
    op.execute(
        sa.text(
            "INSERT INTO workflow_modes (workflow_id, key, name, mode_order) "
            "SELECT id, 'default', 'Default', 1 FROM workflows"
        )
    )
    op.execute(
        sa.text(
            "UPDATE phases SET mode_id = "
            "(SELECT wm.id FROM workflow_modes wm WHERE wm.workflow_id = phases.workflow_id AND wm.key = 'default')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE tasks SET mode_id = "
            "(SELECT p.mode_id FROM phases p WHERE p.id = tasks.current_phase_id "
            "AND p.workflow_id = tasks.workflow_id), "
            "cycle_number = 0"
        )
    )
    op.execute(
        sa.text(
            "UPDATE task_step_history SET mode_id = "
            "(SELECT p.mode_id FROM phases p WHERE p.id = task_step_history.phase_id "
            "AND p.workflow_id = task_step_history.workflow_id), "
            "cycle_number = 0"
        )
    )
    op.execute(
        sa.text(
            "UPDATE task_phase_events SET mode_id = "
            "(SELECT p.mode_id FROM phases p WHERE p.id = task_phase_events.phase_id "
            "AND p.workflow_id = task_phase_events.workflow_id), "
            "cycle_number = 0"
        )
    )

    # Every legacy row has a phase, so the backfill must be complete. Raising
    # here prevents a partially constrained database from being accepted.
    for table in ("phases", "tasks", "task_step_history", "task_phase_events"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} WHERE mode_id IS NULL LIMIT 1")).first():
            raise RuntimeError(f"Не удалось определить default mode для таблицы {table}")

    # SQLite cannot rewrite a referenced parent table while foreign-key
    # enforcement is enabled (the legacy tasks table still points at phases).
    # Its backfill remains fully data-safe; new SQLite schemas are created from
    # ORM metadata and therefore receive the complete composite constraints.
    # Replace workflow-scoped phase graph FKs with mode-scoped ones.
    with op.batch_alter_table("phases", recreate="always") as batch:
        batch.drop_constraint("fk_phases_parallel_with_workflow", type_="foreignkey")
        batch.drop_constraint("fk_phases_rollback_target_workflow", type_="foreignkey")
        batch.drop_constraint("uq_phases_workflow_code", type_="unique")
        batch.drop_constraint("uq_phases_workflow_order", type_="unique")
        batch.alter_column("mode_id", nullable=False)
        batch.create_unique_constraint("uq_phases_id_mode_workflow", ["id", "mode_id", "workflow_id"])
        batch.create_unique_constraint("uq_phases_workflow_mode_code", ["workflow_id", "mode_id", "code"])
        batch.create_unique_constraint("uq_phases_workflow_mode_order", ["workflow_id", "mode_id", "phase_order"])
        batch.create_foreign_key(
            "fk_phases_mode_workflow",
            "workflow_modes",
            ["mode_id", "workflow_id"],
            ["id", "workflow_id"],
            ondelete="CASCADE",
        )
        if not _is_sqlite():
            batch.create_foreign_key(
                "fk_phases_parallel_with_mode_workflow",
                "phases",
                ["parallel_with_phase_id", "mode_id", "workflow_id"],
                ["id", "mode_id", "workflow_id"],
                ondelete="RESTRICT",
            )
            batch.create_foreign_key(
                "fk_phases_rollback_target_mode_workflow",
                "phases",
                ["rollback_target_phase_id", "mode_id", "workflow_id"],
                ["id", "mode_id", "workflow_id"],
                ondelete="RESTRICT",
            )

    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.drop_constraint("fk_tasks_current_phase_workflow", type_="foreignkey")
        batch.alter_column("mode_id", nullable=False)
        batch.alter_column("cycle_number", nullable=False, server_default="0")
        batch.create_check_constraint("ck_tasks_cycle_number_nonnegative", "cycle_number >= 0")
        batch.create_unique_constraint("uq_tasks_id_mode_workflow", ["id", "mode_id", "workflow_id"])
        batch.create_foreign_key(
            "fk_tasks_current_phase_mode_workflow",
            "phases",
            ["current_phase_id", "mode_id", "workflow_id"],
            ["id", "mode_id", "workflow_id"],
            ondelete="RESTRICT",
        )

    with op.batch_alter_table("task_step_history", recreate="always") as batch:
        for name in (
            "fk_task_step_history_phase_workflow",
            "fk_task_step_history_next_phase_workflow",
            "fk_task_step_history_rollback_phase_workflow",
        ):
            batch.drop_constraint(name, type_="foreignkey")
        batch.drop_index("uq_task_step_history_replay")
        batch.alter_column("mode_id", nullable=False)
        batch.alter_column("cycle_number", nullable=False, server_default="0")
        batch.create_check_constraint("ck_task_step_history_cycle_nonnegative", "cycle_number >= 0")
        batch.create_unique_constraint("uq_task_step_history_execution", ["id", "task_id", "mode_id", "cycle_number"])
        for name, local in (
            ("phase", "phase_id"),
            ("next_phase", "next_phase_id"),
            ("rollback_phase", "rollback_phase_id"),
        ):
            batch.create_foreign_key(
                f"fk_task_step_history_{name}_mode_workflow",
                "phases",
                [local, "mode_id", "workflow_id"],
                ["id", "mode_id", "workflow_id"],
                ondelete="RESTRICT",
            )
        batch.create_index(
            "uq_task_step_history_replay",
            ["task_id", "mode_id", "cycle_number", "phase_id", "replay_fingerprint"],
            unique=True,
        )

    with op.batch_alter_table("task_phase_events", recreate="always") as batch:
        batch.drop_constraint("fk_task_phase_events_phase_workflow", type_="foreignkey")
        batch.alter_column("mode_id", nullable=False)
        batch.alter_column("cycle_number", nullable=False, server_default="0")
        batch.create_check_constraint("ck_task_phase_events_cycle_nonnegative", "cycle_number >= 0")
        batch.create_foreign_key(
            "fk_task_phase_events_phase_mode_workflow",
            "phases",
            ["phase_id", "mode_id", "workflow_id"],
            ["id", "mode_id", "workflow_id"],
            ondelete="RESTRICT",
        )
    if _is_sqlite():
        # SQLite cannot retain these self-referential composite FKs during the
        # legacy table rebuild. Triggers provide the same cross-mode guard for
        # direct SQL writes; repository validation covers the normal API path.
        for name, column in (
            ("phases_parallel_mode_guard", "parallel_with_phase_id"),
            ("phases_rollback_mode_guard", "rollback_target_phase_id"),
        ):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER {name} BEFORE INSERT ON phases "
                    f"WHEN NEW.{column} IS NOT NULL AND NOT EXISTS ("
                    f"SELECT 1 FROM phases WHERE id = NEW.{column} "
                    "AND mode_id = NEW.mode_id AND workflow_id = NEW.workflow_id) "
                    "BEGIN SELECT RAISE(ABORT, 'phase reference must stay within mode'); END"
                )
            )
            op.execute(
                sa.text(
                    f"CREATE TRIGGER {name}_update BEFORE UPDATE OF {column}, mode_id, workflow_id ON phases "
                    f"WHEN NEW.{column} IS NOT NULL AND NOT EXISTS ("
                    f"SELECT 1 FROM phases WHERE id = NEW.{column} "
                    "AND mode_id = NEW.mode_id AND workflow_id = NEW.workflow_id) "
                    "BEGIN SELECT RAISE(ABORT, 'phase reference must stay within mode'); END"
                )
            )
        op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    raise NotImplementedError("workflow mode history is irreversible once deployed")
