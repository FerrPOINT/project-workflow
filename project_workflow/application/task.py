"""Application services — use cases."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import UnitOfWork
from project_workflow.domain.validation import TaskKeyValidator, get_project_for_task_key
from project_workflow.application.execution_mode import resolve_execution_selection


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
            # Mode/cycle are adapter-owned. Ordinary UI/repository creation has
            # one compatibility meaning: the workflow's default mode, cycle 0.
            payload.pop("mode_key", None)
            payload.pop("mode_id", None)
            payload.pop("cycle_number", None)
            payload.pop("assignment_operation_key", None)
            payload.pop("assignment_revision", None)
            selection = resolve_execution_selection(self._uow, locked_project.workflow_id)
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

    def assign_runtime_task(
        self,
        *,
        project_id: int,
        task_key: str,
        mode_key: str,
        cycle_number: int,
        operation_key: str,
        expected_revision: int,
        expected_status: str,
        expected_mode_key: str | None = None,
        expected_cycle_number: int | None = None,
    ) -> dict[str, Any]:
        """Persist one authorized Business assignment atomically and idempotently."""
        project = self._uow.projects.lock(project_id)
        if project is None or project.workflow_id is None:
            raise NotFoundError(f"Неймспейс {project_id} не найден")
        operation_key = operation_key.strip()
        mode_key = mode_key.strip()
        if not operation_key or len(operation_key) > 128:
            raise ValueError("operation_key должен быть непустой строкой длиной до 128 символов")
        if not mode_key or len(mode_key) > 128:
            raise ValueError("mode_key должен быть непустой строкой длиной до 128 символов")
        validated_key = TaskKeyValidator.from_projects([]).validate(task_key)
        if not validated_key.is_valid:
            raise ConflictError(validated_key.error_message or f"Недопустимый ключ задачи {task_key!r}")
        task_key = validated_key.normalized or task_key
        mode = self._uow.workflows.get_mode_by_key(project.workflow_id, mode_key)
        if mode is None or mode.id is None:
            raise ConflictError(f"Режим {mode_key!r} не найден в воркфлоу {project.workflow_id}")
        if cycle_number < 0 or expected_revision < 0:
            raise ValueError("cycle_number и expected_revision должны быть неотрицательными")
        phases = list(self._uow.phases.list(workflow_id=project.workflow_id, mode_id=mode.id))
        if not phases or phases[0].id is None:
            raise ConflictError(f"Режим {mode_key!r} не содержит начальной фазы")
        current = self._uow.tasks.get_by_key(task_key, project_id=project_id)
        if current is None:
            if expected_status != "missing" or expected_revision != 0:
                raise ConflictError("Ожидаемое состояние отсутствующей задачи не совпадает")
            if cycle_number != 0:
                raise ConflictError("Начальный Business assignment должен иметь cycle_number=0")
            tid = self._uow.tasks.create(
                {
                    "project_id": project_id,
                    "workflow_id": project.workflow_id,
                    "mode_id": mode.id,
                    "mode_key": mode.key,
                    "cycle_number": cycle_number,
                    "assignment_operation_key": operation_key,
                    "assignment_revision": 1,
                    "task_key": task_key,
                    "title": task_key,
                    "current_phase_id": phases[0].id,
                    "status": "active",
                }
            )
            try:
                self._uow.commit()
            except IntegrityError as exc:
                self._uow.rollback()
                raise ConflictError("operation_key уже использован для другой задачи") from exc
            created = self._uow.tasks.get_by_id(tid)
            if created is None:
                raise RuntimeError("Не удалось сохранить runtime assignment")
            return created.to_dict()

        locked = self._uow.tasks.lock(int(current.id or 0))
        if locked is None:
            raise ConflictError("Задача исчезла во время runtime assignment")
        if locked.assignment_operation_key == operation_key:
            if locked.mode_id != mode.id or locked.cycle_number != cycle_number:
                raise ConflictError("Повторный operation_key содержит другой assignment")
            return locked.to_dict()
        if locked.assignment_revision != expected_revision or locked.status != expected_status:
            raise ConflictError("Ожидаемое prior state/revision задачи устарело")
        if expected_mode_key is not None and locked.mode_key != expected_mode_key:
            raise ConflictError("Ожидаемый prior mode не совпадает")
        if expected_cycle_number is not None and locked.cycle_number != expected_cycle_number:
            raise ConflictError("Ожидаемый prior cycle не совпадает")
        if locked.status != "done":
            if locked.assignment_operation_key is not None:
                raise ConflictError("Другой assignment уже активен")
            if locked.mode_id != mode.id or locked.cycle_number != cycle_number:
                raise ConflictError("Нельзя сменить режим или цикл активной задачи")
        elif cycle_number != locked.cycle_number + 1:
            raise ConflictError("Business cycle должен быть строго следующим")
        self._uow.tasks.update(
            int(locked.id or 0),
            {
                "mode_id": mode.id,
                "cycle_number": cycle_number,
                "assignment_operation_key": operation_key,
                "assignment_revision": locked.assignment_revision + 1,
                "current_phase_id": phases[0].id,
                "status": "active",
            },
        )
        self._uow.tasks.record_phase_event(int(locked.id or 0), int(phases[0].id), "entered")
        try:
            self._uow.commit()
        except IntegrityError as exc:
            self._uow.rollback()
            raise ConflictError("operation_key уже использован для другой задачи") from exc
        assigned = self._uow.tasks.get_by_id(int(locked.id or 0))
        if assigned is None:
            raise RuntimeError("Не удалось обновить runtime assignment")
        return assigned.to_dict()

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
