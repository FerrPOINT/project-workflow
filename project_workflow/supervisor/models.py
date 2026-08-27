"""Domain models — dataclasses for workflow entities."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PhaseCheck:
    """Проверка которую CLI выполняет для фазы."""

    description: str = ""
    id: int | None = None


@dataclass
class PhaseEvidence:
    """Evidence, которое должен собрать исполнитель текущей CLI-фазы."""

    item: str = ""
    id: int | None = None


@dataclass
class PhaseInstruction:
    """Инструкция для исполнителя текущей CLI-фазы."""

    step: str = ""
    execution_type: str = "sync"
    skills: list[str] = field(default_factory=list)
    id: int | None = None
    step_num: int | None = None


@dataclass
class PhaseDelegate:
    """Конфигурация delegate_task для делегированной фазы."""

    agent: str = ""
    hermes_profile: str | None = None


@dataclass
class Phase:
    """Полное описание фазы workflow."""

    id: int | None = 0
    code: str = ""
    name: str = ""
    description: str = ""
    checks: list[PhaseCheck] = field(default_factory=list)
    evidence: list[PhaseEvidence] = field(default_factory=list)
    instructions: list[PhaseInstruction] = field(default_factory=list)
    delegate: PhaseDelegate | None = None
    parallel_with_phase_code: str | None = None
    rollback_target_phase_code: str | None = None
    execution_type: str = "sync"
