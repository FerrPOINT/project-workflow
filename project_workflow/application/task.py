"""Application services — use cases."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError

from project_workflow.application.execution_mode import resolve_execution_selection
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import UnitOfWork
from project_workflow.domain.runtime_assignment import normalize_role_key, payload_sha256
from project_workflow.domain.validation import TaskKeyValidator, get_project_for_task_key


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
        role_key: str,
        execution_scope: str,
        cycle_number: int,
        operation_key: str,
        business_task_ref: str,
        root_task_ref: str,
        work_item_ref: str,
        task_workspace_ref: str,
        tech_execution_workspace_ref: str | None,
        tech_execution_attempt_ref: str | None,
        decomposition_revision_ref: str,
        stage_revision: str,
        assignment_ref: str,
        binding_ref: str,
        hermes_run_ref: str,
        workspace_generation: int,
        lease_generation: int,
        exact_input_refs: list[dict[str, Any]],
        expected_revision: int,
        expected_status: str,
        expected_mode_key: str | None = None,
        expected_cycle_number: int | None = None,
    ) -> dict[str, Any]:
        """Persist one authorized Business assignment atomically and idempotently."""
        operation_key = operation_key.strip()
        mode_key = mode_key.strip()
        role_key = normalize_role_key(role_key)
        if not operation_key or len(operation_key) > 128:
            raise ValueError("operation_key должен быть непустой строкой длиной до 128 символов")
        if not mode_key or len(mode_key) > 128:
            raise ValueError("mode_key должен быть непустой строкой длиной до 128 символов")
        validated_key = TaskKeyValidator.from_projects([]).validate(task_key)
        if not validated_key.is_valid:
            raise ConflictError(validated_key.error_message or f"Недопустимый ключ задачи {task_key!r}")
        task_key = validated_key.normalized or task_key
        project = self._uow.projects.lock(project_id)
        if project is None or project.workflow_id is None:
            raise NotFoundError(f"Неймспейс {project_id} не найден")
        mode = self._uow.workflows.get_mode_by_key(project.workflow_id, mode_key)
        if mode is None or mode.id is None:
            raise ConflictError(f"Режим {mode_key!r} не найден в воркфлоу {project.workflow_id}")
        self._validate_mode_policy(
            mode=mode,
            role_key=role_key,
            execution_scope=execution_scope,
            tech_execution_workspace_ref=tech_execution_workspace_ref,
            tech_execution_attempt_ref=tech_execution_attempt_ref,
        )
        if cycle_number < 0 or expected_revision < 0:
            raise ValueError("cycle_number и expected_revision должны быть неотрицательными")
        if workspace_generation < 0 or lease_generation < 0:
            raise ValueError("workspace_generation и lease_generation должны быть неотрицательными")
        external_refs = {
            "business_task_ref": business_task_ref,
            "root_task_ref": root_task_ref,
            "work_item_ref": work_item_ref,
            "task_workspace_ref": task_workspace_ref,
            "decomposition_revision_ref": decomposition_revision_ref,
            "stage_revision": stage_revision,
            "assignment_ref": assignment_ref,
            "binding_ref": binding_ref,
            "hermes_run_ref": hermes_run_ref,
        }
        normalized_refs = {
            key: self._bounded_ref(value, key, 128 if key == "stage_revision" else 512)
            for key, value in external_refs.items()
        }
        normalized_tech_workspace_ref = (
            self._bounded_ref(tech_execution_workspace_ref, "tech_execution_workspace_ref", 512)
            if tech_execution_workspace_ref is not None
            else None
        )
        normalized_tech_attempt_ref = (
            self._bounded_ref(tech_execution_attempt_ref, "tech_execution_attempt_ref", 512)
            if tech_execution_attempt_ref is not None
            else None
        )
        normalized_input_refs = self._normalize_exact_input_refs(exact_input_refs)
        payload = {
            "project_id": project_id,
            "task_key": task_key,
            "workflow_id": project.workflow_id,
            "mode_key": mode.key,
            "role_key": role_key,
            "execution_scope": execution_scope,
            "cycle_number": cycle_number,
            "operation_key": operation_key,
            **normalized_refs,
            "tech_execution_workspace_ref": normalized_tech_workspace_ref,
            "tech_execution_attempt_ref": normalized_tech_attempt_ref,
            "workspace_generation": workspace_generation,
            "lease_generation": lease_generation,
            "exact_input_refs": normalized_input_refs,
            "expected_revision": expected_revision,
            "expected_status": expected_status,
            "expected_mode_key": expected_mode_key,
            "expected_cycle_number": expected_cycle_number,
        }
        replay = self._uow.tasks.get_assignment_by_operation_key(operation_key)
        if replay is not None:
            return self._reconcile_assignment(replay.to_dict(), payload)
        phases = list(self._uow.phases.list(workflow_id=project.workflow_id, mode_id=mode.id))
        if not phases or phases[0].id is None:
            raise ConflictError(f"Режим {mode_key!r} не содержит начальной фазы")
        current = self._uow.tasks.get_by_key(task_key, project_id=project_id)
        if current is None:
            if expected_status != "missing" or expected_revision != 0:
                raise ConflictError("Ожидаемое состояние отсутствующей задачи не совпадает")
            if cycle_number != 0:
                raise ConflictError("Начальный Business assignment должен иметь cycle_number=0")
            try:
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
                self._uow.tasks.create_assignment(
                    self._assignment_record(
                        payload,
                        operation_key=operation_key,
                        task_id=tid,
                        project_id=project_id,
                        workflow_id=project.workflow_id,
                        mode_id=mode.id,
                        cycle_number=cycle_number,
                        assignment_revision=1,
                    )
                )
                self._uow.commit()
            except IntegrityError as exc:
                self._uow.rollback()
                return self._reconcile_after_integrity_error(operation_key, payload, exc)
            created = self._uow.tasks.get_by_id(tid)
            if created is None:
                raise RuntimeError("Не удалось сохранить runtime assignment")
            persisted = self._uow.tasks.get_assignment_by_operation_key(operation_key)
            if persisted is None:
                raise RuntimeError("Не удалось перечитать runtime assignment")
            return self._assignment_result(created.to_dict(), persisted.to_dict())

        locked = self._uow.tasks.lock(int(current.id or 0))
        if locked is None:
            raise ConflictError("Задача исчезла во время runtime assignment")
        # A concurrent request can win after our initial ledger read but before
        # this row lock. Reconcile the durable operation before treating its
        # advanced projection as a stale expected revision.
        replay = self._uow.tasks.get_assignment_by_operation_key(operation_key)
        if replay is not None:
            return self._reconcile_assignment(replay.to_dict(), payload)
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
        next_revision = locked.assignment_revision + 1
        try:
            self._uow.tasks.update(
                int(locked.id or 0),
                {
                    "mode_id": mode.id,
                    "cycle_number": cycle_number,
                    "assignment_operation_key": operation_key,
                    "assignment_revision": next_revision,
                    "current_phase_id": phases[0].id,
                    "status": "active",
                },
            )
            self._uow.tasks.record_phase_event(int(locked.id or 0), int(phases[0].id), "entered")
            self._uow.tasks.create_assignment(
                self._assignment_record(
                    payload,
                    operation_key=operation_key,
                    task_id=int(locked.id or 0),
                    project_id=project_id,
                    workflow_id=project.workflow_id,
                    mode_id=mode.id,
                    cycle_number=cycle_number,
                    assignment_revision=next_revision,
                )
            )
            self._uow.commit()
        except IntegrityError as exc:
            self._uow.rollback()
            return self._reconcile_after_integrity_error(operation_key, payload, exc)
        assigned = self._uow.tasks.get_by_id(int(locked.id or 0))
        if assigned is None:
            raise RuntimeError("Не удалось обновить runtime assignment")
        persisted = self._uow.tasks.get_assignment_by_operation_key(operation_key)
        if persisted is None:
            raise RuntimeError("Не удалось перечитать runtime assignment")
        return self._assignment_result(assigned.to_dict(), persisted.to_dict())

    @staticmethod
    def _bounded_ref(value: Any, field_name: str, max_length: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
            raise ValueError(f"{field_name} должен быть непустой строкой длиной до {max_length} символов")
        return value.strip()

    @classmethod
    def _normalize_exact_input_refs(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(value, list) or not 1 <= len(value) <= 100:
            raise ValueError("exact_input_refs должен содержать от 1 до 100 snapshot-объектов")
        allowed_kinds = {
            "business_task", "comment", "attachment", "link", "artifact", "decomposition", "stage"
        }
        normalized: list[dict[str, Any]] = []
        identities: set[tuple[str, str, str, str]] = set()
        for raw in value:
            if not isinstance(raw, dict) or set(raw) - {"kind", "ref", "revision", "sha256"}:
                raise ValueError("Каждый exact input snapshot должен иметь только kind/ref/revision/sha256")
            kind = raw.get("kind")
            if kind not in allowed_kinds:
                raise ValueError("Неизвестный kind в exact_input_refs")
            ref = cls._bounded_ref(raw.get("ref"), "exact_input_refs.ref", 512)
            revision = cls._bounded_ref(raw.get("revision"), "exact_input_refs.revision", 128)
            sha256 = raw.get("sha256")
            if sha256 is not None and (
                not isinstance(sha256, str)
                or len(sha256) != 64
                or any(char not in "0123456789abcdef" for char in sha256)
            ):
                raise ValueError("exact_input_refs.sha256 должен быть lowercase SHA-256")
            identity = (kind, ref, revision, sha256 or "")
            if identity in identities:
                raise ValueError("exact_input_refs не должен содержать дубликаты")
            identities.add(identity)
            normalized.append({"kind": kind, "ref": ref, "revision": revision, "sha256": sha256})
        return sorted(
            normalized,
            key=lambda item: (
                str(item["kind"]),
                str(item["ref"]),
                str(item["revision"]),
                str(item["sha256"] or ""),
            ),
        )

    @staticmethod
    def _validate_mode_policy(
        *,
        mode: Any,
        role_key: str,
        execution_scope: str,
        tech_execution_workspace_ref: str | None,
        tech_execution_attempt_ref: str | None,
    ) -> None:
        if not mode.role_key or not mode.execution_scope or not mode.tech_workspace_policy:
            raise ConflictError("Режим не содержит полный backend-owned assignment policy")
        if mode.role_key != role_key:
            raise ConflictError("Backend-owned policy не разрешает указанную роль")
        if mode.execution_scope != execution_scope:
            raise ConflictError("Backend-owned mode policy не разрешает указанный execution scope")
        if mode.tech_workspace_policy == "required" and (
            tech_execution_workspace_ref is None or tech_execution_attempt_ref is None
        ):
            raise ConflictError("Mode policy требует TechExecutionWorkspace и attempt ref")
        if mode.tech_workspace_policy == "forbidden" and (
            tech_execution_workspace_ref is not None or tech_execution_attempt_ref is not None
        ):
            raise ConflictError("Mode policy запрещает TechExecutionWorkspace")

    @staticmethod
    def _assignment_record(payload: dict[str, Any], **identity: Any) -> dict[str, Any]:
        return {
            **identity,
            **{
                key: payload[key]
                for key in (
                    "role_key",
                    "execution_scope",
                    "business_task_ref",
                    "root_task_ref",
                    "work_item_ref",
                    "task_workspace_ref",
                    "tech_execution_workspace_ref",
                    "tech_execution_attempt_ref",
                    "decomposition_revision_ref",
                    "stage_revision",
                    "assignment_ref",
                    "binding_ref",
                    "hermes_run_ref",
                    "workspace_generation",
                    "lease_generation",
                    "exact_input_refs",
                )
            },
            "payload": payload,
            "payload_sha256": payload_sha256(payload),
        }

    @staticmethod
    def _assignment_result(task: dict[str, Any], assignment: dict[str, Any]) -> dict[str, Any]:
        result = dict(task)
        for key in (
            "role_key",
            "execution_scope",
            "business_task_ref",
            "root_task_ref",
            "work_item_ref",
            "task_workspace_ref",
            "tech_execution_workspace_ref",
            "tech_execution_attempt_ref",
            "decomposition_revision_ref",
            "stage_revision",
            "assignment_ref",
            "binding_ref",
            "hermes_run_ref",
            "workspace_generation",
            "lease_generation",
            "exact_input_refs",
        ):
            result[key] = assignment.get(key)
        return result

    def _reconcile_after_integrity_error(
        self, operation_key: str, payload: dict[str, Any], cause: IntegrityError
    ) -> dict[str, Any]:
        replay = self._uow.tasks.get_assignment_by_operation_key(operation_key)
        if replay is None:
            raise ConflictError("Runtime assignment конфликтует с уже сохранённым состоянием") from cause
        return self._reconcile_assignment(replay.to_dict(), payload, cause)

    def _reconcile_assignment(
        self,
        assignment: dict[str, Any],
        payload: dict[str, Any],
        cause: Exception | None = None,
    ) -> dict[str, Any]:
        expected_digest = payload_sha256(payload)
        if assignment.get("payload_sha256") != expected_digest or assignment.get("payload") != payload:
            raise ConflictError("operation_key уже использован для другого runtime assignment") from cause
        task = self._uow.tasks.get_by_id(int(assignment["task_id"]))
        if task is None:
            raise ConflictError("Runtime assignment ссылается на отсутствующую задачу") from cause
        if (
            task.project_id != assignment.get("project_id")
            or task.workflow_id != assignment.get("workflow_id")
            or task.task_key != payload.get("task_key")
        ):
            raise ConflictError("operation_key уже использован для другой задачи") from cause
        result = self._assignment_result(task.to_dict(), assignment)
        phases = list(
            self._uow.phases.list(
                workflow_id=int(assignment["workflow_id"]), mode_id=int(assignment["mode_id"])
            )
        )
        first_phase = phases[0] if phases else None
        result.update(
            {
                "mode_id": assignment["mode_id"],
                "mode_key": assignment["mode_key"],
                "cycle_number": assignment["cycle_number"],
                "assignment_operation_key": assignment["operation_key"],
                "assignment_revision": assignment["assignment_revision"],
                "current_phase_id": first_phase.id if first_phase else None,
                "current_phase_code": first_phase.code if first_phase else None,
                "current_phase_name": first_phase.name if first_phase else None,
            }
        )
        return result

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
