"""SQLAlchemy ORM models mirroring the existing SQLite schema.

Kept 1:1 with db/db_schema.sql so existing rows load without migration.
"""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False, default="")


class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False, default="")
    is_default = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    __table_args__ = (
        CheckConstraint("is_default IN (0, 1)", name="ck_workflows_is_default"),
    )


class Phase(Base):
    __tablename__ = "phases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    code = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    min_time_min = Column(Integer, default=0, server_default="0")
    phase_order = Column(Integer, nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    next_recommendation = Column(Text, nullable=True)
    parallel_with = Column(String, nullable=True)
    rollback_target = Column(String, nullable=True)
    execution_type = Column(
        String,
        default="sync",
        server_default="sync",
    )
    is_seed_managed = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    __table_args__ = (
        CheckConstraint(
            "execution_type IN ('sync', 'parallel')",
            name="ck_phases_execution_type",
        ),
        CheckConstraint("is_seed_managed IN (0, 1)", name="ck_phases_is_seed_managed"),
    )


class Instruction(Base):
    __tablename__ = "instructions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phase_id = Column(
        Integer,
        ForeignKey("phases.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_num = Column(Integer, nullable=False)
    description = Column(String, nullable=False)
    execution_type = Column(
        String,
        default="sync",
        server_default="sync",
    )
    skills = Column(Text, nullable=True)
    __table_args__ = (
        UniqueConstraint("phase_id", "step_num", name="uq_instructions_phase_step"),
        CheckConstraint(
            "execution_type IN ('sync', 'parallel')",
            name="ck_instructions_execution_type",
        ),
    )


class Check(Base):
    __tablename__ = "checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phase_id = Column(
        Integer,
        ForeignKey("phases.id", ondelete="CASCADE"),
        nullable=False,
    )
    description = Column(String, nullable=False)
    __table_args__ = (
        UniqueConstraint("phase_id", "description", name="uq_checks_phase_description"),
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phase_id = Column(
        Integer,
        ForeignKey("phases.id", ondelete="CASCADE"),
        nullable=False,
    )
    description = Column(String, nullable=False)
    __table_args__ = (
        UniqueConstraint("phase_id", "description", name="uq_evidence_phase_description"),
    )


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    code = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    key_patterns = Column(String, nullable=False, default="[]", server_default="[]")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    task_key = Column(String, nullable=False, unique=True)
    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    current_phase = Column(
        String,
        nullable=False,
        default="-1",
        server_default="-1",
    )
    status = Column(
        String,
        default="active",
        server_default="active",
    )
    created_at = Column(String, default="CURRENT_TIMESTAMP", server_default="CURRENT_TIMESTAMP")
    updated_at = Column(String, default="CURRENT_TIMESTAMP", server_default="CURRENT_TIMESTAMP")
    __table_args__ = (
        CheckConstraint("status IN ('active', 'done', 'blocked')", name="ck_tasks_status"),
    )


class TaskHistory(Base):
    __tablename__ = "task_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_id = Column(Integer, ForeignKey("phases.id"), nullable=False)
    status = Column(
        String,
        default="pending",
        server_default="pending",
    )
    completed_at = Column(String, nullable=True)
    __table_args__ = (
        UniqueConstraint("task_id", "phase_id", name="uq_task_history_task_phase"),
        CheckConstraint(
            "status IN ('pending', 'done', 'partial', 'blocked', 'rollback', 'delegated')",
            name="ck_task_history_status",
        ),
    )


class SupervisorRun(Base):
    __tablename__ = "supervisor_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_id = Column(Integer, ForeignKey("phases.id"), nullable=False)
    verdict = Column(String, nullable=False)
    report = Column(Text, nullable=False, default="", server_default="")
    covered = Column(Text, nullable=False, default="[]", server_default="[]")
    missing = Column(Text, nullable=False, default="[]", server_default="[]")
    blockers = Column(Text, nullable=False, default="[]", server_default="[]")
    next_phase_id = Column(Integer, ForeignKey("phases.id"), nullable=True)
    rollback_phase_id = Column(Integer, ForeignKey("phases.id"), nullable=True)
    context_snapshot = Column(Text, nullable=False, default="{}", server_default="{}")
    response = Column(Text, nullable=False, default="{}", server_default="{}")
    created_at = Column(String, default="CURRENT_TIMESTAMP", server_default="CURRENT_TIMESTAMP")
    __table_args__ = (
        CheckConstraint(
            "verdict IN ('pass', 'partial', 'blocked', 'rollback', 'delegate')",
            name="ck_supervisor_runs_verdict",
        ),
    )


class CliHistory(Base):
    __tablename__ = "cli_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    command = Column(String, nullable=False)
    task_key = Column(String, nullable=True)
    request = Column(Text, nullable=True)
    response = Column(Text, nullable=True)
    created_at = Column(String, default="CURRENT_TIMESTAMP", server_default="CURRENT_TIMESTAMP")
