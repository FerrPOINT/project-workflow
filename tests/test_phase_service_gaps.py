"""Coverage gap tests for phase_service helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from project_workflow.application.phase_service import PhaseService

pytestmark = [pytest.mark.unit]


class TestPhaseServiceHelpers:
    def test_normalize_skills_int_and_dict(self):
        assert PhaseService.normalize_skills([1, "", "  a  ", "b"]) == ["1", "a", "b"]
        assert PhaseService.normalize_skills({}) == []
        assert PhaseService.normalize_skills("not json") == []

    def test_parse_skills_invalid_json(self):
        with patch("project_workflow.application.phase_service.logger") as logger:
            assert PhaseService.parse_skills("not-json") == []
            logger.warning.assert_called_once()

    def test_serialize_skills_empty(self):
        assert PhaseService.serialize_skills([]) is None
        assert PhaseService.serialize_skills(None) is None


class TestPhaseServiceUow:
    def test_resolve_phase_id_by_code(self):
        uow = MagicMock()
        phase = MagicMock()
        phase.id = 7
        uow.phases.get_by_code.return_value = phase
        service = PhaseService(uow)
        assert service._resolve_phase_id("my-code") == 7

    def test_resolve_phase_id_not_found(self):
        uow = MagicMock()
        uow.phases.get_by_id.return_value = None
        service = PhaseService(uow)
        with pytest.raises(ValueError):
            service._resolve_phase_id(999)

    def test_get_phase_detail_returns_empty_on_resolve_error(self):
        uow = MagicMock()
        uow.phases.get_by_code.return_value = None
        service = PhaseService(uow)
        assert service.get_phase_detail("missing") == {}

    def test_get_phase_detail_phase_not_found(self):
        uow = MagicMock()
        phase = MagicMock()
        phase.id = 7
        uow.phases.get_by_code.return_value = phase
        uow.phases.get_by_id.return_value = None
        service = PhaseService(uow)
        assert service.get_phase_detail(7) == {}
