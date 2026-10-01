"""SQLAlchemy ORM models for the project-workflow schema.

Uses SQLAlchemy 2 ``mapped_column`` style so mypy sees plain ``int``/``str``
types instead of ``Column[...]`` wrappers.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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


class PMExecution(Base):
    __tablename__ = "pm_executions"

    execution_ref: Mapped[str] = mapped_column(String(512), primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="RESTRICT"), unique=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("task_runtime_assignments.id", ondelete="RESTRICT"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"))
    tracker_instance_ref: Mapped[str] = mapped_column(String(512))
    tracker_project_ref: Mapped[str] = mapped_column(String(512))
    task_ref: Mapped[str] = mapped_column(String(512))
    root_ref: Mapped[str] = mapped_column(String(512))
    agent_ref: Mapped[str] = mapped_column(String(512))
    identity_json: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(BigInteger)
    fence: Mapped[int] = mapped_column(BigInteger)
    session_run_id: Mapped[str] = mapped_column(String(36))
    phase_id: Mapped[int] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"))
    checkpoint_json: Mapped[str | None] = mapped_column(Text)
    resume_operation_key: Mapped[str | None] = mapped_column(String(128))
    resume_session_run_id: Mapped[str | None] = mapped_column(String(36), unique=True)

    __table_args__ = (
        UniqueConstraint("tracker_instance_ref", "task_ref", "agent_ref", name="uq_pm_task_agent"),
        CheckConstraint("state IN ('active', 'waiting', 'resume_pending')", name="ck_pm_state"),
        CheckConstraint("version > 0 AND fence > 0", name="ck_pm_versions"),
        CheckConstraint("state = 'active' OR checkpoint_json IS NOT NULL", name="ck_pm_checkpoint"),
        CheckConstraint(
            "state != 'resume_pending' OR (resume_operation_key IS NOT NULL AND resume_session_run_id IS NOT NULL)",
            name="ck_pm_resume",
        ),
    )


class PMRun(Base):
    __tablename__ = "pm_runs"

    session_run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_ref: Mapped[str] = mapped_column(String(512))
    execution_ref: Mapped[str] = mapped_column(ForeignKey("pm_executions.execution_ref", ondelete="RESTRICT"))
    binding_ref: Mapped[str] = mapped_column(String(512))
    fence: Mapped[int] = mapped_column(BigInteger)
    observation_json: Mapped[str] = mapped_column(Text)
    terminal_json: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("execution_ref", "fence", name="uq_pm_run_fence"),
        CheckConstraint("fence > 0", name="ck_pm_run_fence"),
    )


class PMOperation(Base):
    __tablename__ = "pm_operations"

    operation_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    execution_ref: Mapped[str] = mapped_column(ForeignKey("pm_executions.execution_ref", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(32))
    request_sha256: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("kind IN ('bind', 'checkpoint', 'resume', 'rebind')", name="ck_pm_operation_kind"),
        CheckConstraint("length(request_sha256) = 64", name="ck_pm_operation_hash"),
    )


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
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="", server_default=text("''"))
    is_default: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    __table_args__ = (
        UniqueConstraint("key", name="uq_workflows_key"),
        CheckConstraint("is_default IN (0, 1)", name="ck_workflows_is_default"),
    )

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
    role_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
            "role_key IS NULL OR length(role_key) BETWEEN 2 AND 32",
            name="ck_workflow_modes_role_key_length",
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
        UniqueConstraint("id", "project_id", "workflow_id", name="uq_tasks_id_project_workflow"),
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
    workflow_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mode_id: Mapped[int] = mapped_column(nullable=False)
    cycle_number: Mapped[int] = mapped_column(nullable=False)
    attempt_number: Mapped[int | None] = mapped_column(nullable=True)
    assignment_revision: Mapped[int] = mapped_column(nullable=False)
    role_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    execution_scope: Mapped[str | None] = mapped_column(String(16), nullable=True)
    stage_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    business_task_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    root_task_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    work_item_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    work_item_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    queue_item_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    task_workspace_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    workspace_revision: Mapped[int | None] = mapped_column(nullable=True)
    tech_execution_workspace_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tech_execution_attempt_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    decomposition_revision_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    stage_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assignment_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    binding_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    hermes_run_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    bind_operation_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bind_request_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    concrete_agent_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    workspace_generation: Mapped[int | None] = mapped_column(nullable=True)
    lease_generation: Mapped[int | None] = mapped_column(nullable=True)
    exact_input_refs: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
            ["task_id", "project_id", "workflow_id"],
            ["tasks.id", "tasks.project_id", "tasks.workflow_id"],
            name="fk_task_runtime_assignments_task_project_workflow",
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
            "bind_operation_key", name="uq_task_runtime_assignments_bind_operation_key"
        ),
        UniqueConstraint(
            "task_id", "assignment_revision", name="uq_task_runtime_assignments_task_revision"
        ),
        CheckConstraint("cycle_number >= 0", name="ck_task_runtime_assignments_cycle_nonnegative"),
        CheckConstraint(
            "attempt_number IS NULL OR attempt_number > 0",
            name="ck_task_runtime_assignments_attempt_positive",
        ),
        CheckConstraint(
            "work_item_revision IS NULL OR work_item_revision >= 0",
            name="ck_task_runtime_assignments_work_item_revision",
        ),
        CheckConstraint(
            "workspace_revision IS NULL OR workspace_revision > 0",
            name="ck_task_runtime_assignments_workspace_revision",
        ),
        CheckConstraint("assignment_revision > 0", name="ck_task_runtime_assignments_revision_positive"),
        CheckConstraint(
            "execution_scope IS NULL OR execution_scope IN ('business', 'delivery', 'aggregate')",
            name="ck_task_runtime_assignments_execution_scope",
        ),
        CheckConstraint(
            "role_key IS NULL OR length(role_key) BETWEEN 2 AND 32",
            name="ck_task_runtime_assignments_role_key_length",
        ),
        CheckConstraint(
            "workspace_generation IS NULL OR workspace_generation >= 0",
            name="ck_task_runtime_assignments_workspace_generation",
        ),
        CheckConstraint(
            "lease_generation IS NULL OR lease_generation >= 0",
            name="ck_task_runtime_assignments_lease_generation",
        ),
        CheckConstraint(
            "(workflow_key IS NULL AND role_key IS NULL AND execution_scope IS NULL AND stage_key IS NULL AND "
            "attempt_number IS NULL AND business_task_ref IS NULL AND root_task_ref IS NULL AND "
            "work_item_ref IS NULL AND work_item_revision IS NULL AND queue_item_ref IS NULL AND "
            "task_workspace_ref IS NULL AND workspace_revision IS NULL AND "
            "tech_execution_workspace_ref IS NULL AND tech_execution_attempt_ref IS NULL AND "
            "decomposition_revision_ref IS NULL AND stage_revision IS NULL AND assignment_ref IS NULL AND "
            "binding_ref IS NULL AND hermes_run_ref IS NULL AND bind_operation_key IS NULL AND "
            "bind_request_sha256 IS NULL AND workspace_generation IS NULL AND "
            "lease_generation IS NULL AND exact_input_refs IS NULL AND payload_sha256 IS NULL) OR "
            "(workflow_key IS NOT NULL AND role_key IS NOT NULL AND execution_scope IS NOT NULL AND "
            "stage_key IS NOT NULL AND attempt_number IS NOT NULL AND business_task_ref IS NOT NULL AND "
            "root_task_ref IS NOT NULL AND work_item_ref IS NOT NULL AND work_item_revision IS NOT NULL AND "
            "queue_item_ref IS NOT NULL AND task_workspace_ref IS NOT NULL AND workspace_revision IS NOT NULL AND "
            "decomposition_revision_ref IS NOT NULL AND stage_revision IS NOT NULL AND assignment_ref IS NOT NULL AND "
            "workspace_generation IS NOT NULL AND lease_generation IS NOT NULL AND "
            "exact_input_refs IS NOT NULL AND payload_sha256 IS NOT NULL AND "
            "((binding_ref IS NULL AND hermes_run_ref IS NULL AND bind_operation_key IS NULL AND "
            "bind_request_sha256 IS NULL) OR (binding_ref IS NOT NULL AND hermes_run_ref IS NOT NULL AND "
            "((bind_operation_key IS NULL AND bind_request_sha256 IS NULL) OR "
            "(bind_operation_key IS NOT NULL AND bind_request_sha256 IS NOT NULL)))))",
            name="ck_task_runtime_assignments_binding_complete",
        ),
        CheckConstraint(
            "execution_scope IS NULL OR "
            "(execution_scope = 'business' AND tech_execution_workspace_ref IS NULL AND "
            "tech_execution_attempt_ref IS NULL) OR "
            "(execution_scope IN ('delivery', 'aggregate') AND tech_execution_workspace_ref IS NOT NULL AND "
            "tech_execution_attempt_ref IS NOT NULL)",
            name="ck_task_runtime_assignments_scope_tech_refs",
        ),
        CheckConstraint(
            "payload_sha256 IS NULL OR length(payload_sha256) = 64",
            name="ck_task_runtime_assignments_payload_sha256",
        ),
        CheckConstraint(
            "bind_request_sha256 IS NULL OR length(bind_request_sha256) = 64",
            name="ck_task_runtime_assignments_bind_request_sha256",
        ),
        CheckConstraint(
            "concrete_agent_ref IS NULL OR (length(concrete_agent_ref) = 36 AND "
            "concrete_agent_ref = lower(concrete_agent_ref) AND binding_ref IS NOT NULL AND "
            "hermes_run_ref IS NOT NULL AND bind_operation_key IS NOT NULL AND bind_request_sha256 IS NOT NULL)",
            name="ck_task_runtime_assignments_concrete_agent_binding",
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
    step_operation_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assignment_revision: Mapped[int | None] = mapped_column(nullable=True)
    assignment_operation_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assignment_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    binding_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    hermes_run_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    attempt_number: Mapped[int | None] = mapped_column(nullable=True)
    role_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
        Index(
            "uq_task_step_history_step_operation_key",
            "step_operation_key",
            unique=True,
        ),
        Index("ix_task_step_history_task_id_id", "task_id", "id"),
        Index("ix_task_step_history_phase_id", "phase_id"),
        Index("ix_task_step_history_next_phase_id", "next_phase_id"),
        Index("ix_task_step_history_rollback_phase_id", "rollback_phase_id"),
        CheckConstraint(
            "verdict IN ('pass', 'partial', 'blocked', 'rollback', 'delegate')",
            name="ck_task_step_history_verdict",
        ),
        CheckConstraint("cycle_number >= 0", name="ck_task_step_history_cycle_nonnegative"),
        CheckConstraint(
            "assignment_revision IS NULL OR assignment_revision > 0",
            name="ck_task_step_history_assignment_revision_positive",
        ),
        CheckConstraint(
            "attempt_number IS NULL OR attempt_number > 0",
            name="ck_task_step_history_attempt_positive",
        ),
        CheckConstraint(
            "request_sha256 IS NULL OR length(request_sha256) = 64",
            name="ck_task_step_history_request_sha256",
        ),
        CheckConstraint(
            "(step_operation_key IS NULL AND request_sha256 IS NULL AND "
            "assignment_revision IS NULL AND assignment_operation_key IS NULL AND "
            "assignment_ref IS NULL AND binding_ref IS NULL AND hermes_run_ref IS NULL AND "
            "attempt_number IS NULL AND role_key IS NULL) OR "
            "(step_operation_key IS NOT NULL AND request_sha256 IS NOT NULL AND "
            "assignment_revision IS NOT NULL AND assignment_operation_key IS NOT NULL AND "
            "assignment_ref IS NOT NULL AND binding_ref IS NOT NULL AND hermes_run_ref IS NOT NULL AND "
            "attempt_number IS NOT NULL AND role_key IS NOT NULL)",
            name="ck_task_step_history_runtime_identity_complete",
        ),
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
