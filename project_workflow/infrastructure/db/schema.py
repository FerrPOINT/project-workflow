"""Phase catalog loading and empty-database bootstrap.

Все данные — только из БД (phases, instructions, checks, evidence).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from project_workflow.domain.phase_graph import validate_phase_graph
from project_workflow.domain.repositories import UnitOfWork

from ... import config
from ...supervisor.models import (
    Phase,
    PhaseCheck,
    PhaseDelegate,
    PhaseEvidence,
    PhaseInstruction,
)

# ── DB Load ─────────────────────────────────────────────────────


def _build_phase_from_db(
    phase_row: Any,
    uow: UnitOfWork,
) -> Phase:
    """Assemble a supervisor Phase dataclass from a domain Phase + repositories."""
    phase_id = phase_row.id
    phase_code = phase_row.code or ""
    inst_rows = uow.instructions.list(phase_id)

    instructions = [
        PhaseInstruction(
            step=ir["description"],
            execution_type=ir.get("execution_type", "sync"),
            skills=ir.get("skills") or [],
            id=ir.get("id"),
            step_num=ir.get("step_num"),
        )
        for ir in inst_rows
    ]

    check_rows = uow.phases.get_checks(phase_id)
    checks = [
        PhaseCheck(
            description=cr["description"],
            id=cr.get("id"),
        )
        for cr in check_rows
    ]

    ev_rows = uow.phases.get_evidence(phase_id)
    evidence = [
        PhaseEvidence(
            item=er["description"],
            id=er.get("id"),
        )
        for er in ev_rows
    ]

    delegate = None
    if phase_row.agent_id:
        agent = uow.agents.get_by_id(phase_row.agent_id)
        if agent:
            delegate = PhaseDelegate(
                agent=agent.name,
                hermes_profile=agent.hermes_profile,
                prompt_template=f"Фаза {phase_code}",
                toolsets=[],  # domain Agent does not store toolsets in this schema
                timeout_min=10,
                max_cycles=3,
            )

    return Phase(
        id=phase_id,
        code=phase_code,
        name=phase_row.name,
        description=phase_row.description or "",
        min_time_min=phase_row.min_time_min or 0,
        is_blocker=phase_row.is_blocker,
        is_delegated=phase_row.is_delegated,
        is_critic=phase_row.is_critic,
        checks=checks,
        evidence=evidence,
        instructions=instructions,
        delegate=delegate,
        next_recommendation=phase_row.next_recommendation or "",
        parallel_with=phase_row.parallel_with,
        rollback_target=phase_row.rollback_target,
        execution_type=phase_row.execution_type or "sync",
    )


def load_phases_from_db(
    uow: UnitOfWork,
    workflow_id: int | None = None,
) -> list[Phase]:
    """Load all supervisor phases from a UnitOfWork instance."""
    rows = uow.phases.list(workflow_id)
    return [_build_phase_from_db(r, uow) for r in rows]


# ── Bootstrap seed ───────────


class _SeedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _nonblank(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"Поле {field_name} не может быть пустым")
    return normalized


class _SeedInstruction(_SeedModel):
    description: str
    execution_type: Literal["sync", "parallel"] = "sync"
    skills: list[str] = Field(default_factory=list)

    @field_validator("description")
    @classmethod
    def _description_not_blank(cls, value: str) -> str:
        return _nonblank(value, "description инструкции")

    @field_validator("skills")
    @classmethod
    def _normalize_skills(cls, value: list[str]) -> list[str]:
        normalized = [_nonblank(skill, "skill") for skill in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("skills должен содержать уникальные значения")
        return normalized


class _SeedTextItem(_SeedModel):
    description: str

    @field_validator("description")
    @classmethod
    def _description_not_blank(cls, value: str) -> str:
        return _nonblank(value, "description")


class _SeedDelegate(_SeedModel):
    agent: str
    hermes_profile: str | None = None

    @field_validator("agent")
    @classmethod
    def _agent_not_blank(cls, value: str) -> str:
        return _nonblank(value, "agent делегата")

    @field_validator("hermes_profile")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

class _SeedPhase(_SeedModel):
    phase_order: int = Field(gt=0)
    code: str
    name: str
    description: str = ""
    min_time_min: int = Field(default=0, ge=0)
    execution_type: Literal["sync", "parallel"] = "sync"
    delegate: _SeedDelegate | None = None
    instructions: list[_SeedInstruction] = Field(default_factory=list)
    checks: list[str | _SeedTextItem] = Field(default_factory=list)
    evidence: list[str | _SeedTextItem] = Field(default_factory=list)
    next_recommendation: str = ""
    parallel_with: str | None = None
    rollback_target: str | None = None
    is_blocker: bool = False
    is_critic: bool = False

    @field_validator("code", "name")
    @classmethod
    def _identity_not_blank(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("parallel_with", "rollback_target")
    @classmethod
    def _normalize_link(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


def _seed_text(value: str | _SeedTextItem) -> str:
    return _nonblank(value if isinstance(value, str) else value.description, "description")


def _load_seed(path: Path | str | None = None) -> list[_SeedPhase]:
    seed_path = Path(path) if path else config.SEED_PATH
    if not seed_path.exists():
        raise FileNotFoundError(f"Файл начального каталога не найден: {seed_path}")
    if seed_path.suffix.lower() != ".json":
        raise ValueError("Начальный каталог должен быть в формате JSON")
    with seed_path.open(encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Некорректный начальный каталог: {seed_path}") from exc
    if not isinstance(data, list):
        raise ValueError("Корневое значение начального каталога должно быть массивом")
    if not data:
        raise ValueError("Начальный каталог должен содержать хотя бы одну фазу")
    phases: list[_SeedPhase] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Некорректная фаза начального каталога с индексом {index}: нужен объект")
        label = str(item.get("code") or f"index {index}")
        try:
            phase = _SeedPhase.model_validate(item)
        except ValidationError as exc:
            raise ValueError(f"Некорректная фаза начального каталога {label!r}: {exc}") from exc
        if phase.phase_order != index:
            raise ValueError(
                f"Некорректная фаза начального каталога {phase.code!r}: "
                f"phase_order должен быть {index}, получено {phase.phase_order}"
            )
        phases.append(phase)

    try:
        validate_phase_graph(phases)
    except ValueError as exc:
        raise ValueError(f"Некорректный граф фаз начального каталога: {exc}") from exc
    for phase in phases:
        for field_name in ("checks", "evidence"):
            values = [_seed_text(item).casefold() for item in getattr(phase, field_name)]
            if len(values) != len(set(values)):
                raise ValueError(
                    f"Некорректная фаза начального каталога {phase.code!r}: "
                    f"повторяющиеся описания в поле {field_name}"
                )
    return phases


def _phase_item_to_supervisor(item: _SeedPhase) -> Phase:
    """Convert a validated seed model into a supervisor Phase dataclass."""
    instructions = [
        PhaseInstruction(
            step=instruction.description,
            execution_type=instruction.execution_type,
            skills=instruction.skills,
        )
        for instruction in item.instructions
    ]
    checks = [PhaseCheck(description=_seed_text(check)) for check in item.checks]
    evidence = [PhaseEvidence(item=_seed_text(evidence_item)) for evidence_item in item.evidence]

    delegate: PhaseDelegate | None = None
    if item.delegate:
        delegate_data = item.delegate
        delegate = PhaseDelegate(
            agent=delegate_data.agent,
            hermes_profile=delegate_data.hermes_profile,
            prompt_template=f"Фаза {item.code}",
            toolsets=[],
            timeout_min=10,
            max_cycles=3,
        )
    return Phase(
        id=None,
        code=item.code,
        name=item.name,
        description=item.description,
        min_time_min=item.min_time_min,
        is_blocker=item.is_blocker,
        is_delegated=bool(delegate),
        is_critic=item.is_critic,
        checks=checks,
        evidence=evidence,
        instructions=instructions,
        delegate=delegate,
        next_recommendation=item.next_recommendation,
        parallel_with=item.parallel_with,
        rollback_target=item.rollback_target,
        execution_type=item.execution_type,
    )


def load_phases_from_seed(
    path: Path | str | None = None,
) -> list[Phase]:
    """Load phases from the packaged JSON seed for initial bootstrap."""
    items = _load_seed(path)
    return [_phase_item_to_supervisor(item) for item in items]


# ── Catalog bootstrap ─────────────────────────────────────────────


def ensure_phase_catalog(
    uow: UnitOfWork,
    seed_path: Path | str | None = None,
) -> None:
    """Bootstrap the packaged phase catalog only for a new empty database."""
    seed_path = Path(seed_path) if seed_path else config.SEED_PATH
    seed_phases = load_phases_from_seed(seed_path)
    if uow.workflows.list():
        return
    default_workflow = uow.workflows.ensure_default_exists(config.DEFAULT_WORKFLOW_NAME)
    workflow_id = default_workflow.id
    assert workflow_id is not None

    for phase in seed_phases:
        delegate = phase.delegate
        agent_name = (delegate.agent or "") if delegate else ""
        if agent_name and not uow.agents.get_by_name(agent_name):
            uow.agents.create(
                {
                    "name": agent_name,
                    "description": f"Агент начального каталога: {agent_name}",
                    "hermes_profile": delegate.hermes_profile if delegate else None,
                }
            )

    for order, phase in enumerate(seed_phases, start=1):
        assigned_agent_name = phase.delegate.agent if phase.delegate else ""
        agent_id = None
        if assigned_agent_name:
            agent_id = next(
                (agent.id for agent in uow.agents.list() if agent.name == assigned_agent_name),
                None,
            )
        phase_id = uow.phases.create(
            {
                "workflow_id": workflow_id,
                "code": phase.code,
                "name": phase.name,
                "description": phase.description,
                "min_time_min": phase.min_time_min,
                "phase_order": order,
                "next_recommendation": phase.next_recommendation,
                "parallel_with": phase.parallel_with,
                "rollback_target": phase.rollback_target,
                "execution_type": phase.execution_type,
                "is_seed_managed": True,
                "is_blocker": phase.is_blocker,
                "is_delegated": phase.is_delegated,
                "is_critic": phase.is_critic,
                "agent_id": agent_id,
            }
        )
        for idx, instr in enumerate(phase.instructions, start=1):
            uow.instructions.create(
                int(phase_id),
                {
                    "step_num": idx,
                    "description": instr.step,
                    "execution_type": instr.execution_type,
                    "skills": instr.skills,
                },
            )
        uow.phases.set_checks(
            int(phase_id),
            [{"description": check.description} for check in phase.checks],
        )
        uow.phases.set_evidence(
            int(phase_id),
            [{"description": item.item} for item in phase.evidence],
        )
