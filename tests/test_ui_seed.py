"""Tests for interfaces.ui.seed helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui import seed as seed_mod


def test_update_config_phase_order_with_uow():
    uow = MagicMock(spec=SAUnitOfWork)
    wf = MagicMock()
    wf.id = 1
    uow.workflows.get_default.return_value = wf
    phases = [
        {"code": "p2", "phase_order": 2, "workflow_is_default": True, "is_seed_managed": True},
        {"code": "p1", "phase_order": 1, "workflow_is_default": True, "is_seed_managed": True},
    ]
    with patch("project_workflow.interfaces.ui.seed.PhaseServiceApp") as svc_cls:
        svc_cls.return_value.list_phases.return_value = phases
        seed_mod._update_config_phase_order(uow)
    assert seed_mod.config.PHASE_ORDER == ["p1", "p2"]


def test_update_config_phase_order_no_seed_managed():
    uow = MagicMock(spec=SAUnitOfWork)
    wf = MagicMock()
    wf.id = 1
    uow.workflows.get_default.return_value = wf
    with patch("project_workflow.interfaces.ui.seed.PhaseServiceApp") as svc_cls:
        svc_cls.return_value.list_phases.return_value = []
        before = list(seed_mod.config.PHASE_ORDER)
        seed_mod._update_config_phase_order(uow)
        assert seed_mod.config.PHASE_ORDER == before


def test_update_config_phase_order_non_uow():
    wdb = MagicMock()
    state = MagicMock()
    uow = MagicMock(spec=SAUnitOfWork)
    wf = MagicMock()
    wf.id = 1
    uow.workflows.get_default.return_value = wf
    state.get_uow.return_value = uow
    wdb.get.return_value = uow
    phases = [
        {"code": "p1", "phase_order": 1, "workflow_is_default": True, "is_seed_managed": True},
    ]
    with patch.object(seed_mod, "_get_app_state", return_value=state):
        with patch("project_workflow.interfaces.ui.seed.PhaseServiceApp") as svc_cls:
            svc_cls.return_value.list_phases.return_value = phases
            seed_mod._update_config_phase_order(wdb)
    assert seed_mod.config.PHASE_ORDER == ["p1"]
