"""Prompt assembly for SupervisorEngine phase contracts.

The prompt is stateful: it includes task history and recent verdicts from the
canonical database.
"""

from __future__ import annotations

from typing import Any

from .contracts import PhaseContractBuilder


def _format_history(ctx: dict[str, Any], limit: int = 5) -> str:
    items = ctx.get("phase_history") or []
    if not items:
        return "Нет завершённых фаз."
    lines: list[str] = []
    for item in items[-limit:]:
        code = item.get("phase_code") or "-"
        name = item.get("phase_name") or ""
        status = item.get("event_type") or "-"
        label = name if name else code
        lines.append(f"- {label}: {status}")
    return "\n".join(lines)


def _format_verdicts(ctx: dict[str, Any], limit: int = 3) -> str:
    items = ctx.get("recent_verdicts") or []
    if not items:
        return "Нет предыдущих вердиктов."
    lines: list[str] = []
    for item in items[:limit]:
        name = item.get("phase_name") or item.get("phase_code") or "-"
        verdict = item.get("verdict") or "-"
        blockers = item.get("blockers") or []
        missing = item.get("missing") or []
        parts = [f"- {name}: {verdict}"]
        if missing:
            parts.append(f"  не выполнено: {', '.join(str(m) for m in missing[:3])}")
        if blockers:
            parts.append(f"  блокеры: {', '.join(str(b) for b in blockers[:3])}")
        lines.extend(parts)
    return "\n".join(lines)


def _format_parallel_contract(contract: dict[str, Any], group_details: list[dict[str, Any]]) -> str:
    """Full parallel contract for the LLM prompt (keeps phase names and metadata)."""
    group_names = [d.get("phase_name") or d.get("phase_code") or "-" for d in group_details]
    parts = [
        f"- Описание: {contract.get('description') or '-'}\n",
        "- Тип выполнения: параллельно\n",
        f"- Фазы в группе: {', '.join(group_names)}\n",
        f"- Цель отката: {contract.get('rollback_target_phase_code') or '-'}\n\n",
        "Параллельные фазы (выполняются одновременно, отчёт — одним сообщением):\n",
    ]
    for detail in group_details:
        name = detail.get("phase_name") or detail.get("phase_code") or "-"
        agent = detail.get("delegate_agent") or "не задан"
        hermes_profile = detail.get("hermes_profile")
        agent_line = f"Агент: {agent}"
        if hermes_profile:
            agent_line += f" | профиль Hermes: {hermes_profile}"
        partner_code = detail.get("parallel_with_phase_code") or "-"
        partner = next(
            (
                d.get("phase_name") or d.get("phase_code") or partner_code
                for d in group_details
                if d.get("phase_code") == partner_code
            ),
            partner_code,
        )
        parts.append(f"\n[{name}] (параллельно с {partner})\n")
        parts.append(f"  {agent_line}\n")
        desc = detail.get("description") or "-"
        parts.append(f"  Описание: {desc}\n")
        instructions = detail.get("instructions") or []
        if instructions:
            parts.append("  Инструкции:\n" + "\n".join(f"    · {item}" for item in instructions) + "\n")
        checks = detail.get("required_checks") or []
        if checks:
            parts.append("  Чекапы:\n" + "\n".join(f"    · {item}" for item in checks) + "\n")
        evidence = detail.get("required_evidence") or []
        if evidence:
            parts.append("  Доказательства:\n" + "\n".join(f"    · {item}" for item in evidence) + "\n")
    return "".join(parts)


def _format_contract(contract: dict[str, Any], human_only: bool = False) -> str:
    group_details = contract.get("group_details") or []
    if group_details:
        if human_only:
            return _format_parallel_contract_human(group_details)
        return _format_parallel_contract(contract, group_details)
    instructions = contract.get("instructions") or [
        "Нет отдельных инструкций — следуй описанию фазы и обязательным проверкам."
    ]
    checks = contract.get("required_checks") or ["Нет явных проверок."]
    evidence = contract.get("required_evidence") or ["Нет явных подтверждений."]
    parts: list[str] = []
    if not human_only:
        execution_type = "параллельно" if contract.get("execution_type") == "parallel" else "последовательно"
        parts.extend(
            [
                f"- Описание: {contract.get('description') or '-'}\n",
                f"- Тип выполнения: {execution_type}\n",
                f"- Параллельно с: {contract.get('parallel_with_phase_code') or '-'}\n",
                f"- Цель отката: {contract.get('rollback_target_phase_code') or '-'}\n",
            ]
        )
    parts.extend(
        [
            "Инструкции:\n" + "\n".join(f"  - {item}" for item in instructions) + "\n\n",
            "Чекапы:\n" + "\n".join(f"  - {item}" for item in checks) + "\n\n",
            "Доказательства:\n" + "\n".join(f"  - {item}" for item in evidence) + "\n\n",
        ]
    )
    if contract.get("delegate_agent"):
        parts.append(
            f"Делегировано агенту: {contract['delegate_agent']}"
            + (f" | профиль Hermes: {contract['hermes_profile']}" if contract.get("hermes_profile") else "")
            + "\n\n"
        )
    return "".join(parts)


def _format_parallel_contract_human(group_details: list[dict[str, Any]]) -> str:
    """Flatten parallel group into a single concrete instruction list for CLI humans.

    Phase names are intentionally omitted — workers need actions, not abstract labels.
    """
    instructions: list[str] = []
    checks: list[str] = []
    evidence: list[str] = []
    for detail in group_details:
        agent = detail.get("delegate_agent") or "не задан"
        profile = detail.get("hermes_profile")
        agent_label = f"{agent} (профиль Hermes: {profile})" if profile else agent
        for item in detail.get("instructions", []) or []:
            instructions.append(f"[{agent_label}] {item}")
        for item in detail.get("required_checks", []) or []:
            checks.append(f"[{agent_label}] {item}")
        for item in detail.get("required_evidence", []) or []:
            evidence.append(f"[{agent_label}] {item}")

    parts = ["Инструкции:\n" + "\n".join(f"  · {item}" for item in instructions) + "\n\n"]
    if checks:
        parts.append("Чекапы:\n" + "\n".join(f"  · {item}" for item in checks) + "\n\n")
    if evidence:
        parts.append("Доказательства:\n" + "\n".join(f"  · {item}" for item in evidence) + "\n\n")
    return "".join(parts)


def build_phase_prompt(
    task_key: str,
    phase_map: dict,
    all_phases: list,
    current_phase_code: str,
    ctx: dict,
    phase_code: str | None = None,
) -> str:
    """Build a stateful human-readable prompt for a given phase (or current)."""
    target_phase = phase_map.get(phase_code or current_phase_code)
    if not target_phase:
        return f"Фаза {phase_code or current_phase_code} не найдена в воркфлоу."

    cb = PhaseContractBuilder(all_phases, str(ctx.get("workflow_revision") or ctx.get("workflow_name") or ""))
    is_parallel_target = target_phase.execution_type == "parallel"
    if is_parallel_target:
        group = cb.get_parallel_group(target_phase)
        contract = cb.build_parallel(group).to_dict()
        group_names = [getattr(p, "name", p.code) for p in group]
        parallel_banner = (
            "ПАРАЛЛЕЛЬНАЯ ГРУППА ФАЗ\n"
            f"Выполняются одновременно: {', '.join(group_names)}\n"
            "Отчёт по этой группе присылается ОДНИМ сообщением.\n\n"
        )
    else:
        if target_phase.code == current_phase_code:
            raw = ctx.get("current_contract")
            if isinstance(raw, dict):
                contract = raw
            else:
                contract = raw.to_dict() if raw else cb.build(target_phase).to_dict()
        else:
            contract = cb.build(target_phase).to_dict()
        parallel_banner = ""

    cli_actor = ctx.get("cli_actor")
    report_template = ctx.get("report_template")
    if not isinstance(cli_actor, dict) or not all(
        isinstance(cli_actor.get(key), str) and cli_actor[key].strip() for key in ("description", "entrypoint")
    ):
        raise ValueError("Контекст Supervisor не содержит полного описания CLI-исполнителя")
    if not isinstance(report_template, dict) or not all(
        isinstance(report_template.get(key), str) and report_template[key].strip()
        for key in ("summary", "completed", "evidence", "blockers", "next_step")
    ):
        raise ValueError("Контекст Supervisor не содержит полного шаблона отчёта")

    return (
        f"Задача: {task_key}\n"
        f"Воркфлоу: {ctx.get('workflow_name') or '-'}\n"
        f"Текущий шаг: {target_phase.code} — {target_phase.name}\n"
        f"Исполнитель CLI: {cli_actor['description']}\n"
        f"Команда CLI: {cli_actor['entrypoint']}\n\n"
        f"{parallel_banner}"
        f"Контракт текущей фазы:\n"
        f"{_format_contract(contract)}"
        f"История выполнения:\n"
        f"{_format_history(ctx)}\n\n"
        f"Недавние вердикты:\n"
        f"{_format_verdicts(ctx)}\n\n"
        f"Формат отчёта:\n"
        f"- summary: {report_template['summary']}\n"
        f"- completed: {report_template['completed']}\n"
        f"- evidence: {report_template['evidence']}\n"
        f"- blockers: {report_template['blockers']}\n"
        f"- next_step: {report_template['next_step']}\n"
    )


def format_current_phase_instructions(
    task_key: str,
    phase_map: dict,
    all_phases: list,
    current_phase_code: str,
    ctx: dict,
) -> str:
    """Human-only CLI output for `step --task X` without a report.

    Stripped of internal codes, boilerplate, and LLM context. Returns only
    concrete instructions, checks, and evidence the worker needs right now.
    """
    target_phase = phase_map.get(current_phase_code)
    if not target_phase:
        return f"Фаза {current_phase_code} не найдена в воркфлоу."

    cb = PhaseContractBuilder(all_phases, str(ctx.get("workflow_revision") or ctx.get("workflow_name") or ""))
    is_parallel_target = target_phase.execution_type == "parallel"
    if is_parallel_target:
        group = cb.get_parallel_group(target_phase)
        contract = cb.build_parallel(group).to_dict()
        return (
            "Выполняй следующие действия параллельно. Отчёт по ним присылай ОДНИМ сообщением.\n\n"
            + _format_parallel_contract_human(contract.get("group_details") or [])
        )

    # Serial phase
    raw = ctx.get("current_contract")
    if isinstance(raw, dict):
        contract = raw
    else:
        contract = raw.to_dict() if raw else cb.build(target_phase).to_dict()
    return f"Текущий шаг: {target_phase.name}\n\n{_format_contract(contract, human_only=True)}"
