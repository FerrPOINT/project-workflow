"""Application services — use cases."""

from __future__ import annotations

from typing import Any

from project_workflow.domain import Phase
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.phase_graph import PhaseGraphNode, validate_phase_graph
from project_workflow.domain.repositories import UnitOfWork


class PhaseServiceApp:
    """Use cases for phases."""

    DEFAULT_PHASE_NAME = "Новая фаза"

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def _generate_code(self, workflow_id: int, order: int) -> str:
        prefix = f"wf-{workflow_id}-phase-"
        existing = self._uow.phases.list(workflow_id)
        max_num = 0
        for phase in existing:
            if phase.code.startswith(prefix):
                suffix = phase.code[len(prefix) :]
                try:
                    max_num = max(max_num, int(suffix))
                except ValueError:
                    pass
        return f"{prefix}{max_num + 1}"

    def _lock_workflow(self, workflow_id: int) -> None:
        workflow = self._uow.workflows.lock(workflow_id)
        if workflow is None:
            raise NotFoundError(f"Воркфлоу {workflow_id} не найден")

    def _validate_agent(self, agent_id: Any) -> None:
        if agent_id is None:
            return
        if not isinstance(agent_id, int) or isinstance(agent_id, bool) or agent_id <= 0:
            raise ValueError("agent_id должен быть положительным целым числом или null")
        if self._uow.agents.lock(agent_id) is None:
            raise NotFoundError(f"Агент {agent_id} не найден")

    @staticmethod
    def _node(phase: Phase, **updates: Any) -> PhaseGraphNode:
        if phase.id is None:
            raise ValueError("Фаза без идентификатора не может участвовать в графе")
        return PhaseGraphNode(
            code=str(updates.get("code", phase.code)),
            graph_id=phase.id,
            phase_order=int(updates.get("phase_order", phase.phase_order)),
            execution_type=str(updates.get("execution_type", phase.execution_type)),
            parallel_with_phase_id=updates.get(
                "parallel_with_phase_id", phase.parallel_with_phase_id
            ),
            rollback_target_phase_id=updates.get(
                "rollback_target_phase_id", phase.rollback_target_phase_id
            ),
        )

    @staticmethod
    def _validate_graph(nodes: list[PhaseGraphNode]) -> None:
        try:
            validate_phase_graph(nodes)
        except ValueError as exc:
            raise ConflictError(str(exc)) from exc

    @staticmethod
    def _normalize_links(data: dict[str, Any]) -> None:
        for field in ("parallel_with_phase_id", "rollback_target_phase_id"):
            if field not in data or data[field] is None:
                continue
            if not isinstance(data[field], int) or isinstance(data[field], bool) or data[field] <= 0:
                raise ValueError(f"{field} должен быть положительным целым числом или null")

    def _rollback_if_owning_transaction(self, commit: bool) -> None:
        if commit:
            self._uow.rollback()

    def create_phase(self, data: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        workflow_id_raw = data.get("workflow_id")
        if not isinstance(workflow_id_raw, int) or isinstance(workflow_id_raw, bool) or workflow_id_raw <= 0:
            raise ValueError("workflow_id должен быть положительным целым числом")
        workflow_id = workflow_id_raw
        try:
            self._validate_agent(data.get("agent_id"))
            self._lock_workflow(workflow_id)
            existing = list(self._uow.phases.list(workflow_id))
            order = data.get("phase_order")
            if order is None:
                order = self._uow.phases.get_next_order(workflow_id)
            else:
                if not isinstance(order, int) or isinstance(order, bool) or order <= 0:
                    raise ValueError("phase_order должен быть положительным целым числом")
                if order > len(existing) + 1:
                    raise ConflictError(f"phase_order должен быть в диапазоне 1..{len(existing) + 1}")
            raw_code = data.get("code")
            if raw_code is None:
                code = self._generate_code(workflow_id, order)
            elif not isinstance(raw_code, str) or not raw_code.strip():
                raise ValueError("code должен быть непустой строкой")
            else:
                code = raw_code.strip()
            if any(phase.code == code for phase in existing):
                raise ConflictError(f"Код фазы {code!r} уже существует в этом воркфлоу")
            validated = dict(data)
            self._normalize_links(validated)
            prospective = [
                self._node(
                    phase,
                    phase_order=phase.phase_order + 1 if phase.phase_order >= order else phase.phase_order,
                )
                for phase in existing
            ]
            prospective.append(
                PhaseGraphNode(
                    code=code,
                    graph_id=f"new:{code}",
                    phase_order=order,
                    execution_type=validated.get("execution_type", "sync"),
                    parallel_with_phase_id=validated.get("parallel_with_phase_id"),
                    rollback_target_phase_id=validated.get("rollback_target_phase_id"),
                )
            )
            self._validate_graph(prospective)
            if any(phase.phase_order == order for phase in existing):
                self._uow.phases.shift_orders(workflow_id, order, delta=1)
            phase_data = {
                "workflow_id": workflow_id,
                "code": code,
                "name": validated.get("name", self.DEFAULT_PHASE_NAME),
                "description": validated.get("description", ""),
                "execution_type": validated.get("execution_type", "sync"),
                "phase_order": order,
                "agent_id": validated.get("agent_id"),
                "parallel_with_phase_id": validated.get("parallel_with_phase_id"),
                "rollback_target_phase_id": validated.get("rollback_target_phase_id"),
            }
            pid = self._uow.phases.create(phase_data)
            phase = self._uow.phases.get_by_id(pid)
            if not phase:
                raise RuntimeError("Не удалось создать фазу")
            if commit:
                self._uow.commit()
            return phase.to_dict()
        except Exception:
            self._rollback_if_owning_transaction(commit)
            raise

    def list_phases(self, workflow_id: int | None = None) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self._uow.phases.list(workflow_id=workflow_id)]

    def get_phase(self, phase_id: int) -> dict[str, Any] | None:
        p = self._uow.phases.get_by_id(phase_id)
        return p.to_dict() if p else None

    def prepare_update(self, phase_id: int, data: dict[str, Any]) -> tuple[dict[str, Any], list[int]]:
        phase = self._uow.phases.get_by_id(phase_id)
        if phase is None:
            raise NotFoundError(f"Фаза {phase_id} не найдена")
        if phase.workflow_id is None:
            raise ConflictError("Для фазы не найден владеющий воркфлоу")
        workflow_id = phase.workflow_id
        updates = dict(data)
        if "agent_id" in updates:
            self._validate_agent(updates["agent_id"])
        self._lock_workflow(workflow_id)
        self._normalize_links(updates)
        phases = list(self._uow.phases.list(workflow_id))
        phase = next((item for item in phases if item.id == phase_id), None)
        if phase is None:
            raise NotFoundError(f"Фаза {phase_id} не найдена")
        detached_ids: list[int] = []
        if updates.get("execution_type") == "sync":
            updates["parallel_with_phase_id"] = None
            detached_ids = [
                int(item.id)
                for item in phases
                if item.id is not None
                and item.id != phase_id
                and item.parallel_with_phase_id == phase_id
            ]
        prospective = [
            self._node(
                item,
                **(updates if item.id == phase_id else {}),
                **({"parallel_with_phase_id": None} if item.id in detached_ids else {}),
            )
            for item in phases
        ]
        self._validate_graph(prospective)
        return updates, detached_ids

    def update_phase(self, phase_id: int, data: dict[str, Any], *, commit: bool = True) -> None:
        try:
            updates, detached_ids = self.prepare_update(phase_id, data)
            for detached_id in detached_ids:
                self._uow.phases.update(detached_id, {"parallel_with_phase_id": None})
            self._uow.phases.update(phase_id, updates)
            if commit:
                self._uow.commit()
        except Exception:
            self._rollback_if_owning_transaction(commit)
            raise
        return None

    def delete_phase(self, phase_id: int, *, commit: bool = True) -> None:
        try:
            phase = self._uow.phases.get_by_id(phase_id)
            if phase is None:
                raise NotFoundError(f"Фаза {phase_id} не найдена")
            if phase.workflow_id is None:
                raise ConflictError("Для фазы не найден владеющий воркфлоу")
            workflow_id = phase.workflow_id
            self._lock_workflow(workflow_id)
            references = self._uow.phases.reference_kinds(phase_id)
            if references:
                raise ConflictError(f"На фазу ссылаются: {', '.join(sorted(references))}")
            self._uow.phases.delete(phase_id)
            self._uow.phases.resequence(workflow_id)
            if commit:
                self._uow.commit()
        except Exception:
            self._rollback_if_owning_transaction(commit)
            raise
        return None

    def reorder_phases(self, orders: list[tuple[int, int]], *, commit: bool = True) -> int:
        try:
            if not orders:
                raise ValueError("Список порядка фаз пуст")
            phase_ids = [phase_id for phase_id, _ in orders]
            if len(phase_ids) != len(set(phase_ids)):
                raise ConflictError("Список порядка фаз содержит повторяющиеся идентификаторы")

            phases = [self._uow.phases.get_by_id(phase_id) for phase_id in phase_ids]
            if any(phase is None for phase in phases):
                raise NotFoundError("Список порядка фаз содержит неизвестную фазу")
            if any(phase is not None and phase.workflow_id is None for phase in phases):
                raise ConflictError("Для перемещаемой фазы не найден владеющий воркфлоу")
            workflow_ids = {
                phase.workflow_id
                for phase in phases
                if phase is not None and phase.workflow_id is not None
            }
            if len(workflow_ids) != 1:
                raise ConflictError("Все перемещаемые фазы должны принадлежать одному воркфлоу")
            workflow_id = workflow_ids.pop()
            self._lock_workflow(workflow_id)

            locked_phases = list(self._uow.phases.list(workflow_id))
            current_ids = {phase.id for phase in locked_phases}
            if set(phase_ids) != current_ids:
                raise ConflictError("Порядок должен содержать каждую фазу воркфлоу ровно один раз")
            positions = [position for _, position in orders]
            if sorted(positions) != list(range(1, len(orders) + 1)):
                raise ConflictError("Позиции фаз должны образовывать непрерывный диапазон 1..N")

            position_by_id = dict(orders)
            prospective = [
                self._node(phase, phase_order=position_by_id[int(phase.id)])
                for phase in locked_phases
                if phase.id is not None
            ]
            self._validate_graph(prospective)

            self._uow.phases.reorder(workflow_id, orders)
            if commit:
                self._uow.commit()
            return len(orders)
        except Exception:
            self._rollback_if_owning_transaction(commit)
            raise
