"""Phase contract builder — turns DB phase catalog into structured PhaseContract."""

from __future__ import annotations

from typing import Any

from project_workflow import config
from project_workflow.domain.phase_grouping import group_parallel_phases

from .models import Phase
from .types import PhaseContract


def text_from_instruction(item: Any) -> str:
    step = str(getattr(item, "step", "") or "").strip()
    skills = [str(skill).strip() for skill in (getattr(item, "skills", None) or []) if str(skill).strip()]
    if not skills:
        return step
    recommendation = f"Используй навыки: {', '.join(skills)}."
    return f"{step} {recommendation}" if step else recommendation


def text_from_check(item: Any) -> str:
    return str(getattr(item, "description", "") or "").strip()


def text_from_evidence(item: Any) -> str:
    return str(getattr(item, "item", "") or "").strip()


def skills_from_phase(phase: Phase) -> list[str]:
    """Return stable, de-duplicated skill names declared by phase instructions."""
    seen: set[str] = set()
    skills: list[str] = []
    for instruction in phase.instructions:
        for raw_skill in getattr(instruction, "skills", None) or []:
            skill = str(raw_skill).strip()
            if skill and skill not in seen:
                seen.add(skill)
                skills.append(skill)
    return skills


def actor_from_phase(phase: Phase) -> str:
    """Return the executor kind without turning Supervisor into an executor."""
    if phase.delegate and phase.delegate.agent == config.CODEX_OPERATOR_AGENT:
        return "codex_operator"
    return "hermes"


def phase_to_dict(phase: Phase, workflow_revision: str = "") -> dict[str, Any]:
    return {
        "id": phase.id,
        "code": phase.code,
        "name": phase.name,
        "workflow_revision": workflow_revision,
        "actor": actor_from_phase(phase),
        "description": phase.description,
        "instructions": [text_from_instruction(item) for item in phase.instructions],
        "checks": [text_from_check(item) for item in phase.checks],
        "evidence": [text_from_evidence(item) for item in phase.evidence],
        "skills": skills_from_phase(phase),
        "execution_type": phase.execution_type,
        "parallel_with": phase.parallel_with,
        "rollback_target": phase.rollback_target,
        "delegate_agent": phase.delegate.agent if phase.delegate else None,
        "hermes_profile": phase.delegate.hermes_profile if phase.delegate else None,
        "delegate_toolsets": list(phase.delegate.toolsets) if phase.delegate else [],
    }


class PhaseContractBuilder:
    """Builds PhaseContract from DB Phase models."""

    def __init__(self, all_phases: list[Phase], workflow_revision: str = ""):
        self.all_phases = all_phases
        self.workflow_revision = workflow_revision
        self._phase_map: dict[str, Phase] | None = None

    @property
    def phase_map(self) -> dict[str, Phase]:
        if self._phase_map is None:
            self._phase_map = {phase.code: phase for phase in self.all_phases}
        return self._phase_map

    def _phase_groups(self) -> list[list[Phase]]:
        """Return the canonical execution sequence, including isolated parallel phases."""
        return group_parallel_phases(
            self.all_phases,
            code_of=lambda phase: phase.code,
            execution_type_of=lambda phase: phase.execution_type,
            parallel_with_of=lambda phase: phase.parallel_with,
        )

    def build(self, phase: Phase) -> PhaseContract:
        """Single-phase contract."""
        return PhaseContract(
            phase_code=phase.code,
            phase_name=phase.name,
            workflow_revision=self.workflow_revision,
            actor=actor_from_phase(phase),
            description=phase.description,
            instructions=[text_from_instruction(item) for item in phase.instructions],
            required_checks=[text_from_check(item) for item in phase.checks],
            required_evidence=[text_from_evidence(item) for item in phase.evidence],
            skills=skills_from_phase(phase),
            execution_type=phase.execution_type,
            delegate_agent=phase.delegate.agent if phase.delegate else None,
            hermes_profile=phase.delegate.hermes_profile if phase.delegate else None,
            delegate_toolsets=list(phase.delegate.toolsets) if phase.delegate else [],
            parallel_with=phase.parallel_with,
            rollback_target=phase.rollback_target,
        )

    def build_missing(self, phase_code: str) -> PhaseContract:
        """Placeholder when phase is not in catalog."""
        return PhaseContract(
            phase_code=phase_code,
            phase_name="Неизвестная фаза",
            workflow_revision=self.workflow_revision,
            description="",
            instructions=[],
            required_checks=[],
            required_evidence=[],
            execution_type="sync",
        )

    def build_parallel(self, group: list[Phase]) -> PhaseContract:
        """Merged contract for a parallel group."""
        instructions: list[str] = []
        checks: list[str] = []
        evidence: list[str] = []
        group_details: list[dict[str, Any]] = []
        for ph in group:
            ph_instructions = [text_from_instruction(inst) for inst in ph.instructions]
            ph_checks = [text_from_check(chk) for chk in ph.checks]
            ph_evidence = [text_from_evidence(ev) for ev in ph.evidence]
            for txt in ph_instructions:
                if txt:
                    instructions.append(f"[{ph.code}] {txt}")
            for txt in ph_checks:
                if txt:
                    checks.append(f"[{ph.code}] {txt}")
            for txt in ph_evidence:
                if txt:
                    evidence.append(f"[{ph.code}] {txt}")
            group_details.append(
                {
                    "phase_code": ph.code,
                    "phase_name": ph.name,
                    "workflow_revision": self.workflow_revision,
                    "actor": actor_from_phase(ph),
                    "description": ph.description,
                    "instructions": [t for t in ph_instructions if t],
                    "required_checks": [t for t in ph_checks if t],
                    "required_evidence": [t for t in ph_evidence if t],
                    "skills": skills_from_phase(ph),
                    "execution_type": ph.execution_type,
                    "delegate_agent": ph.delegate.agent if ph.delegate else None,
                    "hermes_profile": ph.delegate.hermes_profile if ph.delegate else None,
                    "delegate_toolsets": list(ph.delegate.toolsets) if ph.delegate else [],
                    "parallel_with": ph.parallel_with,
                    "rollback_target": ph.rollback_target,
                }
            )
        first = group[0]
        representative = first.delegate or next((phase.delegate for phase in group if phase.delegate), None)
        return PhaseContract(
            phase_code=first.code,
            phase_name=f"Параллельная группа: {', '.join(p.code for p in group)}",
            workflow_revision=self.workflow_revision,
            actor=actor_from_phase(first),
            description="\n".join(f"- {p.code}: {p.description or '-'}" for p in group),
            instructions=instructions or ["Нет отдельных инструкций — следуй описаниям фаз и обязательным проверкам."],
            required_checks=checks or ["Нет явных проверок."],
            required_evidence=evidence or ["Нет явных подтверждений."],
            skills=list(dict.fromkeys(skill for phase in group for skill in skills_from_phase(phase))),
            execution_type="parallel",
            delegate_agent=representative.agent if representative else None,
            hermes_profile=representative.hermes_profile if representative else None,
            delegate_toolsets=list(representative.toolsets) if representative else [],
            parallel_with=first.parallel_with,
            rollback_target=first.rollback_target,
            group_phases=[p.code for p in group],
            group_details=group_details,
        )

    def build_checklist(self, phase: Phase) -> list[str]:
        """Only checks + evidence — criteria for report evaluation."""
        items: list[str] = []
        items.extend(text_from_check(item) for item in phase.checks)
        items.extend(text_from_evidence(item) for item in phase.evidence)
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            k = item.strip().lower()
            if k and k not in seen:
                seen.add(k)
                deduped.append(item.strip())
        return deduped

    def build_evaluation_items(self, phase: Phase) -> list[tuple[str, str]]:
        """Stable internal IDs paired with public checklist text."""
        items: list[tuple[str, str]] = []
        for index, check in enumerate(phase.checks, start=1):
            text = text_from_check(check)
            if text:
                item_id = getattr(check, "id", None)
                token = item_id if item_id is not None else index
                items.append((f"{phase.code}:check:{token}", text))
        for index, evidence in enumerate(phase.evidence, start=1):
            text = text_from_evidence(evidence)
            if text:
                item_id = getattr(evidence, "id", None)
                token = item_id if item_id is not None else index
                items.append((f"{phase.code}:evidence:{token}", text))
        return items

    def build_parallel_evaluation_items(self, group: list[Phase]) -> list[tuple[str, str]]:
        return [item for phase in group for item in self.build_evaluation_items(phase)]

    def build_parallel_checklist(self, group: list[Phase]) -> list[str]:
        items: list[str] = []
        for ph in group:
            for chk in ph.checks:
                items.append(text_from_check(chk))
            for ev in ph.evidence:
                items.append(text_from_evidence(ev))
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            k = item.strip().lower()
            if k and k not in seen:
                seen.add(k)
                deduped.append(item.strip())
        return deduped

    def get_parallel_group(self, start_phase: Phase) -> list[Phase]:
        for group in self._phase_groups():
            if any(phase.code == start_phase.code for phase in group):
                return group
        return [start_phase]

    def get_next_phase(self, phase_code: str) -> tuple[str | None, str | None]:
        groups = self._phase_groups()
        for index, group in enumerate(groups):
            if not any(phase.code == phase_code for phase in group):
                continue
            if index + 1 >= len(groups):
                return None, None
            nxt = groups[index + 1][0]
            return nxt.code, nxt.name
        return None, None

    def _next_after_group(self, group: list[Phase]) -> tuple[str | None, str | None]:
        if not group:
            return None, None
        return self.get_next_phase(group[0].code)

    def build_next_contract(self, phase_code: str | None) -> PhaseContract | None:
        """Contract for the phase that follows the current one."""
        if not phase_code:
            return None
        ph = self.phase_map.get(phase_code)
        if not ph:
            return None
        if ph.execution_type == "parallel":
            group = self.get_parallel_group(ph)
            return self.build_parallel(group)
        return self.build(ph)
