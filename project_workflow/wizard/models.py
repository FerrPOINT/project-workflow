"""Domain models — dataclasses for workflow entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PhaseCheck:
    """Проверка которую CLI выполняет для фазы."""
    description: str = ""


@dataclass
class PhaseEvidence:
    """Evidence, которое должен собрать исполнитель текущей CLI-фазы."""
    item: str = ""


@dataclass
class PhaseInstruction:
    """Инструкция для исполнителя текущей CLI-фазы."""
    step: str = ""
    example: Optional[str] = None
    execution_type: str = "sync"
    skills: List[str] = field(default_factory=list)


@dataclass
class PhaseDelegate:
    """Конфигурация delegate_task для делегированной фазы."""
    agent: str = ""
    prompt_template: str = ""
    context: List[str] = field(default_factory=list)
    toolsets: List[str] = field(default_factory=list)
    timeout_min: int = 10
    max_cycles: int = 3


@dataclass
class Phase:
    """Полное описание фазы workflow."""
    id: int | None = 0
    code: str = ""
    name: str = ""
    description: str = ""
    min_time_min: int = 0
    is_blocker: bool = False
    is_delegated: bool = False
    is_critic: bool = False
    checks: List[PhaseCheck] = field(default_factory=list)
    evidence: List[PhaseEvidence] = field(default_factory=list)
    instructions: List[PhaseInstruction] = field(default_factory=list)
    delegate: Optional[PhaseDelegate] = None
    next_recommendation: str = ""
    parallel_with: Optional[str] = None
    rollback_target: Optional[str] = None
    execution_type: str = "sync"

    selected_agent: Optional[str] = None

    def __post_init__(self) -> None:
        if self.selected_agent and not self.delegate:
            self.delegate = PhaseDelegate(
                agent=self.selected_agent,
                prompt_template=f"Phase {self.code}: {self.description}",
                toolsets=[],
            )

    def render_instructions(self, context: dict) -> List[str]:
        """Подставить переменные в инструкции."""
        result = []
        for inst in self.instructions:
            step = inst.step
            for key, val in context.items():
                step = step.replace(f"{{{key}}}", str(val))
            result.append(step)
        return result
