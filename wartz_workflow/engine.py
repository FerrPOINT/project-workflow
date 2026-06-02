"""Workflow Engine — исполняет декларативные фазы из YAML-схемы + генерирует delegate payloads."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from . import jira_gitlab, schema, state, profiles, jobs
from .schema import Phase, PhaseCheck


def run_checks(repo: str, phase: Phase, context: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]]]:
    """Выполнить все checks для фазы. Возвращает (all_ok, results)."""
    results: List[Dict[str, Any]] = []
    all_ok = True

    for check in phase.checks:
        ok, detail = _run_single_check(repo, check, context)
        results.append({
            "check": check.type,
            "description": check.description,
            "ok": ok,
            "detail": detail,
            "optional": check.optional,
        })
        if not ok and not check.optional:
            all_ok = False

    return all_ok, results


def _run_single_check(repo: str, check: PhaseCheck, context: Dict[str, Any]) -> Tuple[bool, str]:
    """Выполнить одну проверку."""
    # Подставить переменные
    cmd = check.command or ""
    for key, val in context.items():
        cmd = cmd.replace(f"{{{key}}}", str(val))

    path = check.path or ""
    for key, val in context.items():
        path = path.replace(f"{{{key}}}", str(val))

    if check.type == "file_exists":
        target = os.path.join(repo, path) if path else ""
        ok = os.path.isfile(target)
        return ok, f"{'Found' if ok else 'Missing'}: {target}"

    if check.type == "dir_exists":
        target = os.path.join(repo, path) if path else ""
        ok = os.path.isdir(target)
        return ok, f"{'Found' if ok else 'Missing'}: {target}"

    if check.type == "script_pass":
        if not cmd:
            return True, "No command"
        result = subprocess.run(
            cmd, shell=True, cwd=repo, capture_output=True, text=True, timeout=60
        )
        ok = result.returncode == 0
        return ok, f"exit={result.returncode}, out={result.stdout[:200]}"

    if check.type == "env_var":
        missing = []
        for var in (check.expected or []):
            if not os.environ.get(var):
                missing.append(var)
        ok = not missing
        return ok, f"Missing: {missing}" if missing else "All present"

    if check.type == "jira_status":
        from .jira_gitlab import get_jira_status
        status = get_jira_status(context.get("jira_key", ""))
        expected = check.expected or []
        ok = status in expected if status else False
        return ok, f"Status={status}, expected={expected}"

    if check.type == "api_ping":
        if "jira" in check.description.lower():
            ok, detail = jira_gitlab.ping_jira()
            return ok, detail
        if "gitlab" in check.description.lower():
            ok, detail = jira_gitlab.ping_gitlab()
            return ok, detail
        return False, "Unknown API"

    if check.type == "git_branch":
        result = subprocess.run(
            ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True
        )
        branch = result.stdout.strip()
        ok = bool(branch) and "TASKNEIROKLYUCH" in branch
        return ok, f"Branch: {branch}"

    if check.type == "git_commit":
        result = subprocess.run(
            ["git", "log", "-1", "--oneline"], cwd=repo, capture_output=True, text=True
        )
        commit = result.stdout.strip()
        task_id = context.get("task_id", "")
        ok = task_id in commit if task_id else bool(commit)
        return ok, f"Commit: {commit}"

    if check.type == "git_sync":
        result = subprocess.run(
            ["git", "pull", "origin", "develop"], cwd=repo, capture_output=True, text=True
        )
        ok = "Already up to date" in result.stdout or result.returncode == 0
        return ok, f"Pull: {result.stdout[:100]}"

    if check.type == "gate_passed":
        # Проверяем state на наличие evidence от CriticGate
        jira_key = context.get("jira_key", "")
        repo_path = context.get("repo", "")
        st = state.load_state(repo_path, jira_key) if repo_path else None
        last_ev = st.get("last_evidence", "") if st else ""
        ok = "PASS" in last_ev.upper()
        return ok, f"Last evidence: {last_ev}"

    if check.type == "gitlab_mr":
        task_id = context.get("task_id", "")
        mr = jira_gitlab.get_mr_state(task_id) if task_id else None
        ok = mr is not None and mr.get("state") in ["opened", "merged"]
        return ok, f"MR: {mr}"

    return True, f"Unknown check type: {check.type}"


def build_context(repo: str, jira_key: str, task_id: str, sprint: str) -> Dict[str, Any]:
    """Собрать контекст для подстановки в шаблоны."""
    return {
        "repo": repo,
        "jira_key": jira_key,
        "task_id": task_id,
        "sprint": sprint,
        "jira_url": "https://task.wemakedev.ru",
        "gitlab_url": "https://gt.wmtgroup.ru",
        "verify_suite_script": os.path.expanduser(
            "~/.hermes/skills/software-development/hr-recruiter-workflow-suite/scripts/verify-suite.sh"
        ),
    }


def render_phase_playbook(phase: Phase, context: Dict[str, Any]) -> Dict[str, Any]:
    """Сгенерировать 'playbook' для фазы — что агенту делать."""
    instructions = phase.render_instructions(context)

    # Делегированная фаза — добавить delegate инструкции
    delegate_prompt = None
    if phase.delegate:
        d = phase.delegate
        delegate_prompt = d.prompt_template
        for key, val in context.items():
            delegate_prompt = delegate_prompt.replace(f"{{{key}}}", str(val))

    return {
        "phase_id": phase.id,
        "phase_name": phase.name,
        "description": phase.description,
        "is_blocker": phase.is_blocker,
        "is_delegated": phase.is_delegated,
        "is_critic": phase.is_critic,
        "min_time_min": phase.min_time_min,
        "instructions": instructions,
        "evidence_required": [e.item for e in phase.evidence],
        "checks": [{"type": c.type, "desc": c.description, "optional": c.optional} for c in phase.checks],
        "delegate": {
            "agent": phase.delegate.agent,
            "prompt": delegate_prompt,
            "toolsets": phase.delegate.toolsets,
            "timeout_min": phase.delegate.timeout_min,
        } if phase.delegate else None,
        "skills": phase.skills,
        "next_recommendation": phase.next_recommendation,
        "parallel_with": phase.parallel_with,
    }


def execute_phase(repo: str, jira_key: str, phase_id: str) -> Tuple[bool, Dict[str, Any]]:
    """Полный цикл выполнения фазы: checks → playbook → delegate payload → job tracking."""
    phase = schema.get_phase(phase_id)
    if not phase:
        return False, {"error": f"Unknown phase: {phase_id}"}

    st = state.load_state(repo, jira_key)
    if not st:
        return False, {"error": "Task not initialized"}

    ctx = build_context(repo, jira_key, st.get("task_id", ""), st.get("sprint", ""))

    # 1. Run checks
    checks_ok, check_results = run_checks(repo, phase, ctx)

    # 2. Generate playbook
    playbook = render_phase_playbook(phase, ctx)

    # 3. For delegated phases — generate delegate payload + create job
    delegate_payload = None
    job = None
    if phase.is_delegated and phase.delegate:
        delegate_payload = profiles.build_delegate_payload(
            phase_id, jira_key, st.get("task_id", ""), st.get("title", "")
        )
        # Create job tracking record
        if delegate_payload:
            job = jobs.create_job(jira_key, phase_id, delegate_payload["agent"])

    # 4. If checks passed and not delegated — mark complete
    if checks_ok and not phase.is_delegated:
        state.mark_phase_complete(repo, jira_key, phase_id, f"checks passed, playbook executed")

    return checks_ok, {
        "phase": phase_id,
        "phase_name": phase.name,
        "checks_ok": checks_ok,
        "check_results": check_results,
        "playbook": playbook,
        "is_complete": checks_ok and not phase.is_delegated,
        "is_delegated": phase.is_delegated,
        "delegate_payload": delegate_payload,
        "job_id": job.job_id if job else None,
    }


def get_parallel_phases(phase_id: str) -> List[str]:
    """Найти фазы которые можно запускать параллельно с данной."""
    phase = schema.get_phase(phase_id)
    if not phase:
        return []

    result = []
    if phase.parallel_with:
        result.append(phase.parallel_with)

    # Reverse: кто параллелен мне
    for p in schema.load_phases():
        if p.parallel_with == phase_id:
            result.append(p.id)

    return list(dict.fromkeys(result))


def get_delegate_command(phase_id: str, jira_key: str, task_id: str, title: str) -> Optional[Dict[str, Any]]:
    """Сгенерировать готовую команду delegate_task для агента."""
    payload = profiles.build_delegate_payload(phase_id, jira_key, task_id, title)
    if not payload:
        return None

    return {
        "tool": "delegate_task",
        "role": payload.get("role", "leaf"),
        "goal": payload.get("goal", ""),
        "context": payload.get("context", ""),
        "toolsets": payload.get("toolsets", []),
    }

