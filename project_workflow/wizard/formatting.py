"""CLI formatting helpers for wizard evaluation results.

Public functions kept compatible for existing imports from wizard.core.
"""

from __future__ import annotations

from typing import Any


def format_result(result: dict) -> str:
    """CLI evaluate → человекочитаемый вывод.

    Основные секции: Инструкции, Чекапы, Доказательства.
    BLOCKED дополнительно показывает причину блокировки.
    PASS: показываем контракт следующей фазы со статусом pending (·).
    Не-PASS: показываем только недоделанные пункты текущей фазы.
    Для parallel групп перечисляем все фазы с агентами и параллельными партнёрами.
    """
    verdict = str(result.get("verdict", "UNKNOWN")).upper()
    covered = result.get("covered", []) or []
    covered_set = {str(i) for i in covered}
    is_pass = verdict == "PASS"

    if is_pass:
        contract = result.get("next_phase_contract") or {}
        group_details = contract.get("group_details") or []
        if group_details:
            instructions, checks, evidence = _flatten_parallel_contract(contract, set())
        else:
            instructions = list(contract.get("instructions", []) or [])
            checks = list(contract.get("required_checks", []) or [])
            evidence = list(contract.get("required_evidence", []) or [])
    else:
        group_details = result.get("group_details") or []
        if group_details:
            instructions, checks, evidence = _flatten_parallel_contract(result, covered_set)
        else:
            instructions = list(result.get("instructions", []) or [])
            checks = list(result.get("required_checks", []) or [])
            evidence = list(result.get("required_evidence", []) or [])
            missing = result.get("missing", []) or []
            checks = [c for c in checks if str(c) not in covered_set]
            evidence = [e for e in evidence if str(e) not in covered_set]
            for m in missing:
                s = str(m)
                if s not in covered_set and s not in checks and s not in evidence:
                    checks.append(s)

    lines: list[str] = []

    if is_pass and not result.get("next_phase"):
        lines.append("Workflow завершён: все фазы успешно пройдены.")

    if verdict == "BLOCKED":
        reasons = [str(item) for item in (result.get("blockers") or []) if str(item).strip()]
        message = str(result.get("message") or "").strip()
        if message and message not in reasons:
            reasons.insert(0, message)
        lines.append("Причина:")
        for reason in reasons or ["Проверка отчёта заблокирована."]:
            lines.append(f"  · {reason}")

    if verdict == "ROLLBACK":
        target = result.get("rollback_target") or result.get("next_phase")
        if target:
            instructions.insert(0, f"Вернись к шагу: {target}")
    elif verdict == "DELEGATE":
        message = str(result.get("message") or "").strip()
        instructions.insert(0, message or "Передай выполнение настроенному агенту.")

    # PASS: first instruction becomes the actionable next step.
    if is_pass:
        next_name = result.get("next_phase_name") or result.get("next_phase") or ""
        if next_name and instructions:
            instructions.insert(0, f"Перейди к шагу: {next_name}")
        elif next_name:
            instructions.insert(0, f"Перейди к шагу: {next_name}")

    if instructions:
        if lines:
            lines.append("")
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


def _flatten_parallel_contract(
    contract: dict[str, Any], covered_set: set[str]
) -> tuple[list[str], list[str], list[str]]:
    """Flatten a parallel group contract into (instructions, checks, evidence) with phase labels."""
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
            f"{name} — параллельно с {partner}, агент: {agent}" + (f" | toolsets: {toolsets}" if toolsets else "")
        )
        for item in detail.get("instructions", []) or []:
            instructions.append(f"  {item}")
        for item in detail.get("required_checks", []) or []:
            if str(item) not in covered_set:
                checks.append(f"{name}: {item}")
        for item in detail.get("required_evidence", []) or []:
            if str(item) not in covered_set:
                evidence.append(f"{name}: {item}")
    return instructions, checks, evidence
