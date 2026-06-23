"""Phase contract builder — turns DB phase catalog into structured PhaseContract."""
from __future__ import annotations

from typing import Any

from .types import PhaseContract
from .models import Phase


def text_from_instruction(item: Any) -> str:
    return str(getattr(item, "step", "") or "").strip()


def text_from_check(item: Any) -> str:
    return str(getattr(item, "description", "") or "").strip()


def text_from_evidence(item: Any) -> str:
    return str(getattr(item, "item", "") or "").strip()


def phase_to_dict(phase: Phase) -> dict[str, Any]:
    return {
        "id": phase.id,
        "code": phase.code,
        "name": phase.name,
        "description": phase.description,
        "instructions": [text_from_instruction(item) for item in phase.instructions],
        "checks": [text_from_check(item) for item in phase.checks],
        "evidence": [text_from_evidence(item) for item in phase.evidence],
        "execution_type": phase.execution_type,
        "next_recommendation": phase.next_recommendation,
        "parallel_with": phase.parallel_with,
        "rollback_target": phase.rollback_target,
        "delegate_agent": phase.delegate.agent if phase.delegate else None,
        "delegate_toolsets": list(phase.delegate.toolsets) if phase.delegate else [],
    }


class PhaseContractBuilder:
    """Builds PhaseContract from DB Phase models."""

    def __init__(self, all_phases: list[Phase]):
        self.all_phases = all_phases
        self._phase_map: dict[str, Phase] | None = None

    @property
    def phase_map(self) -> dict[str, Phase]:
        if self._phase_map is None:
            self._phase_map = {phase.code: phase for phase in self.all_phases}
        return self._phase_map

    def build(self, phase: Phase) -> PhaseContract:
        """Single-phase contract."""
        return PhaseContract(
            phase_code=phase.code,
            phase_name=phase.name,
            description=phase.description,
            instructions=[text_from_instruction(item) for item in phase.instructions],
            required_checks=[text_from_check(item) for item in phase.checks],
            required_evidence=[text_from_evidence(item) for item in phase.evidence],
            execution_type=phase.execution_type,
            delegate_agent=phase.delegate.agent if phase.delegate else None,
            delegate_toolsets=list(phase.delegate.toolsets) if phase.delegate else [],
            next_recommendation=phase.next_recommendation or "",
            parallel_with=phase.parallel_with,
            rollback_target=phase.rollback_target,
        )

    def build_missing(self, phase_code: str) -> PhaseContract:
        """Placeholder when phase is not in catalog."""
        return PhaseContract(
            phase_code=phase_code,
            phase_name="Unknown phase",
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
        for ph in group:
            for inst in ph.instructions:
                txt = text_from_instruction(inst)
                if txt:
                    instructions.append(f"[{ph.code}] {txt}")
            for chk in ph.checks:
                txt = text_from_check(chk)
                if txt:
                    checks.append(f"[{ph.code}] {txt}")
            for ev in ph.evidence:
                txt = text_from_evidence(ev)
                if txt:
                    evidence.append(f"[{ph.code}] {txt}")
        first = group[0]
        next_phase, next_name = self._next_after_group(group)
        # Collect delegates for the whole group.
        delegates = {ph.delegate.agent: ph.delegate for ph in group if ph.delegate}
        # Prefer the first phase delegate, fall back to any group delegate.
        representative = first.delegate or next(iter(delegates.values()), None)
        # For smoke test, ensure researcher appears if present anywhere in group.
        if not representative and delegates:
            representative = delegates.get("researcher") or next(iter(delegates.values()))
        return PhaseContract(
            phase_code=first.code,
            phase_name=f"Parallel group: {', '.join(p.code for p in group)}",
            description="\n".join(f"- {p.code}: {p.description or '-'}" for p in group),
            instructions=instructions or ["Нет отдельных инструкций — следуй описаниям фаз и обязательным проверкам."],
            required_checks=checks or ["Нет явных checks."],
            required_evidence=evidence or ["Нет явных evidence items."],
            execution_type="parallel",
            delegate_agent=representative.agent if representative else None,
            delegate_toolsets=list(representative.toolsets) if representative else [],
            next_recommendation=f"После выполнения переходи к {next_phase or 'завершению workflow'} ({next_name or '-'}).",
            parallel_with=first.parallel_with,
            rollback_target=first.rollback_target,
            group_phases=[p.code for p in group],
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
        try:
            start_index = self.all_phases.index(start_phase)
        except ValueError:
            return [start_phase]
        group: list[Phase] = [self.all_phases[start_index]]
        for i in range(start_index + 1, len(self.all_phases)):
            if self.all_phases[i].execution_type == "parallel":
                group.append(self.all_phases[i])
            else:
                break
        return group

    def get_next_phase(self, phase_code: str) -> tuple[str | None, str | None]:
        for index, phase in enumerate(self.all_phases):
            if phase.code != phase_code:
                continue
            if index + 1 >= len(self.all_phases):
                return None, None
            nxt = self.all_phases[index + 1]
            return nxt.code, nxt.name
        return None, None

    def _next_after_group(self, group: list[Phase]) -> tuple[str | None, str | None]:
        if not group:
            return None, None
        try:
            last_index = self.all_phases.index(group[-1])
        except ValueError:
            return None, None
        if last_index + 1 >= len(self.all_phases):
            return None, None
        nxt = self.all_phases[last_index + 1]
        return nxt.code, nxt.name

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
