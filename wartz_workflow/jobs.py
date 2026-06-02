"""Job tracking для background delegated tasks."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

JOBS_DIR = Path(os.path.expanduser("~/.wartz-workflow/jobs"))


@dataclass
class Job:
    job_id: str
    jira_key: str
    phase_id: str
    agent: str
    status: str           # pending, running, complete, failed
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[str] = None
    evidence: Optional[str] = None


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def create_job(jira_key: str, phase_id: str, agent: str) -> Job:
    """Создать запись о background job."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job = Job(
        job_id=str(uuid.uuid4())[:8],
        jira_key=jira_key,
        phase_id=phase_id,
        agent=agent,
        status="pending",
        created_at=_now(),
    )
    _save_job(job)
    return job


def _save_job(job: Job) -> None:
    path = JOBS_DIR / f"{job.job_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(job), f, indent=2, ensure_ascii=False)


def load_job(job_id: str) -> Optional[Job]:
    path = JOBS_DIR / f"{job_id}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return Job(**data)


def update_job_status(job_id: str, status: str, result: Optional[str] = None) -> None:
    job = load_job(job_id)
    if not job:
        return
    job.status = status
    if status == "running" and not job.started_at:
        job.started_at = _now()
    if status in ("complete", "failed"):
        job.completed_at = _now()
    if result:
        job.result = result
    _save_job(job)


def list_jobs(jira_key: Optional[str] = None, phase_id: Optional[str] = None) -> List[Job]:
    """Список jobs, опционально отфильтрованный."""
    jobs: List[Job] = []
    for path in JOBS_DIR.glob("*.json"):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        job = Job(**data)
        if jira_key and job.jira_key != jira_key:
            continue
        if phase_id and job.phase_id != phase_id:
            continue
        jobs.append(job)
    return sorted(jobs, key=lambda j: j.created_at, reverse=True)


def get_parallel_jobs(jira_key: str) -> Dict[str, List[Job]]:
    """Получить jobs сгруппированные по phase_id для задачи."""
    jobs = list_jobs(jira_key=jira_key)
    result: Dict[str, List[Job]] = {}
    for job in jobs:
        result.setdefault(job.phase_id, []).append(job)
    return result


def is_phase_delegated(jira_key: str, phase_id: str) -> bool:
    """Проверить что для фазы уже есть job (complete или running)."""
    jobs = list_jobs(jira_key=jira_key, phase_id=phase_id)
    for job in jobs:
        if job.status in ("pending", "running", "complete"):
            return True
    return False


def render_jobs_table(jira_key: str) -> str:
    """Rich-compatible текстовое представление jobs."""
    jobs = list_jobs(jira_key=jira_key)
    if not jobs:
        return "Нет background jobs."

    lines = [f"{'Job':<10} {'Phase':<8} {'Agent':<18} {'Status':<12} {'Created'}",
             "-" * 65]
    for job in jobs:
        lines.append(f"{job.job_id:<10} {job.phase_id:<8} {job.agent:<18} {job.status:<12} {job.created_at[:10]}")
    return "\n".join(lines)
