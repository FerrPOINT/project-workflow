"""Prompt assembly for WizardEngine phase contracts.

The prompt is stateful: it includes task history, recent verdicts, and recent
conversation messages already collected by WizardContextBuilder. This gives the
LLM (or deterministic consumer) enough context to avoid repeating failures.
"""
from __future__ import annotations

from typing import Any, Optional

from .contracts import PhaseContractBuilder


def _format_history(ctx: dict[str, Any], limit: int = 5) -> str:
    items = ctx.get("phase_history") or []
    if not items:
        return "Нет завершённых фаз."
    lines: list[str] = []
    for item in items[-limit:]:
        code = item.get("phase_code") or "-"
        name = item.get("phase_name") or ""
        status = item.get("status") or "-"
        label = f"{name} ({code})" if name else code
        lines.append(f"- {label}: {status}")
    return "\n".join(lines)


def _format_verdicts(ctx: dict[str, Any], limit: int = 3) -> str:
    items = ctx.get("recent_verdicts") or []
    if not items:
        return "Нет предыдущих вердиктов."
    lines: list[str] = []
    for item in items[:limit]:
        code = item.get("phase_code") or "-"
        verdict = item.get("verdict") or "-"
        blockers = item.get("blockers") or []
        missing = item.get("missing") or []
        parts = [f"- {code}: {verdict}"]
        if missing:
            parts.append(f"  missing: {', '.join(str(m) for m in missing[:3])}")
        if blockers:
            parts.append(f"  blockers: {', '.join(str(b) for b in blockers[:3])}")
        lines.extend(parts)
    return "\n".join(lines)


def _format_messages(ctx: dict[str, Any], limit: int = 5) -> str:
    items = ctx.get("messages") or []
    if not items:
        return "Нет сообщений."
    lines: list[str] = []
    for item in items[-limit:]:
        if isinstance(item, dict):
            role = item.get("role") or item.get("actor") or "-"
            text = item.get("content") or item.get("text") or ""
        else:
            role = getattr(item, "role", getattr(item, "actor", "-"))
            text = getattr(item, "content", getattr(item, "text", ""))
        preview = str(text).replace("\n", " ")[:120]
        lines.append(f"- {role}: {preview}")
    return "\n".join(lines)


def _format_contract(contract: dict[str, Any]) -> str:
    group_details = contract.get("group_details") or []
    if group_details:
        return _format_parallel_contract(contract, group_details)
    instructions = contract.get("instructions") or ["Нет отдельных инструкций — следуй описанию фазы и обязательным проверкам."]
    checks = contract.get("required_checks") or ["Нет явных checks."]
    evidence = contract.get("required_evidence") or ["Нет явных evidence items."]
    parts = [
        f"- Описание: {contract.get('description') or '-'}\n",
        f"- Тип выполнения: {contract.get('execution_type') or 'sync'}\n",
        f"- Параллельно с: {contract.get('parallel_with') or '-'}\n",
        f"- Rollback target: {contract.get('rollback_target') or '-'}\n",
        "Инструкции:\n" + "\n".join(f"  - {item}" for item in instructions) + "\n\n",
        "Checks:\n" + "\n".join(f"  - {item}" for item in checks) + "\n\n",
        "Evidence:\n" + "\n".join(f"  - {item}" for item in evidence) + "\n\n",
    ]
    if contract.get("delegate_agent"):
        toolsets = ", ".join(contract.get("delegate_toolsets") or [])
        parts.append(f"Делегировано агенту: {contract['delegate_agent']}" + (f" | toolsets: {toolsets}" if toolsets else "") + "\n\n")
    return "".join(parts)


def _format_parallel_contract(contract: dict[str, Any], group_details: list[dict[str, Any]]) -> str:
    parts = [
        f"- Описание группы: {contract.get('description') or '-'}\n",
        "- Тип выполнения: parallel\n",
        f"- Фазы в группе: {', '.join(contract.get('group_phases') or [])}\n",
        f"- Rollback target: {contract.get('rollback_target') or '-'}\n\n",
        "Параллельные фазы (выполняются одновременно, отчёт — одним сообщением):\n",
    ]
    for detail in group_details:
        code = detail.get("phase_code") or "-"
        name = detail.get("phase_name") or "-"
        agent = detail.get("delegate_agent") or "не задан"
        toolsets = ", ".join(detail.get("delegate_toolsets") or [])
        agent_line = f"Агент: {agent}" + (f" | toolsets: {toolsets}" if toolsets else "")
        partner = detail.get("parallel_with") or "-"
        parts.append(f"\n[{code}] {name} (параллельно с {partner})\n")
        parts.append(f"  {agent_line}\n")
        desc = detail.get("description") or "-"
        parts.append(f"  Описание: {desc}\n")
        instructions = detail.get("instructions") or []
        if instructions:
            parts.append("  Инструкции:\n" + "\n".join(f"    · {item}" for item in instructions) + "\n")
        checks = detail.get("required_checks") or []
        if checks:
            parts.append("  Checks:\n" + "\n".join(f"    · {item}" for item in checks) + "\n")
        evidence = detail.get("required_evidence") or []
        if evidence:
            parts.append("  Evidence:\n" + "\n".join(f"    · {item}" for item in evidence) + "\n")
    return "".join(parts)


def build_phase_prompt(
    task_key: str,
    phase_map: dict,
    all_phases: list,
    current_phase: str,
    ctx: dict,
    phase_id: Optional[str] = None,
) -> str:
    """Build a stateful human-readable prompt for a given phase (or current)."""
    target_phase = phase_map.get(phase_id or current_phase)
    if not target_phase:
        return f"Фаза {phase_id or current_phase} не найдена в workflow."

    cb = PhaseContractBuilder(all_phases)
    is_parallel_target = target_phase.execution_type == "parallel"
    if is_parallel_target:
        group = cb.get_parallel_group(target_phase)
        contract = cb.build_parallel(group).to_dict()
        group_codes = contract.get("group_phases") or []
        parallel_banner = (
            "ПАРАЛЛЕЛЬНАЯ ГРУППА ФАЗ\n"
            f"Выполняются одновременно: {', '.join(group_codes)}\n"
            "Отчёт по этой группе присылается ОДНИМ сообщением.\n\n"
        )
    else:
        if target_phase.code == current_phase:
            raw = ctx.get("current_contract")
            if isinstance(raw, dict):
                contract = raw
            else:
                contract = raw.to_dict() if raw else cb.build(target_phase).to_dict()
        else:
            contract = cb.build(target_phase).to_dict()
        parallel_banner = ""

    cli_actor = ctx.get("cli_actor") or {
        "description": "CLI user",
        "entrypoint": "project-workflow step --task TASK-KEY [--report TEXT]",
    }
    report_template = ctx.get("report_template") or {
        "summary": "What was achieved in this phase.",
        "completed": "Bullet list of completed contract items.",
        "evidence": "Concrete evidence produced in this phase.",
        "blockers": "Explicit blockers or 'none'.",
        "next_step": "Single next recommended action.",
    }
    # Guard against partial report_template dicts from tests.
    report_template = {
        "summary": report_template.get("summary", "What was achieved in this phase."),
        "completed": report_template.get("completed", "Bullet list of completed contract items."),
        "evidence": report_template.get("evidence", "Concrete evidence produced in this phase."),
        "blockers": report_template.get("blockers", "Explicit blockers or 'none'."),
        "next_step": report_template.get("next_step", "Single next recommended action."),
    }

    return (
        f"Задача: {task_key}\n"
        f"Workflow: {ctx.get('workflow_name') or '-'}\n"
        f"Текущий шаг: {target_phase.code} — {target_phase.name}\n"
        f"Исполнитель CLI: {cli_actor['description']}\n"
        f"CLI entrypoint: {cli_actor['entrypoint']}\n\n"
        f"{parallel_banner}"
        f"Контракт текущей фазы:\n"
        f"{_format_contract(contract)}"
        f"История выполнения:\n"
        f"{_format_history(ctx)}\n\n"
        f"Недавние вердикты:\n"
        f"{_format_verdicts(ctx)}\n\n"
        f"Недавние сообщения:\n"
        f"{_format_messages(ctx)}\n\n"
        f"Формат отчёта:\n"
        f"- summary: {report_template['summary']}\n"
        f"- completed: {report_template['completed']}\n"
        f"- evidence: {report_template['evidence']}\n"
        f"- blockers: {report_template['blockers']}\n"
        f"- next_step: {report_template['next_step']}\n"
    )
