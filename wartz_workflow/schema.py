"""Schema loader — читает декларативное описание фаз из YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass
class PhaseCheck:
    """Проверка которую CLI выполняет для фазы."""
    type: str                          # file_exists, jira_status, git_commit, etc.
    description: str = ""
    path: Optional[str] = None         # для file_exists
    expected: Optional[List[str]] = None  # для jira_status
    command: Optional[str] = None     # shell-команда
    fail_msg: str = "Check failed"
    optional: bool = False             # если True — warning, не blocker


@dataclass
class PhaseEvidence:
    """Evidence который агент должен собрать."""
    item: str                          # описание evidence
    validator: Optional[str] = None    # тип валидации (grep, file_size, etc.)


@dataclass
class PhaseInstruction:
    """Инструкция для агента."""
    step: str                          # текст инструкции
    tool: Optional[str] = None         # рекомендуемый инструмент (skill, browser, etc.)
    example: Optional[str] = None    # пример команды


@dataclass
class PhaseQuestion:
    """Вопрос для фазы — задаётся агентом, анализируется по keywords."""
    text: str                          # текст вопроса
    required: bool = True              # обязательный или можно ответить "не делал"
    expected_keywords: List[str] = field(default_factory=list)  # ключевые слова для положительного ответа
    min_evidence_lines: int = 1        # минимум строк evidence
    hint: Optional[str] = None         # подсказка при неполном ответе
    auto_command: Optional[str] = None # команда для автопроверки
    validate_fn: Optional[str] = None # имя python-функции для валидации (опционально)


@dataclass
class PhaseDelegate:
    """Конфигурация delegate_task для делегированной фазы."""
    agent: str                         # имя агента (wartzresearcher, wartzreviewer, etc.)
    prompt_template: str = ""          # шаблон промпта
    context: List[str] = field(default_factory=list)  # доп. контекст
    toolsets: List[str] = field(default_factory=list)   # toolsets агента
    timeout_min: int = 10
    max_cycles: int = 3                # максимум retry cycles при FAIL


@dataclass
class Phase:
    """Полное описание фазы workflow."""
    id: str
    name: str
    description: str = ""
    min_time_min: int = 0
    is_blocker: bool = False
    is_delegated: bool = False
    is_critic: bool = False
    skills: List[str] = field(default_factory=list)
    checks: List[PhaseCheck] = field(default_factory=list)
    evidence: List[PhaseEvidence] = field(default_factory=list)
    instructions: List[PhaseInstruction] = field(default_factory=list)
    questions: List[PhaseQuestion] = field(default_factory=list)
    delegate: Optional[PhaseDelegate] = None
    next_recommendation: str = ""
    parallel_with: Optional[str] = None  # фаза, с которой можно параллельно
    gate_after: Optional[str] = None     # CriticGate после этой фазы
    rollback_target: Optional[str] = None  # куда откатиться при FAIL

    def render_instructions(self, context: dict) -> List[str]:
        """Подставить переменные в инструкции."""
        result = []
        for inst in self.instructions:
            step = inst.step
            for key, val in context.items():
                step = step.replace(f"{{{key}}}", str(val))
            result.append(step)
        return result


# ── Schema Loader ─────────────────────────────────────────────────────

SCHEMA_PATH = Path(__file__).parent / "references" / "phases.yaml"


def load_phases(path: Optional[Path] = None) -> List[Phase]:
    """Загрузить описание фаз из YAML."""
    p = path or SCHEMA_PATH
    if not p.exists():
        return []

    with open(p, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    phases: List[Phase] = []
    for item in raw.get("phases", []):
        checks = [PhaseCheck(**c) for c in item.get("checks", [])]
        evidence = [PhaseEvidence(**e) for e in item.get("evidence", [])]
        instructions = [PhaseInstruction(**i) for i in item.get("instructions", [])]
        questions = [PhaseQuestion(**q) for q in item.get("questions", [])]

        delegate = None
        if "delegate" in item:
            d = item["delegate"]
            delegate = PhaseDelegate(
                agent=d["agent"],
                prompt_template=d.get("prompt_template", ""),
                context=d.get("context", []),
                toolsets=d.get("toolsets", []),
                timeout_min=d.get("timeout_min", 10),
                max_cycles=d.get("max_cycles", 3),
            )

        phases.append(Phase(
            id=item["id"],
            name=item["name"],
            description=item.get("description", ""),
            min_time_min=item.get("min_time_min", 0),
            is_blocker=item.get("is_blocker", False),
            is_delegated=item.get("is_delegated", False),
            is_critic=item.get("is_critic", False),
            skills=item.get("skills", []),
            checks=checks,
            evidence=evidence,
            instructions=instructions,
            delegate=delegate,
            next_recommendation=item.get("next_recommendation", ""),
            parallel_with=item.get("parallel_with"),
            gate_after=item.get("gate_after"),
            rollback_target=item.get("rollback_target"),
            questions=questions,
        ))

    return phases


def get_phase(phase_id: str, phases: Optional[List[Phase]] = None) -> Optional[Phase]:
    """Найти фазу по ID."""
    plist = phases or load_phases()
    for ph in plist:
        if ph.id == phase_id:
            return ph
    return None


def get_phase_order(phases: Optional[List[Phase]] = None) -> List[str]:
    """Вернуть список ID фаз в порядке следования."""
    plist = phases or load_phases()
    return [p.id for p in plist]
