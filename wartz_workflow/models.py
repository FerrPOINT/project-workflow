"""Domain models — dataclasses for workflow entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PhaseCheck:
    """Проверка которую CLI выполняет для фазы."""
    type: str = ""                          # file_exists, jira_status, git_commit, etc.
    description: str = ""
    path: Optional[str] = None             # для file_exists
    expected: Optional[List[str]] = None  # для jira_status
    command: Optional[str] = None        # shell-команда
    fail_msg: str = "Check failed"
    optional: bool = False                # если True — warning, не blocker


@dataclass
class PhaseEvidence:
    """Evidence который агент должен собрать."""
    item: str = ""                         # описание evidence
    validator: Optional[str] = None        # тип валидации (grep, file_size, etc.)


@dataclass
class PhaseInstruction:
    """Инструкция для агента."""
    step: str = ""                         # текст инструкции
    tool: Optional[str] = None             # рекомендуемый инструмент (skill, browser, etc.)
    example: Optional[str] = None          # пример команды
    execution_type: str = "sync"           # sync | parallel


@dataclass
class PhaseDelegate:
    """Конфигурация delegate_task для делегированной фазы."""
    agent: str = ""                        # имя агента (wartzresearcher, wartzreviewer, etc.)
    prompt_template: str = ""              # шаблон промпта
    context: List[str] = field(default_factory=list)  # доп. контекст
    toolsets: List[str] = field(default_factory=list)   # toolsets агента
    timeout_min: int = 10
    max_cycles: int = 3                    # максимум retry cycles при FAIL


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
    parallel_with: Optional[str] = None   # фаза, с которой можно параллельно
    gate_after: Optional[str] = None      # CriticGate после этой фазы
    rollback_target: Optional[str] = None # куда откатиться при FAIL
    execution_mode: str = "sync"          # sync | parallel — режим выполнения фазы

    def render_instructions(self, context: dict) -> List[str]:
        """Подставить переменные в инструкции."""
        result = []
        for inst in self.instructions:
            step = inst.step
            for key, val in context.items():
                step = step.replace(f"{{{key}}}", str(val))
            result.append(step)
        return result
