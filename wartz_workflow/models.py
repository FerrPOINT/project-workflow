"""Domain models — dataclasses for workflow entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PhaseCheck:
    """Проверка которую CLI выполняет для фазы."""
    description: str = ""
    path: Optional[str] = None
    expected: Optional[List[str]] = None
    fail_msg: str = "Check failed"
    optional: bool = False


@dataclass
class PhaseEvidence:
    """Evidence который агент должен собрать."""
    item: str = ""


@dataclass
class PhaseInstruction:
    """Инструкция для агента."""
    step: str = ""
    example: Optional[str] = None
    execution_type: str = "sync"


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
    id: str = ""
    name: str = ""
    description: str = ""
    min_time_min: int = 0
    is_blocker: bool = False
    is_delegated: bool = False
    is_critic: bool = False
    skills: List[str] = field(default_factory=list)
    checks: List[PhaseCheck] = field(default_factory=list)
    evidence: List[PhaseEvidence] = field(default_factory=list)
    instructions: List[PhaseInstruction] = field(default_factory=list)
    delegate: Optional[PhaseDelegate] = None
    next_recommendation: str = ""
    parallel_with: Optional[str] = None
    gate_after: Optional[str] = None
    rollback_target: Optional[str] = None
    execution_mode: str = "sync"

    def render_instructions(self, context: dict) -> List[str]:
        """Подставить переменные в инструкции."""
        result = []
        for inst in self.instructions:
            step = inst.step
            for key, val in context.items():
                step = step.replace(f"{{{key}}}", str(val))
            result.append(step)
        return result
