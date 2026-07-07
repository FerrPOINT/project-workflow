"""Persona adapter — formats wizard results in the user's preferred style.

Rules:
- No emojis.
- No "All checks passed" / "You can proceed" / internal phase codes.
- Three sections only: Инструкции, Чекапы, Доказательства.
- PASS → show next phase contract items with pending markers (·).
- PARTIAL/SOFT_FAIL → "Ты сделал часть, доделай:" + not-done items.
- BLOCKED/HARD_FAIL → explicit blocker + what to fix.
- Always end with one actionable next step.
"""
from __future__ import annotations

from typing import Any


def _to_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None and str(v).strip() != ""]
    return [str(value)]


class PersonaAdapter:
    """Convert an evaluate result dict into user-aligned plain text."""

    @staticmethod
    def format(result: dict[str, Any]) -> str:
        verdict = str(result.get("verdict", "")).upper()
        covered = {str(c) for c in result.get("covered", []) or []}
        missing = _to_str_list(result.get("missing"))
        blockers = _to_str_list(result.get("blockers"))
        is_pass = verdict == "PASS"
        is_partial = verdict in {"PARTIAL", "SOFT_FAIL"}

        lines: list[str] = []

        if is_partial:
            lines.append("Ты сделал часть, доделай:")
            instructions, checks, evidence = PersonaAdapter._not_done_items(
                result, covered, missing
            )
        elif is_pass:
            instructions, checks, evidence = PersonaAdapter._next_phase_items(result)
            next_name = result.get("next_phase_name") or result.get("next_phase") or ""
            if next_name:
                instructions.insert(0, f"Перейди к шагу: {next_name}")
        else:
            instructions, checks, evidence = PersonaAdapter._not_done_items(
                result, covered, missing
            )
            if blockers:
                instructions.insert(0, f"Блокер: {blockers[0]}")
            if missing and not blockers:
                instructions.insert(0, f"Недостаёт: {missing[0]}")

        if instructions:
            lines.append("Инструкции:")
            for item in instructions:
                lines.append(f"  · {item}")

        if checks:
            lines.append("")
            lines.append("Чекапы:")
            for item in checks:
                lines.append(f"  · {item}")

        if evidence:
            lines.append("")
            lines.append("Доказательства:")
            for item in evidence:
                lines.append(f"  · {item}")

        return "\n".join(lines)

    @staticmethod
    def _next_phase_items(result: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
        contract = result.get("next_phase_contract") or {}
        group_details = contract.get("group_details") or []
        if group_details:
            return PersonaAdapter._flatten_parallel(contract, set())
        instructions = list(contract.get("instructions", []) or [])
        checks = list(contract.get("required_checks", []) or [])
        evidence = list(contract.get("required_evidence", []) or [])
        return instructions, checks, evidence

    @staticmethod
    def _not_done_items(
        result: dict[str, Any], covered: set[str], missing: list[str]
    ) -> tuple[list[str], list[str], list[str]]:
        group_details = result.get("group_details") or []
        if group_details:
            return PersonaAdapter._flatten_parallel(result, covered)
        instructions = list(result.get("instructions", []) or [])
        checks = [str(c) for c in result.get("required_checks", []) or [] if str(c) not in covered]
        evidence = [str(e) for e in result.get("required_evidence", []) or [] if str(e) not in covered]
        for m in missing:
            s = str(m)
            if s not in covered and s not in checks and s not in evidence:
                checks.append(s)
        return instructions, checks, evidence

    @staticmethod
    def _flatten_parallel(
        contract: dict[str, Any], covered: set[str]
    ) -> tuple[list[str], list[str], list[str]]:
        instructions: list[str] = []
        checks: list[str] = []
        evidence: list[str] = []
        group_details = contract.get("group_details") or []
        group_names = [d.get("phase_name") or d.get("phase_code") or "-" for d in group_details]
        if group_names:
            instructions.append(
                f"Параллельная группа фаз: {', '.join(group_names)} — выполняются одновременно, отчёт одним сообщением"
            )
        for detail in group_details:
            name = detail.get("phase_name") or detail.get("phase_code") or "-"
            agent = detail.get("delegate_agent") or "не задан"
            toolsets = ", ".join(detail.get("delegate_toolsets") or [])
            partner_code = detail.get("parallel_with") or "-"
            partner = next(
                (
                    d.get("phase_name") or d.get("phase_code") or partner_code
                    for d in group_details
                    if d.get("phase_code") == partner_code
                ),
                partner_code,
            )
            instructions.append(
                f"{name} — параллельно с {partner}, агент: {agent}"
                + (f" | toolsets: {toolsets}" if toolsets else "")
            )
            for item in detail.get("instructions", []) or []:
                instructions.append(f"  {item}")
            for item in detail.get("required_checks", []) or []:
                s = str(item)
                if s not in covered:
                    checks.append(f"{name}: {s}")
            for item in detail.get("required_evidence", []) or []:
                s = str(item)
                if s not in covered:
                    evidence.append(f"{name}: {s}")
        return instructions, checks, evidence
