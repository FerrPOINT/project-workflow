"""Prompt assembly for WizardEngine phase contracts."""
from __future__ import annotations

from typing import Optional

from .wizard_contracts import PhaseContractBuilder


def build_phase_prompt(
    task_key: str,
    phase_map: dict,
    all_phases: list,
    current_phase: str,
    ctx: dict,
    phase_id: Optional[str] = None,
) -> str:
    """Build human-readable prompt for a given phase (or current)."""
    target_phase = phase_map.get(phase_id or current_phase)
    if not target_phase:
        return f"Фаза {phase_id or current_phase} не найдена в workflow."

    cb = PhaseContractBuilder(all_phases)
    is_parallel_target = target_phase.execution_type == "parallel"
    if is_parallel_target:
        group = cb.get_parallel_group(target_phase)
        contract = cb.build_parallel(group).to_dict()
        parallel_banner = (
            "\n⚡ ПАРАЛЛЕЛЬНАЯ ГРУППА ФАЗ\n"
            f"Выполняются одновременно: {', '.join(contract.get('group_phases') or [])}\n"
            f"Отчёт по этой группе присылается ОДНИМ сообщением.\n"
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

    instructions = contract.get("instructions") or ["Нет отдельных инструкций — следуй описанию фазы и обязательным проверкам."]
    checks = contract.get("required_checks") or ["Нет явных checks."]
    evidence = contract.get("required_evidence") or ["Нет явных evidence items."]
    cli_actor = ctx.get("cli_actor") or {
        "description": "CLI user",
        "entrypoint": "wartz-workflow step --task TASK-KEY [--report TEXT]",
    }

    delegated = ""
    if contract.get("delegate_agent"):
        delegated = (
            f"\nДелегировано агенту: {contract['delegate_agent']}"
            + (f" | toolsets: {', '.join(contract['delegate_toolsets'])}" if contract.get("delegate_toolsets") else "")
        )

    return (
        f"Задача: {task_key}\n"
        f"Workflow: {ctx['workflow_name'] or '-'}\n"
        f"Текущий шаг: {target_phase.code} — {target_phase.name}\n"
        f"Исполнитель CLI: {cli_actor['description']}\n"
        f"CLI entrypoint: {cli_actor['entrypoint']}\n\n"
        f"Контракт текущей фазы:\n"
        f"- Описание: {contract.get('description') or '-'}\n"
        f"- Тип выполнения: {contract.get('execution_type')}\n"
        f"- Параллельно с: {contract.get('parallel_with') or '-'}\n"
        f"- Rollback target: {contract.get('rollback_target') or '-'}\n"
        f"- Next recommendation: {contract.get('next_recommendation') or '-'}"
        f"{delegated}\n"
        f"{parallel_banner}\n"
        f"Инструкции:\n" + "\n".join(f"- {item}" for item in instructions) + "\n\n"
        "Checks:\n" + "\n".join(f"- {item}" for item in checks) + "\n\n"
        "Evidence:\n" + "\n".join(f"- {item}" for item in evidence) + "\n\n"
    )
