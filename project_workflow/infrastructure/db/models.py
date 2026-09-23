"""SQLAlchemy ORM models for the project-workflow schema.

Uses SQLAlchemy 2 ``mapped_column`` style so mypy sees plain ``int``/``str``
types instead of ``Column[...]`` wrappers.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="", server_default=text("''"))
    hermes_profile: Mapped[str | None] = mapped_column(String(251), nullable=True)

    __table_args__ = (
        Index("uq_agents_name", "name", unique=True),
        Index("uq_agents_hermes_profile", "hermes_profile", unique=True),
    )

    phases: Mapped[list[Phase]] = relationship("Phase", back_populates="agent")


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="", server_default=text("''"))
    is_default: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    __table_args__ = (CheckConstraint("is_default IN (0, 1)", name="ck_workflows_is_default"),)

    phases: Mapped[list[Phase]] = relationship(
        "Phase", back_populates="workflow", cascade="all, delete-orphan", passive_deletes=True
    )
    modes: Mapped[list[WorkflowMode]] = relationship(
        "WorkflowMode", back_populates="workflow", cascade="all, delete-orphan", passive_deletes=True
    )
    projects: Mapped[list[Project]] = relationship("Project", back_populates="workflow", cascade="all, delete-orphan")
    tasks: Mapped[list[Task]] = relationship("Task", back_populates="workflow")


class WorkflowMode(Base):
    """A versioned execution catalog owned by a workflow.

    The adapter may select a mode, but this table remains project-workflow's
    source of truth for the catalog and its phase graph.
    """

    __tablename__ = "workflow_modes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    mode_order: Mapped[int] = mapped_column(nullable=False)
    role_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    execution_scope: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tech_workspace_policy: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        UniqueConstraint("id", "workflow_id", name="uq_workflow_modes_id_workflow"),
        UniqueConstraint("workflow_id", "key", name="uq_workflow_modes_workflow_key"),
        UniqueConstraint("workflow_id", "mode_order", name="uq_workflow_modes_workflow_order"),
        CheckConstraint("mode_order > 0", name="ck_workflow_modes_order_positive"),
        CheckConstraint(
            "execution_scope IS NULL OR execution_scope IN ('business', 'delivery', 'aggregate')",
            name="ck_workflow_modes_execution_scope",
        ),
        CheckConstraint(
            "tech_workspace_policy IS NULL OR tech_workspace_policy IN ('forbidden', 'required')",
            name="ck_workflow_modes_tech_policy",
        ),
        CheckConstraint(
            "(role_key IS NULL AND execution_scope IS NULL AND tech_workspace_policy IS NULL) OR "
            "(role_key IS NOT NULL AND execution_scope IS NOT NULL AND tech_workspace_policy IS NOT NULL)",
            name="ck_workflow_modes_policy_complete",
        ),
        CheckConstraint(
            "execution_scope IS NULL OR "
            "(execution_scope = 'business' AND tech_workspace_policy = 'forbidden') OR "
            "(execution_scope IN ('delivery', 'aggregate') AND tech_workspace_policy = 'required')",
            name="ck_workflow_modes_policy_consistent",
        ),
    )

    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="modes")
    phases: Mapped[list[Phase]] = relationship("Phase", back_populates="mode", overlaps="phases,workflow,mode")


class Phase(Base):
    __tablename__ = "phases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    mode_id: Mapped[int] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    phase_order: Mapped[int] = mapped_column(nullable=False)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), nullable=True)
    parallel_with_phase_id: Mapped[int | None] = mapped_column(nullable=True)
    rollback_target_phase_id: Mapped[int | None] = mapped_column(nullable=True)
    execution_type: Mapped[str] = mapped_column(
        String,
        default="sync",
        server_default="sync",
    )
    __table_args__ = (
        UniqueConstraint("id", "workflow_id", name="uq_phases_id_workflow"),
        UniqueConstraint("id", "mode_id", "workflow_id", name="uq_phases_id_mode_workflow"),
        UniqueConstraint("workflow_id", "mode_id", "code", name="uq_phases_workflow_mode_code"),
        UniqueConstraint("workflow_id", "mode_id", "phase_order", name="uq_phases_workflow_mode_order"),
        ForeignKeyConstraint(
            ["mode_id", "workflow_id"],
            ["workflow_modes.id", "workflow_modes.workflow_id"],
            name="fk_phases_mode_workflow",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["parallel_with_phase_id", "mode_id", "workflow_id"],
            ["phases.id", "phases.mode_id", "phases.workflow_id"],
            name="fk_phases_parallel_with_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["rollback_target_phase_id", "mode_id", "workflow_id"],
            ["phases.id", "phases.mode_id", "phases.workflow_id"],
            name="fk_phases_rollback_target_workflow",
            ondelete="RESTRICT",
        ),
        CheckConstraint("phase_order > 0", name="ck_phases_phase_order_positive"),
        CheckConstraint(
            "execution_type IN ('sync', 'parallel')",
            name="ck_phases_execution_type",
        ),
    )

    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="phases", overlaps="phases,mode")
    mode: Mapped[WorkflowMode] = relationship("WorkflowMode", back_populates="phases", overlaps="phases,workflow")
    agent: Mapped[Agent | None] = relationship("Agent", back_populates="phases")
    instructions: Mapped[list[PhaseInstruction]] = relationship(
        "PhaseInstruction", back_populates="phase", cascade="all, delete-orphan"
    )
    checks: Mapped[list[PhaseCheck]] = relationship(
        "PhaseCheck", back_populates="phase", cascade="all, delete-orphan"
    )
    evidence: Mapped[list[PhaseEvidenceRequirement]] = relationship(
        "PhaseEvidenceRequirement", back_populates="phase", cascade="all, delete-orphan"
    )


class PhaseInstruction(Base):
    __tablename__ = "phase_instructions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phase_id: Mapped[int] = mapped_column(
        ForeignKey("phases.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_num: Mapped[int] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    execution_type: Mapped[str] = mapped_column(
        String,
        default="sync",
        server_default="sync",
    )
    skills: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        UniqueConstraint("phase_id", "step_num", name="uq_phase_instructions_phase_step"),
        CheckConstraint("step_num > 0", name="ck_phase_instructions_step_num_positive"),
        CheckConstraint(
            "execution_type IN ('sync', 'parallel')",
            name="ck_phase_instructions_execution_type",
        ),
    )

    phase: Mapped[Phase] = relationship("Phase", back_populates="instructions")


class PhaseCheck(Base):
    __tablename__ = "phase_checks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phase_id: Mapped[int] = mapped_column(
        ForeignKey("phases.id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (UniqueConstraint("phase_id", "description", name="uq_phase_checks_description"),)

    phase: Mapped[Phase] = relationship("Phase", back_populates="checks")


class PhaseEvidenceRequirement(Base):
    __tablename__ = "phase_evidence_requirements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phase_id: Mapped[int] = mapped_column(
        ForeignKey("phases.id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        UniqueConstraint("phase_id", "description", name="uq_phase_evidence_requirements_description"),
    )

    phase: Mapped[Phase] = relationship("Phase", back_populates="evidence")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    theme_icon: Mapped[str] = mapped_column(String(32), nullable=False, default="folder", server_default="folder")
    theme_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#5E6AD2", server_default="#5E6AD2")
    cli_command: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_prefixes: Mapped[str] = mapped_column(String, nullable=False, default="[]", server_default="[]")

    __table_args__ = (
        UniqueConstraint("id", "workflow_id", name="uq_projects_id_workflow"),
    )

    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="projects")
    tasks: Mapped[list[Task]] = relationship(
        "Task",
        back_populates="project",
        foreign_keys="Task.project_id",
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(nullable=False)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="RESTRICT"), nullable=False)
    mode_id: Mapped[int] = mapped_column(nullable=False)
    cycle_number: Mapped[int] = mapped_column(nullable=False, server_default="0")
    assignment_operation_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assignment_revision: Mapped[int] = mapped_column(nullable=False, server_default="0")
    task_key: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_phase_id: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String,
        default="active",
        server_default="active",
    )
    created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "workflow_id"],
            ["projects.id", "projects.workflow_id"],
            name="fk_tasks_project_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["current_phase_id", "mode_id", "workflow_id"],
            ["phases.id", "phases.mode_id", "phases.workflow_id"],
            name="fk_tasks_current_phase_workflow",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "workflow_id", name="uq_tasks_id_workflow"),
        UniqueConstraint("id", "mode_id", "workflow_id", name="uq_tasks_id_mode_workflow"),
        UniqueConstraint("project_id", "task_key", name="uq_tasks_project_task_key"),
        UniqueConstraint(
            "project_id", "assignment_operation_key", name="uq_tasks_project_assignment_operation"
        ),
        CheckConstraint("status IN ('active', 'done', 'blocked')", name="ck_tasks_status"),
        CheckConstraint("cycle_number >= 0", name="ck_tasks_cycle_number_nonnegative"),
        CheckConstraint("assignment_revision >= 0", name="ck_tasks_assignment_revision_nonnegative"),
        Index("ix_tasks_project_id", "project_id"),
        Index("ix_tasks_workflow_id", "workflow_id"),
        Index("ix_tasks_current_phase_id", "current_phase_id"),
    )

    project: Mapped[Project] = relationship(
        "Project",
        back_populates="tasks",
        foreign_keys=[project_id],
    )
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="tasks")
    mode: Mapped[WorkflowMode] = relationship(
        "WorkflowMode",
        primaryjoin="and_(Task.mode_id == WorkflowMode.id, Task.workflow_id == WorkflowMode.workflow_id)",
        foreign_keys="[Task.mode_id, Task.workflow_id]",
        viewonly=True,
    )


class TaskRuntimeAssignment(Base):
    """Append-only acceptance ledger for adapter-owned runtime assignments."""

    __tablename__ = "task_runtime_assignments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    operation_key: Mapped[str] = mapped_column(String(128), nullable=False)
    task_id: Mapped[int] = mapped_column(nullable=False)
    project_id: Mapped[int] = mapped_column(nullable=False)
    workflow_id: Mapped[int] = mapped_column(nullable=False)
    mode_id: Mapped[int] = mapped_column(nullable=False)
    cycle_number: Mapped[int] = mapped_column(nullable=False)
    assignment_revision: Mapped[int] = mapped_column(nullable=False)
    role_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    execution_scope: Mapped[str | None] = mapped_column(String(16), nullable=True)
    business_task_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    root_task_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    work_item_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    task_workspace_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tech_execution_workspace_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tech_execution_attempt_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    decomposition_revision_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    stage_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assignment_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    binding_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    hermes_run_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    workspace_generation: Mapped[int | None] = mapped_column(nullable=True)
    lease_generation: Mapped[int | None] = mapped_column(nullable=True)
    exact_input_refs: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "workflow_id"],
            ["tasks.id", "tasks.workflow_id"],
            name="fk_task_runtime_assignments_task_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "workflow_id"],
            ["projects.id", "projects.workflow_id"],
            name="fk_task_runtime_assignments_project_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["mode_id", "workflow_id"],
            ["workflow_modes.id", "workflow_modes.workflow_id"],
            name="fk_task_runtime_assignments_mode_workflow",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("operation_key", name="uq_task_runtime_assignments_operation_key"),
        UniqueConstraint(
            "task_id", "assignment_revision", name="uq_task_runtime_assignments_task_revision"
        ),
        CheckConstraint("cycle_number >= 0", name="ck_task_runtime_assignments_cycle_nonnegative"),
        CheckConstraint("assignment_revision > 0", name="ck_task_runtime_assignments_revision_positive"),
        CheckConstraint(
            "execution_scope IS NULL OR execution_scope IN ('business', 'delivery', 'aggregate')",
            name="ck_task_runtime_assignments_execution_scope",
        ),
        CheckConstraint(
            "workspace_generation IS NULL OR workspace_generation >= 0",
            name="ck_task_runtime_assignments_workspace_generation",
        ),
        CheckConstraint(
            "lease_generation IS NULL OR lease_generation >= 0",
            name="ck_task_runtime_assignments_lease_generation",
        ),
        Index("ix_task_runtime_assignments_task_id", "task_id"),
        Index("ix_task_runtime_assignments_business_task_ref", "business_task_ref"),
        Index("ix_task_runtime_assignments_task_workspace_ref", "task_workspace_ref"),
    )
    mode: Mapped[WorkflowMode] = relationship(
        "WorkflowMode",
        primaryjoin=(
            "and_(TaskRuntimeAssignment.mode_id == WorkflowMode.id, "
            "TaskRuntimeAssignment.workflow_id == WorkflowMode.workflow_id)"
        ),
        foreign_keys="[TaskRuntimeAssignment.mode_id, TaskRuntimeAssignment.workflow_id]",
        viewonly=True,
    )


class TaskStepHistoryEntry(Base):
    __tablename__ = "task_step_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(nullable=False)
    workflow_id: Mapped[int] = mapped_column(nullable=False)
    mode_id: Mapped[int] = mapped_column(nullable=False)
    cycle_number: Mapped[int] = mapped_column(nullable=False, server_default="0")
    phase_id: Mapped[int] = mapped_column(nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    worker_report: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    covered_item_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    missing_item_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    blocker_messages: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    next_phase_id: Mapped[int | None] = mapped_column(nullable=True)
    rollback_phase_id: Mapped[int | None] = mapped_column(nullable=True)
    replay_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evaluation_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    supervisor_response: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "workflow_id"],
            ["tasks.id", "tasks.workflow_id"],
            name="fk_task_step_history_task_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["phase_id", "mode_id", "workflow_id"],
            ["phases.id", "phases.mode_id", "phases.workflow_id"],
            name="fk_task_step_history_phase_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["next_phase_id", "mode_id", "workflow_id"],
            ["phases.id", "phases.mode_id", "phases.workflow_id"],
            name="fk_task_step_history_next_phase_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["rollback_phase_id", "mode_id", "workflow_id"],
            ["phases.id", "phases.mode_id", "phases.workflow_id"],
            name="fk_task_step_history_rollback_phase_workflow",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "task_id", name="uq_task_step_history_id_task"),
        UniqueConstraint("id", "task_id", "mode_id", "cycle_number", name="uq_task_step_history_execution"),
        Index(
            "uq_task_step_history_replay",
            "task_id",
            "mode_id",
            "cycle_number",
            "phase_id",
            "replay_fingerprint",
            unique=True,
        ),
        Index("ix_task_step_history_phase_id", "phase_id"),
        Index("ix_task_step_history_next_phase_id", "next_phase_id"),
        Index("ix_task_step_history_rollback_phase_id", "rollback_phase_id"),
        CheckConstraint(
            "verdict IN ('pass', 'partial', 'blocked', 'rollback', 'delegate')",
            name="ck_task_step_history_verdict",
        ),
        CheckConstraint("cycle_number >= 0", name="ck_task_step_history_cycle_nonnegative"),
    )
    mode: Mapped[WorkflowMode] = relationship(
        "WorkflowMode",
        primaryjoin=(
            "and_(TaskStepHistoryEntry.mode_id == WorkflowMode.id, "
            "TaskStepHistoryEntry.workflow_id == WorkflowMode.workflow_id)"
        ),
        foreign_keys="[TaskStepHistoryEntry.mode_id, TaskStepHistoryEntry.workflow_id]",
        viewonly=True,
    )


class TaskPhaseEvent(Base):
    __tablename__ = "task_phase_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(nullable=False)
    workflow_id: Mapped[int] = mapped_column(nullable=False)
    mode_id: Mapped[int] = mapped_column(nullable=False)
    cycle_number: Mapped[int] = mapped_column(nullable=False, server_default="0")
    phase_id: Mapped[int] = mapped_column(nullable=False)
    step_history_id: Mapped[int | None] = mapped_column(nullable=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "workflow_id"],
            ["tasks.id", "tasks.workflow_id"],
            name="fk_task_phase_events_task_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["phase_id", "mode_id", "workflow_id"],
            ["phases.id", "phases.mode_id", "phases.workflow_id"],
            name="fk_task_phase_events_phase_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["step_history_id", "task_id", "mode_id", "cycle_number"],
            [
                "task_step_history.id",
                "task_step_history.task_id",
                "task_step_history.mode_id",
                "task_step_history.cycle_number",
            ],
            name="fk_task_phase_events_step_task_execution",
            ondelete="RESTRICT",
        ),
        Index("ix_task_phase_events_task_id_id", "task_id", "id"),
        Index("ix_task_phase_events_phase_id", "phase_id"),
        Index("ix_task_phase_events_step_history_id", "step_history_id"),
        CheckConstraint(
            "event_type IN ('entered', 'completed', 'blocked', 'resumed', 'rolled_back')",
            name="ck_task_phase_events_event_type",
        ),
        CheckConstraint("cycle_number >= 0", name="ck_task_phase_events_cycle_nonnegative"),
    )
    mode: Mapped[WorkflowMode] = relationship(
        "WorkflowMode",
        primaryjoin=(
            "and_(TaskPhaseEvent.mode_id == WorkflowMode.id, "
            "TaskPhaseEvent.workflow_id == WorkflowMode.workflow_id)"
        ),
        foreign_keys="[TaskPhaseEvent.mode_id, TaskPhaseEvent.workflow_id]",
        viewonly=True,
    )


# Runtime helper used by repository layer to extract a plain dict from a model.
def model_to_dict(model: Base) -> dict[str, Any]:
    return {c.name: getattr(model, c.name) for c in model.__table__.columns}
