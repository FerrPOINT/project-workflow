"""Wizard context builder — assembles task dossier from DB + artifacts."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from ..infrastructure import conversation as convo

from .models import Phase
from .types import ArtifactSnapshot
from .contracts import PhaseContractBuilder, phase_to_dict

logger = logging.getLogger(__name__)


class WizardContextBuilder:
    """Collects unified task dossier: metadata, phase history, recent verdicts, contract, artifacts."""

    def __init__(
        self,
        uow: Any = None,
        task: dict[str, Any] | None = None,
        project: dict[str, Any] | None = None,
        workflow: dict[str, Any] | None = None,
        all_phases: list[Phase] | None = None,
        current_phase: str = "",
        task_key: str = "",
        repo: Optional[str] = None,
        db: Any = None,
    ):
        if uow is None and db is not None:
            uow = db
        self.uow = uow
        self.task = task or {}
        self.project = project
        self.workflow = workflow
        self.all_phases = all_phases or []
        self.current_phase = current_phase
        self.task_key = task_key
        self.repo = repo
        self._contract_builder = PhaseContractBuilder(self.all_phases)
        self._phase_map: dict[str, Phase] | None = None

    @property
    def phase_map(self) -> dict[str, Phase]:
        if self._phase_map is None:
            self._phase_map = {phase.code: phase for phase in self.all_phases}
        return self._phase_map

    def _phase_by_id(self, phase_id: int | str | None) -> Phase | None:
        if phase_id is None:
            return None
        needle = int(phase_id)
        for phase in self.all_phases:
            if phase.id is not None and int(phase.id) == needle:
                return phase
        return None

    def _phase_status_lookup(self) -> dict[str, str]:
        statuses: dict[str, str] = {}
        for row in self.uow.get_task_history(self.task["id"]):
            phase = self._phase_by_id(row["phase_id"])
            if phase:
                statuses[phase.code] = str(row["status"])
        current_phase = str(self.task.get("current_phase") or self.current_phase)
        if current_phase in self.phase_map and current_phase not in statuses and self.task.get("status") != "done":
            statuses[current_phase] = "current"
        return statuses

    def _build_workflow_path(self) -> list[dict[str, Any]]:
        status_lookup = self._phase_status_lookup()
        path: list[dict] = []
        for phase in self.all_phases:
            path.append({
                "code": phase.code,
                "name": phase.name,
                "status": status_lookup.get(phase.code, "pending"),
                "parallel_with": phase.parallel_with,
                "rollback_target": phase.rollback_target,
            })
        return path

    def _build_phase_history(self) -> list[dict[str, Any]]:
        history: list[dict] = []
        for row in self.uow.get_task_history(self.task["id"]):
            phase = self._phase_by_id(row["phase_id"])
            if not phase:
                continue
            history.append({
                "phase_code": phase.code,
                "phase_name": phase.name,
                "status": row["status"],
                "completed_at": row["completed_at"],
            })
        return history

    def _build_recent_verdicts(self, limit: int = 5) -> list[dict[str, Any]]:
        verdicts: list[dict] = []
        for row in self.uow.get_supervisor_runs(task_id=self.task["id"], limit=limit):
            if isinstance(row, dict):
                verdicts.append({
                    "phase_code": row.get("phase_code"),
                    "verdict": str(row.get("verdict") or "").upper(),
                    "blockers": row.get("blockers") or [],
                    "missing": row.get("missing") or [],
                    "next_phase": row.get("next_phase_code"),
                    "rollback_target": row.get("rollback_phase_code"),
                    "created_at": row.get("created_at"),
                })
            else:
                verdicts.append({
                    "phase_code": row.phase_code,
                    "verdict": str(row.verdict or "").upper(),
                    "blockers": row.blockers or [],
                    "missing": row.missing or [],
                    "next_phase": row.next_phase_code,
                    "rollback_target": row.rollback_phase_code,
                    "created_at": row.created_at,
                })
        return verdicts

    def _artifact_dir(self) -> Path | None:
        project_code = self.project.get("code") if self.project else None
        if not project_code:
            return None
        return Path.home() / ".project-workflow" / "tasks" / project_code / self.task_key

    def _scan_artifacts(self) -> list[ArtifactSnapshot]:
        """Check existence and freshness of known task artifacts."""
        artifact_dir = self._artifact_dir()
        if not artifact_dir:
            return []
        known_files = [
            "progress.json",
            "requirements.md",
            "current-stage.md",
            "changelog.md",
            "test-cases.md",
        ]
        snapshots: list[ArtifactSnapshot] = []
        for name in known_files:
            path = artifact_dir / name
            if path.exists():
                stat = path.stat()
                snapshots.append(ArtifactSnapshot(
                    path=str(path),
                    exists=True,
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                ))
            else:
                snapshots.append(ArtifactSnapshot(
                    path=str(path),
                    exists=False,
                ))
        return snapshots

    def build(self) -> dict[str, Any]:
        phase = self.phase_map.get(self.current_phase)
        workflow_path = self._build_workflow_path()
        completed_phases = [item["code"] for item in workflow_path if item["status"] == "done"]

        messages = []
        try:
            messages = convo.get_messages(self.task_key, limit=20)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Failed to load conversation messages: %s", exc)
            messages = []

        current_contract = self._contract_builder.build(phase) if phase else self._contract_builder.build_missing(self.current_phase)

        return {
            "task_key": self.task_key,
            "repo": self.repo,
            "project_code": self.project.get("code") if self.project else None,
            "project_name": self.project.get("name") if self.project else None,
            "workflow_name": self.workflow.get("name") if self.workflow else None,
            "workflow_id": self.workflow.get("id") if self.workflow else None,
            "task_status": self.task.get("status"),
            "current_phase": self.current_phase,
            "current_phase_name": phase.name if phase else "Unknown phase",
            "completed_phases": completed_phases,
            "all_phases": [phase_to_dict(item) for item in self.all_phases],
            "workflow_path": workflow_path,
            "phase_history": self._build_phase_history(),
            "recent_verdicts": self._build_recent_verdicts(),
            "current_contract": current_contract.to_dict(),
            "cli_actor": self._cli_actor(),
            "global_instructions": self._global_instructions(),
            "report_template": self._report_template(),
            "messages": messages,
            "total_phases": len(self.all_phases),
            "completed_count": len(completed_phases),
            "artifact_snapshots": [a.__dict__ for a in self._scan_artifacts()],
        }

    @staticmethod
    def _global_instructions() -> list[str]:
        return [
            "Do not skip phases or invent completed evidence.",
            "Evaluate progress strictly against the current phase contract from the DB phase catalog.",
            "Treat the CLI actor as the source of the report whether it is a human user or automation; do not assume a specific model/provider.",
            "Return a structured phase report with summary, completed items, evidence, blockers, and next step.",
            "If the phase is blocked, say exactly which checks/evidence are missing and whether rollback is required.",
        ]

    @staticmethod
    def _cli_actor() -> dict[str, Any]:
        return {
            "kind": "cli-user",
            "description": (
                "Любой пользователь или автоматизация, которая вызывает project-workflow CLI "
                "и отправляет report по текущей фазе. Supervisor не предполагает конкретную модель, "
                "Ollama или другого провайдера."
            ),
            "entrypoint": "project-workflow step --task TASK-KEY [--report TEXT]",
        }

    @staticmethod
    def _report_template() -> dict[str, str]:
        return {
            "summary": "What was achieved in this phase.",
            "completed": "Bullet list of completed contract items.",
            "evidence": "Concrete evidence produced in this phase.",
            "blockers": "Explicit blockers or 'none'.",
            "next_step": "Single next recommended action.",
        }
