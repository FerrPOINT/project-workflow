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
        current_phase_code: str = "",
        task_key: str = "",
    ):
        self.uow = uow
        self.task = task or {}
        self.project = project
        self.workflow = workflow
        self.all_phases = all_phases or []
        self.current_phase_code = current_phase_code
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
        event_status = {
            "entered": "current",
            "completed": "done",
            "blocked": "blocked",
            "resumed": "current",
            "rolled_back": "rollback",
        }
        events = self.uow.list_phase_events(self.task["id"])
        if not events:
            raise ValueError("Для задачи отсутствует обязательный журнал событий фаз")
        for row in events:
            phase = self._phase_by_id(row["phase_id"])
            if phase is None:
                raise ValueError(f"Событие ссылается на неизвестную фазу {row['phase_id']}")
            statuses[phase.code] = event_status[str(row["event_type"])]
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
                    "parallel_with_phase_code": phase.parallel_with_phase_code,
                    "rollback_target_phase_code": phase.rollback_target_phase_code,
                }
            )
        return path

    def _build_phase_history(self) -> list[dict[str, Any]]:
        history: list[dict] = []
        for row in self.uow.list_phase_events(self.task["id"]):
            phase = self._phase_by_id(row["phase_id"])
            if not phase:
                raise ValueError(f"Событие ссылается на неизвестную фазу {row['phase_id']}")
            history.append(
                {
                    "phase_code": phase.code,
                    "phase_name": phase.name,
                    "event_type": row["event_type"],
                    "occurred_at": row["occurred_at"],
                    "step_history_id": row.get("step_history_id"),
                }
            )
        return history

    def _build_recent_verdicts(self, limit: int = 5) -> list[dict[str, Any]]:
        verdicts: list[dict] = []
        for row in self.uow.list_step_history(task_id=self.task["id"], limit=limit):
            phase = self._phase_by_id(row.get("phase_id"))
            next_phase = self._phase_by_id(row.get("next_phase_id"))
            rollback_phase = self._phase_by_id(row.get("rollback_phase_id"))
            response = row.get("supervisor_response") or {}
            verdicts.append(
                {
                    "phase_code": phase.code if phase else None,
                    "verdict": str(row.get("verdict") or "").upper(),
                    "blockers": row.get("blocker_messages") or [],
                    "missing": row.get("missing_item_ids") or [],
                    "message": response.get("message") if isinstance(response, dict) else None,
                    "next_phase_code": next_phase.code if next_phase else None,
                    "rollback_phase_code": rollback_phase.code if rollback_phase else None,
                    "created_at": row.get("created_at"),
                }
            )
        return verdicts

    def build(self) -> dict[str, Any]:
        phase = self.phase_map.get(self.current_phase_code)
        if phase is None:
            raise ValueError("Текущая фаза задачи отсутствует в каталоге воркфлоу")
        workflow_path = self._build_workflow_path()
        completed_phases = [item["code"] for item in workflow_path if item["status"] == "done"]

        current_contract = (
            self._contract_builder.build(phase)
        )

        return {
            "task_key": self.task_key,
            "namespace_code": self.project.get("code") if self.project else None,
            "namespace_name": self.project.get("name") if self.project else None,
            "namespace_id": self.project.get("id") if self.project else None,
            "namespace_cli_command": self.project.get("cli_command") if self.project else None,
            "context_code": self.project.get("code") if self.project else None,
            "context_name": self.project.get("name") if self.project else None,
            "context_id": self.project.get("id") if self.project else None,
            "project_code": self.project.get("code") if self.project else None,
            "project_name": self.project.get("name") if self.project else None,
            "project_id": self.project.get("id") if self.project else None,
            "workflow_name": self.workflow.get("name") if self.workflow else None,
            "workflow_id": self.workflow.get("id") if self.workflow else None,
            "task_status": self.task.get("status"),
            "current_phase_code": self.current_phase_code,
            "current_phase_name": phase.name,
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

    def _cli_actor(self) -> dict[str, Any]:
        cli_command = str((self.project or {}).get("cli_command") or "project-workflow").strip()
        return {
            "kind": "cli-user",
            "description": (
                "Любой пользователь или автоматизация, которая вызывает эту CLI-команду "
                "и отправляет report по текущей фазе. Supervisor не предполагает конкретную модель, "
                "OpenAI-compatible провайдера."
            ),
            "entrypoint": f"{cli_command} step --task {self.task_key} [--report TEXT]",
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
