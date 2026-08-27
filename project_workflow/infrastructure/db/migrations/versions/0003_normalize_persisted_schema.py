"""Normalize the deployed schema without losing tasks or audit history.

Revision ID: 0003_normalized
Revises: 0002_sdlc_v2
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_normalized"
down_revision: str | Sequence[str] | None = "0002_sdlc_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _scalar(sql: str) -> int:
    return int(op.get_bind().execute(sa.text(sql)).scalar_one())


def _require_zero(sql: str, message: str) -> None:
    if _scalar(sql):
        raise RuntimeError(message)


def _rename_constraint(table: str, old: str, new: str) -> None:
    op.execute(sa.text(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old}" TO "{new}"'))


def _reset_sequence(table: str) -> None:
    op.execute(
        sa.text(
            "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
            f"COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {table}"
        ).bindparams(table_name=table)
    )


def _validate_deployed_data() -> None:
    _require_zero(
        "SELECT COUNT(*) FROM ("
        "SELECT workflow_id, phase_order FROM phases "
        "GROUP BY workflow_id, phase_order HAVING COUNT(*) > 1"
        ") duplicate_orders",
        "Нельзя нормализовать каталог: порядок фаз внутри workflow не уникален",
    )
    _require_zero(
        "SELECT COUNT(*) FROM phases p "
        "WHERE NULLIF(BTRIM(p.parallel_with), '') IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM phases target "
        "WHERE target.workflow_id = p.workflow_id AND target.code = p.parallel_with)",
        "Нельзя нормализовать каталог: parallel_with ссылается на неизвестную фазу",
    )
    _require_zero(
        "SELECT COUNT(*) FROM phases p "
        "WHERE NULLIF(BTRIM(p.rollback_target), '') IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM phases target "
        "WHERE target.workflow_id = p.workflow_id AND target.code = p.rollback_target)",
        "Нельзя нормализовать каталог: rollback_target ссылается на неизвестную фазу",
    )
    _require_zero(
        "SELECT COUNT(*) FROM tasks t "
        "WHERE NOT EXISTS (SELECT 1 FROM phases p "
        "WHERE p.workflow_id = t.workflow_id AND p.code = t.current_phase)",
        "Нельзя нормализовать задачи: current_phase отсутствует в закреплённом workflow",
    )
    _require_zero(
        "SELECT COUNT(*) FROM supervisor_runs r "
        "JOIN tasks t ON t.id = r.task_id "
        "JOIN phases p ON p.id = r.phase_id "
        "WHERE p.workflow_id <> t.workflow_id",
        "Нельзя нормализовать audit: evaluator run ссылается на чужой workflow",
    )
    _require_zero(
        "SELECT COUNT(*) FROM supervisor_runs r "
        "JOIN tasks t ON t.id = r.task_id "
        "JOIN phases p ON p.id IN (r.next_phase_id, r.rollback_phase_id) "
        "WHERE p.workflow_id <> t.workflow_id",
        "Нельзя нормализовать audit: переход evaluator ссылается на чужой workflow",
    )
    _require_zero(
        "SELECT COUNT(*) FROM task_history h "
        "JOIN tasks t ON t.id = h.task_id "
        "JOIN phases p ON p.id = h.phase_id "
        "WHERE p.workflow_id <> t.workflow_id",
        "Нельзя нормализовать историю фаз: запись ссылается на чужой workflow",
    )


def _normalize_phase_and_task_references() -> None:
    op.add_column("phases", sa.Column("parallel_with_phase_id", sa.Integer(), nullable=True))
    op.add_column("phases", sa.Column("rollback_target_phase_id", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE phases source SET parallel_with_phase_id = target.id "
            "FROM phases target WHERE target.workflow_id = source.workflow_id "
            "AND target.code = source.parallel_with "
            "AND NULLIF(BTRIM(source.parallel_with), '') IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE phases source SET rollback_target_phase_id = target.id "
            "FROM phases target WHERE target.workflow_id = source.workflow_id "
            "AND target.code = source.rollback_target "
            "AND NULLIF(BTRIM(source.rollback_target), '') IS NOT NULL"
        )
    )
    op.create_unique_constraint("uq_phases_id_workflow", "phases", ["id", "workflow_id"])
    op.create_unique_constraint(
        "uq_phases_workflow_order", "phases", ["workflow_id", "phase_order"]
    )

    op.add_column("tasks", sa.Column("current_phase_id", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE tasks task SET current_phase_id = phase.id "
            "FROM phases phase WHERE phase.workflow_id = task.workflow_id "
            "AND phase.code = task.current_phase"
        )
    )
    op.alter_column("tasks", "current_phase_id", nullable=False)
    op.create_unique_constraint("uq_tasks_id_workflow", "tasks", ["id", "workflow_id"])
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])
    op.create_index("ix_tasks_workflow_id", "tasks", ["workflow_id"])
    op.create_index("ix_tasks_current_phase_id", "tasks", ["current_phase_id"])


def _rename_phase_contract_tables() -> None:
    op.rename_table("instructions", "phase_instructions")
    _rename_constraint(
        "phase_instructions", "uq_instructions_phase_step", "uq_phase_instructions_phase_step"
    )
    _rename_constraint(
        "phase_instructions",
        "ck_instructions_step_num_positive",
        "ck_phase_instructions_step_num_positive",
    )
    _rename_constraint(
        "phase_instructions",
        "ck_instructions_execution_type",
        "ck_phase_instructions_execution_type",
    )

    op.rename_table("checks", "phase_checks")
    _rename_constraint("phase_checks", "uq_checks_phase_description", "uq_phase_checks_description")

    op.rename_table("evidence", "phase_evidence_requirements")
    _rename_constraint(
        "phase_evidence_requirements",
        "uq_evidence_phase_description",
        "uq_phase_evidence_requirements_description",
    )


def _normalize_step_history() -> None:
    op.rename_table("supervisor_runs", "task_step_history")
    op.alter_column("task_step_history", "report", new_column_name="worker_report")
    op.alter_column("task_step_history", "covered", new_column_name="covered_item_ids")
    op.alter_column("task_step_history", "missing", new_column_name="missing_item_ids")
    op.alter_column("task_step_history", "blockers", new_column_name="blocker_messages")
    op.alter_column(
        "task_step_history", "report_fingerprint", new_column_name="replay_fingerprint"
    )
    op.alter_column(
        "task_step_history", "context_snapshot", new_column_name="evaluation_snapshot"
    )
    op.alter_column("task_step_history", "response", new_column_name="supervisor_response")
    op.add_column("task_step_history", sa.Column("workflow_id", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE task_step_history history SET workflow_id = task.workflow_id "
            "FROM tasks task WHERE task.id = history.task_id"
        )
    )
    op.execute(sa.text("UPDATE task_step_history SET created_at = NOW() WHERE created_at IS NULL"))
    op.alter_column("task_step_history", "workflow_id", nullable=False)
    op.alter_column("task_step_history", "created_at", nullable=False)

    for constraint in (
        "supervisor_runs_task_id_fkey",
        "supervisor_runs_phase_id_fkey",
        "supervisor_runs_next_phase_id_fkey",
        "supervisor_runs_rollback_phase_id_fkey",
    ):
        op.drop_constraint(constraint, "task_step_history", type_="foreignkey")
    _rename_constraint(
        "task_step_history", "ck_supervisor_runs_verdict", "ck_task_step_history_verdict"
    )
    op.execute(
        sa.text(
            "ALTER INDEX uq_supervisor_runs_task_phase_report_fingerprint "
            "RENAME TO uq_task_step_history_replay"
        )
    )
    op.create_unique_constraint(
        "uq_task_step_history_id_task", "task_step_history", ["id", "task_id"]
    )
    op.create_foreign_key(
        "fk_task_step_history_task_workflow",
        "task_step_history",
        "tasks",
        ["task_id", "workflow_id"],
        ["id", "workflow_id"],
        ondelete="RESTRICT",
    )
    for field, name in (
        ("phase_id", "fk_task_step_history_phase_workflow"),
        ("next_phase_id", "fk_task_step_history_next_phase_workflow"),
        ("rollback_phase_id", "fk_task_step_history_rollback_phase_workflow"),
    ):
        op.create_foreign_key(
            name,
            "task_step_history",
            "phases",
            [field, "workflow_id"],
            ["id", "workflow_id"],
            ondelete="RESTRICT",
        )
    op.create_index("ix_task_step_history_phase_id", "task_step_history", ["phase_id"])
    op.create_index("ix_task_step_history_next_phase_id", "task_step_history", ["next_phase_id"])
    op.create_index(
        "ix_task_step_history_rollback_phase_id", "task_step_history", ["rollback_phase_id"]
    )


def _normalize_phase_events() -> None:
    op.rename_table("task_history", "task_phase_events")
    op.drop_constraint("uq_task_history_task_phase", "task_phase_events", type_="unique")
    op.drop_constraint("ck_task_history_status", "task_phase_events", type_="check")
    op.drop_constraint("task_history_task_id_fkey", "task_phase_events", type_="foreignkey")
    op.drop_constraint("task_history_phase_id_fkey", "task_phase_events", type_="foreignkey")
    op.alter_column("task_phase_events", "status", new_column_name="event_type")
    op.alter_column("task_phase_events", "completed_at", new_column_name="occurred_at")
    op.add_column("task_phase_events", sa.Column("workflow_id", sa.Integer(), nullable=True))
    op.add_column("task_phase_events", sa.Column("step_history_id", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE task_phase_events event SET workflow_id = task.workflow_id, "
            "occurred_at = COALESCE(event.occurred_at, task.updated_at, task.created_at, NOW()), "
            "event_type = CASE event.event_type "
            "WHEN 'done' THEN 'completed' WHEN 'blocked' THEN 'blocked' "
            "WHEN 'rollback' THEN 'rolled_back' ELSE 'entered' END "
            "FROM tasks task WHERE task.id = event.task_id"
        )
    )
    op.execute(
        sa.text(
            "UPDATE task_phase_events event SET step_history_id = history.id "
            "FROM task_step_history history WHERE history.id = ("
            "SELECT MAX(candidate.id) FROM task_step_history candidate "
            "WHERE candidate.task_id = event.task_id AND candidate.phase_id = event.phase_id)"
        )
    )
    op.alter_column("task_phase_events", "event_type", server_default=None)
    op.alter_column("task_phase_events", "workflow_id", nullable=False)
    op.alter_column(
        "task_phase_events", "occurred_at", nullable=False, server_default=sa.text("now()")
    )
    op.create_check_constraint(
        "ck_task_phase_events_event_type",
        "task_phase_events",
        "event_type IN ('entered', 'completed', 'blocked', 'resumed', 'rolled_back')",
    )
    op.create_foreign_key(
        "fk_task_phase_events_task_workflow",
        "task_phase_events",
        "tasks",
        ["task_id", "workflow_id"],
        ["id", "workflow_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_task_phase_events_phase_workflow",
        "task_phase_events",
        "phases",
        ["phase_id", "workflow_id"],
        ["id", "workflow_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_task_phase_events_step_task",
        "task_phase_events",
        "task_step_history",
        ["step_history_id", "task_id"],
        ["id", "task_id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_task_phase_events_task_id_id", "task_phase_events", ["task_id", "id"])
    op.create_index("ix_task_phase_events_phase_id", "task_phase_events", ["phase_id"])
    op.create_index(
        "ix_task_phase_events_step_history_id", "task_phase_events", ["step_history_id"]
    )
    op.execute(
        sa.text(
            "INSERT INTO task_phase_events "
            "(task_id, workflow_id, phase_id, step_history_id, event_type, occurred_at) "
            "SELECT task.id, task.workflow_id, task.current_phase_id, NULL, 'entered', "
            "COALESCE(task.created_at, NOW()) FROM tasks task "
            "WHERE NOT EXISTS (SELECT 1 FROM task_phase_events event "
            "WHERE event.task_id = task.id AND event.phase_id = task.current_phase_id)"
        )
    )


def _drop_legacy_columns() -> None:
    op.drop_constraint("phases_agent_id_fkey", "phases", type_="foreignkey")
    op.create_foreign_key(
        None, "phases", "agents", ["agent_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_foreign_key(
        "fk_phases_parallel_with_workflow",
        "phases",
        "phases",
        ["parallel_with_phase_id", "workflow_id"],
        ["id", "workflow_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_phases_rollback_target_workflow",
        "phases",
        "phases",
        ["rollback_target_phase_id", "workflow_id"],
        ["id", "workflow_id"],
        ondelete="RESTRICT",
    )
    for constraint in (
        "ck_phases_is_seed_managed",
        "ck_phases_is_blocker",
        "ck_phases_is_delegated",
        "ck_phases_is_critic",
    ):
        op.drop_constraint(constraint, "phases", type_="check")
    for column in (
        "min_time_min",
        "next_recommendation",
        "parallel_with",
        "rollback_target",
        "is_seed_managed",
        "is_blocker",
        "is_delegated",
        "is_critic",
    ):
        op.drop_column("phases", column)

    op.create_foreign_key(
        "fk_tasks_current_phase_workflow",
        "tasks",
        "phases",
        ["current_phase_id", "workflow_id"],
        ["id", "workflow_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_tasks_current_phase_nonblank", "tasks", type_="check")
    op.drop_column("tasks", "current_phase")

    op.drop_constraint("ck_workflows_catalog_sha256", "workflows", type_="check")
    op.drop_constraint("ck_workflows_is_locked", "workflows", type_="check")
    op.drop_column("workflows", "catalog_sha256")
    op.drop_column("workflows", "is_locked")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Обновление сохранённой схемы поддерживается только для PostgreSQL")
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    required = {"instructions", "checks", "evidence", "task_history", "supervisor_runs"}
    if not required.issubset(tables):
        raise RuntimeError("Схема 0002 не соответствует ожидаемой развёрнутой форме")

    _validate_deployed_data()
    _normalize_phase_and_task_references()
    _rename_phase_contract_tables()
    _normalize_step_history()
    _normalize_phase_events()
    _drop_legacy_columns()
    for table in (
        "phase_instructions",
        "phase_checks",
        "phase_evidence_requirements",
        "task_step_history",
        "task_phase_events",
    ):
        _reset_sequence(table)


def downgrade() -> None:
    raise RuntimeError(
        "Lossless downgrade после нормализации audit не поддерживается; используйте backup PostgreSQL"
    )
