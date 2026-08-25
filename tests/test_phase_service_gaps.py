"""Coverage gap tests for phase_service helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from project_workflow.application.phase_service import PhaseService

pytestmark = [pytest.mark.unit]


class TestPhaseServiceHelpers:
    def test_normalize_skills_is_list_only(self):
        assert PhaseService.normalize_skills(["", "  a  ", "b"]) == ["a", "b"]
        with pytest.raises(TypeError):
            PhaseService.normalize_skills([1])
        with pytest.raises(TypeError):
            PhaseService.normalize_skills("not json")


class TestPhaseServiceUow:
    def test_resolve_phase_id_rejects_code_identifier(self):
        uow = MagicMock()
        service = PhaseService(uow)
        with pytest.raises(ValueError, match="должен быть числом"):
            service._resolve_phase_id("my-code")
        uow.phases.get_by_code.assert_not_called()

    def test_resolve_phase_id_not_found(self):
        uow = MagicMock()
        uow.phases.get_by_id.return_value = None
        service = PhaseService(uow)
        with pytest.raises(ValueError):
            service._resolve_phase_id(999)

    def test_get_phase_detail_returns_empty_on_resolve_error(self):
        uow = MagicMock()
        service = PhaseService(uow)
        assert service.get_phase_detail("missing") == {}

    def test_get_phase_detail_phase_not_found(self):
        uow = MagicMock()
        phase = MagicMock()
        phase.id = 7
        uow.phases.get_by_id.return_value = None
        service = PhaseService(uow)
        assert service.get_phase_detail(7) == {}
