"""Application services — use cases."""

from __future__ import annotations

from typing import Any

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import UnitOfWork
from project_workflow.domain.validation import TaskKeyValidator, get_project_for_task_key
from project_workflow.application.execution_mode import ExecutionSelection, resolve_execution_selection


class TaskService:
    """Use cases for tasks."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def create_task(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data)
        try:
            requested_workflow_id = payload.get("workflow_id")
            if requested_workflow_id is not None and (
                not isinstance(requested_workflow_id, int)
                or isinstance(requested_workflow_id, bool)
                or requested_workflow_id <= 0
            ):
                raise ValueError("workflow_id задачи должен быть положительным целым числом")
            if "project_id" not in payload or payload["project_id"] is None:
                resolved_project = get_project_for_task_key(
                    self._uow,
                    payload.get("task_key", ""),
                    workflow_id=requested_workflow_id,
                )
                if resolved_project is None:
                    raise ValueError(
                        f"Для ключа задачи {payload.get('task_key', '')!r} нет подходящего неймспейса"
                    )
                payload["project_id"] = resolved_project["id"]
            raw_project_id = payload["project_id"]
            if not isinstance(raw_project_id, int) or isinstance(raw_project_id, bool) or raw_project_id <= 0:
                raise ValueError("project_id задачи должен быть положительным целым числом")
            project_id = raw_project_id
            project = self._uow.projects.get_by_id(project_id)
            if project is None:
                raise NotFoundError(f"Неймспейс {project_id} не найден")
            if requested_workflow_id is not None and project.workflow_id != requested_workflow_id:
                raise ConflictError("Задача принадлежит другому воркфлоу")
            if self._uow.workflows.lock(project.workflow_id) is None:
                raise NotFoundError(f"Воркфлоу {project.workflow_id} не найден")
            locked_project = self._uow.projects.lock(project_id)
            if locked_project is None:
                raise NotFoundError(f"Неймспейс {project_id} не найден")
            if locked_project.workflow_id != project.workflow_id:
                raise ConflictError("Воркфлоу изменился во время создания задачи")
            payload["workflow_id"] = locked_project.workflow_id
            requested_mode_key = payload.get("mode_key")
            requested_mode_id = payload.get("mode_id")
            if requested_mode_id is not None:
                if (
                    not isinstance(requested_mode_id, int)
                    or isinstance(requested_mode_id, bool)
                    or requested_mode_id <= 0
                ):
                    raise ValueError("mode_id задачи должен быть положительным целым числом")
                mode_row = self._uow.workflows.get_mode(requested_mode_id, locked_project.workflow_id)
                if mode_row is None:
                    raise ConflictError("Указанный mode_id не принадлежит воркфлоу задачи")
                if requested_mode_key is not None and requested_mode_key != mode_row.key:
                    raise ConflictError("mode_key и mode_id указывают на разные режимы")
                requested_mode_key = mode_row.key
            selection = resolve_execution_selection(self._uow, locked_project.workflow_id,
                                                    mode_key=requested_mode_key,
                                                    cycle_number=payload.get("cycle_number"),
                                                    use_environment=False)
            payload["mode_id"] = selection.mode_id
            payload["cycle_number"] = selection.cycle_number
            raw_task_key = payload.get("task_key")
            if not isinstance(raw_task_key, str) or not raw_task_key.strip():
                raise ValueError("task_key должен быть непустой строкой")
            task_key = raw_task_key.strip()
            validated_key = TaskKeyValidator.from_projects([]).validate(task_key)
            if not validated_key.is_valid:
                raise ConflictError(validated_key.error_message or f"Недопустимый ключ задачи {task_key!r}")
            task_key = validated_key.normalized or task_key
            payload["task_key"] = task_key
            phases = list(self._uow.phases.list(workflow_id=locked_project.workflow_id, mode_id=selection.mode_id))
            if not phases:
                raise ValueError(f"Воркфлоу {locked_project.workflow_id} не содержит фаз")
            raw_current_phase_id = payload.get("current_phase_id")
            if raw_current_phase_id is None:
                current_phase_id = phases[0].id
            elif (
                not isinstance(raw_current_phase_id, int)
                or isinstance(raw_current_phase_id, bool)
                or raw_current_phase_id <= 0
            ):
                raise ValueError("current_phase_id должен быть положительным целым числом")
            else:
                current_phase_id = raw_current_phase_id
            if current_phase_id is None or not any(phase.id == current_phase_id for phase in phases):
                raise ValueError(
                    f"Фаза {current_phase_id!r} не найдена в режиме {selection.mode_key!r}"
                )
            payload["current_phase_id"] = current_phase_id
            if self._uow.tasks.get_by_key(task_key, project_id=locked_project.id) is not None:
                raise ConflictError(f"Задача {task_key!r} уже существует")
            tid = self._uow.tasks.create(payload)
            task = self._uow.tasks.get_by_id(tid)
            if not task:
                raise RuntimeError("Не удалось создать задачу")
            self._uow.commit()
            return task.to_dict()
        except Exception:
            self._uow.rollback()
            raise

    def prepare_runtime_assignment(
        self, task: dict[str, Any], selection: ExecutionSelection
    ) -> dict[str, Any]:
        """Apply a Business-selected mode/cycle to an existing terminal task.

        This is deliberately a private runtime path: ordinary task/API creation
        remains default-mode based.  A task may move to a strictly newer cycle
        only after its previous execution is terminal; active or stale work is
        rejected and its history remains untouched.
        """
        task_id = task.get("id")
        workflow_id = task.get("workflow_id")
        if not isinstance(task_id, int) or not isinstance(workflow_id, int):
            raise ConflictError("У задачи отсутствует корректная runtime-идентичность")
        locked = self._uow.tasks.lock(task_id)
        if locked is None or locked.workflow_id != workflow_id:
            raise ConflictError("Задача исчезла или сменила воркфлоу во время runtime assignment")
        current_mode_id = int(locked.mode_id or 0)
        current_cycle = int(locked.cycle_number or 0)
        if current_mode_id == selection.mode_id and current_cycle == selection.cycle_number:
            return locked.to_dict()
        if locked.status != "done":
            raise ConflictError("Нельзя сменить режим или цикл активной задачи")
        if selection.cycle_number <= current_cycle:
            raise ConflictError("Runtime cycle должен быть строго новее завершённого цикла")
        phases = list(self._uow.phases.list(workflow_id=workflow_id, mode_id=selection.mode_id))
        if not phases or phases[0].id is None:
            raise ConflictError(f"Режим {selection.mode_key!r} не содержит начальной фазы")
        self._uow.tasks.update(
            task_id,
            {
                "mode_id": selection.mode_id,
                "cycle_number": selection.cycle_number,
                "current_phase_id": phases[0].id,
                "status": "active",
            },
        )
        self._uow.tasks.record_phase_event(task_id, int(phases[0].id), "entered")
        return self._uow.tasks.get_by_id(task_id).to_dict()  # type: ignore[union-attr]

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        t = self._uow.tasks.get_by_id(task_id)
        return t.to_dict() if t else None

    def get_task_by_key(
        self,
        task_key: str,
        workflow_id: int | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any] | None:
        t = self._uow.tasks.get_by_key(task_key, workflow_id=workflow_id, project_id=project_id)
        return t.to_dict() if t else None

    def list_tasks(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self._uow.tasks.list()]

__all__ = ["TaskService"]
