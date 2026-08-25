"""Supervisor context builder — assembles the task dossier from PostgreSQL."""

from __future__ import annotations

from typing import Any

from .contracts import PhaseContractBuilder, phase_to_dict
from .models import Phase


class SupervisorContextBuilder:
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
    ):
        self.uow = uow
        self.task = task or {}
        self.project = project
        self.workflow = workflow
        self.all_phases = all_phases or []
        self.current_phase = current_phase
        self.task_key = task_key
        workflow_revision = str(self.workflow.get("name") or "") if self.workflow else ""
        self._contract_builder = PhaseContractBuilder(self.all_phases, workflow_revision)
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
            path.append(
                {
                    "code": phase.code,
                    "name": phase.name,
                    "status": status_lookup.get(phase.code, "pending"),
                    "parallel_with": phase.parallel_with,
                    "rollback_target": phase.rollback_target,
                }
            )
        return path

    def _build_phase_history(self) -> list[dict[str, Any]]:
        history: list[dict] = []
        for row in self.uow.get_task_history(self.task["id"]):
            phase = self._phase_by_id(row["phase_id"])
            if not phase:
                continue
            history.append(
                {
                    "phase_code": phase.code,
                    "phase_name": phase.name,
                    "status": row["status"],
                    "completed_at": row["completed_at"],
                }
            )
        return history

    def _build_recent_verdicts(self, limit: int = 5) -> list[dict[str, Any]]:
        verdicts: list[dict] = []
        for row in self.uow.get_supervisor_runs(task_id=self.task["id"], limit=limit):
            phase = self._phase_by_id(row.get("phase_id"))
            next_phase = self._phase_by_id(row.get("next_phase_id"))
            rollback_phase = self._phase_by_id(row.get("rollback_phase_id"))
            response = row.get("response") or {}
            verdicts.append(
                {
                    "phase_code": phase.code if phase else None,
                    "verdict": str(row.get("verdict") or "").upper(),
                    "blockers": row.get("blockers") or [],
                    "missing": row.get("missing") or [],
                    "message": response.get("message") if isinstance(response, dict) else None,
                    "next_phase": next_phase.code if next_phase else None,
                    "rollback_target": rollback_phase.code if rollback_phase else None,
                    "created_at": row.get("created_at"),
                }
            )
        return verdicts

    def build(self) -> dict[str, Any]:
        phase = self.phase_map.get(self.current_phase)
        workflow_path = self._build_workflow_path()
        completed_phases = [item["code"] for item in workflow_path if item["status"] == "done"]

        current_contract = (
            self._contract_builder.build(phase) if phase else self._contract_builder.build_missing(self.current_phase)
        )

        return {
            "task_key": self.task_key,
            "project_code": self.project.get("code") if self.project else None,
            "project_name": self.project.get("name") if self.project else None,
            "workflow_name": self.workflow.get("name") if self.workflow else None,
            "workflow_id": self.workflow.get("id") if self.workflow else None,
            "task_status": self.task.get("status"),
            "current_phase": self.current_phase,
            "current_phase_name": phase.name if phase else "Неизвестная фаза",
            "completed_phases": completed_phases,
            "workflow_revision": self._contract_builder.workflow_revision,
            "all_phases": [
                phase_to_dict(item, self._contract_builder.workflow_revision)
                for item in self.all_phases
            ],
            "workflow_path": workflow_path,
            "phase_history": self._build_phase_history(),
            "recent_verdicts": self._build_recent_verdicts(),
            "current_contract": current_contract.to_dict(),
            "cli_actor": self._cli_actor(),
            "report_template": self._report_template(),
            "total_phases": len(self.all_phases),
            "completed_count": len(completed_phases),
        }

    @staticmethod
    def _cli_actor() -> dict[str, Any]:
        return {
            "kind": "cli-user",
            "description": (
                "Любой пользователь или автоматизация, которая вызывает project-workflow CLI "
                "и отправляет report по текущей фазе. Supervisor не предполагает конкретную модель, "
                "OpenAI-compatible провайдера."
            ),
            "entrypoint": "project-workflow step --task RUN-42 [--report TEXT]",
        }

    @staticmethod
    def _report_template() -> dict[str, str]:
        return {
            "summary": "Что достигнуто на этой фазе.",
            "completed": "Список выполненных пунктов контракта.",
            "evidence": "Конкретные подтверждения, полученные на этой фазе.",
            "blockers": "Явные блокеры или 'нет'.",
            "next_step": "Одно рекомендуемое следующее действие.",
        }
