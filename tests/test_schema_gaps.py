"""Coverage gap tests for infrastructure.db.schema."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from project_workflow import config
from project_workflow.infrastructure.db.schema import (
    _load_seed,
    _normalized_url,
    _phase_item_to_wizard,
    ensure_phase_catalog,
    get_phase_from_db,
    load_phases_from_db,
    load_phases_from_seed,
    mark_catalog_not_ensured,
    persist_phase_order_to_seed,
    persist_phase_update_to_seed,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork

pytestmark = [pytest.mark.ui]


def _seed_path(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[1] / "project_workflow" / "references" / "seed.json"
    dst = tmp_path / "seed.json"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dst


class TestSchemaEdgeCases:
    def test_normalized_url_no_engine(self):
        uow = MagicMock()
        uow._session = None
        assert _normalized_url(uow) == ""

    def test_mark_catalog_not_ensured_clears_all(self):
        from project_workflow.infrastructure.db import schema

        schema._CATALOG_ENSURED_URLS.add("sqlite:///.test.db")
        mark_catalog_not_ensured()
        assert not schema._CATALOG_ENSURED_URLS

    def test_load_phases_from_db_returns_fallback_intake(self, tmp_path, monkeypatch):
        url = f"sqlite:///{tmp_path / 'empty.db'}"
        uow = SAUnitOfWork(url)
        uow.create_all()
        monkeypatch.setattr(config, "SEED_PATH", _seed_path(tmp_path))
        ensure_phase_catalog(uow)
        phases = load_phases_from_db(uow, workflow_id=999999)
        assert any(p.code == "-1" for p in phases)
        uow.close()

    def test_load_phases_from_db_with_string_workflow_id(self, tmp_path, monkeypatch):
        url = f"sqlite:///{tmp_path / 'str.db'}"
        uow = SAUnitOfWork(url)
        uow.create_all()
        monkeypatch.setattr(config, "SEED_PATH", _seed_path(tmp_path))
        ensure_phase_catalog(uow)
        phases = load_phases_from_db(uow, workflow_id="not-a-number")
        assert any(p.code == "-1" for p in phases)
        uow.close()

    def test_get_phase_from_db_with_string_workflow_id(self, tmp_path, monkeypatch):
        url = f"sqlite:///{tmp_path / 'str2.db'}"
        uow = SAUnitOfWork(url)
        uow.create_all()
        monkeypatch.setattr(config, "SEED_PATH", _seed_path(tmp_path))
        ensure_phase_catalog(uow)
        # workflow_id string 'bad' normalizes to None, so search is global and finds '1'.
        phase = get_phase_from_db(uow, "1", workflow_id="bad")
        assert phase is not None
        assert phase.code == "1"
        uow.close()

    def test_load_seed_yaml(self, tmp_path):
        yaml_path = tmp_path / "seed.yaml"
        yaml_path.write_text("- code: yaml-phase\n  name: YAML\n", encoding="utf-8")
        items = _load_seed(yaml_path)
        assert items[0]["code"] == "yaml-phase"

    def test_load_seed_non_list(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text('{"foo": "bar"}', encoding="utf-8")
        assert _load_seed(path) == []

    def test_phase_item_to_wizard_with_delegate(self):
        phase = _phase_item_to_wizard(
            {
                "code": "DLG",
                "name": "Delegate",
                "delegate": {
                    "agent": "reviewer",
                    "toolsets": ["ts1"],
                    "timeout_min": 5,
                    "max_cycles": 2,
                },
            }
        )
        assert phase.delegate is not None
        assert phase.delegate.agent == "reviewer"
        assert phase.delegate.toolsets == ["ts1"]
        assert phase.delegate.timeout_min == 5
        assert phase.delegate.max_cycles == 2

    def test_load_phases_from_seed_workflow_filter_is_noop(self, tmp_path):
        path = _seed_path(tmp_path)
        phases = load_phases_from_seed(path, workflow_id=42)
        assert len(phases) > 0

    def test_persist_phase_order_to_seed(self, tmp_path, monkeypatch):
        seed_path = _seed_path(tmp_path)
        # Seed a custom phase that we will reorder to the front.
        seed_data = _load_seed(seed_path)
        seed_data.insert(0, {"code": "GAP-ORD", "name": "Order Gap"})
        seed_path.write_text(json.dumps(seed_data), encoding="utf-8")
        monkeypatch.setattr(config, "SEED_PATH", seed_path)

        url = f"sqlite:///{tmp_path / 'persist.db'}"
        uow = SAUnitOfWork(url)
        uow.create_all()
        ensure_phase_catalog(uow)

        persist_phase_order_to_seed(uow, ["GAP-ORD"], seed_path=seed_path)
        assert seed_path.exists()
        data = _load_seed(seed_path)
        codes = [p["code"] for p in data]
        assert codes[0] == "GAP-ORD"
        uow.close()

    def test_persist_phase_update_to_seed_missing_file(self, tmp_path):
        missing = tmp_path / "missing.yaml"
        persist_phase_update_to_seed(MagicMock(), "1", {}, seed_path=missing)

    def test_persist_phase_update_to_seed_skips_id_and_code(self, tmp_path):
        seed_path = tmp_path / "seed.json"
        seed_path.write_text('[{"code":"1","name":"A"}]', encoding="utf-8")
        persist_phase_update_to_seed(
            MagicMock(),
            "1",
            {"name": "B", "code": "2", "id": 99, "description": "d"},
            seed_path=seed_path,
        )
        data = _load_seed(seed_path)
        assert data[0]["name"] == "B"
        assert data[0]["description"] == "d"
        assert data[0]["code"] == "1"

    def test_ensure_phase_catalog_skip_already_ensured_url(self, tmp_path, monkeypatch):
        from project_workflow.infrastructure.db import schema as schema_mod

        seed_path = _seed_path(tmp_path)
        monkeypatch.setattr(config, "SEED_PATH", seed_path)
        url = f"sqlite:///{tmp_path / 'skip.db'}"
        uow = SAUnitOfWork(url)
        uow.create_all()
        mark_catalog_not_ensured(url)
        ensure_phase_catalog(uow)
        assert url in schema_mod._CATALOG_ENSURED_URLS or any(
            url.endswith(u.split("/")[-1]) for u in schema_mod._CATALOG_ENSURED_URLS
        )

        # Use a mock UoW whose phases.list would raise if called; ensure must skip.
        mock_uow = MagicMock()
        mock_uow._session = uow._session
        mock_uow.agents.list.return_value = []
        mock_uow.workflows.ensure_default_exists.return_value = MagicMock(id=1)
        mock_uow.phases.list.return_value = []
        schema_mod._CATALOG_ENSURED_URLS.add(schema_mod._normalized_url(uow))
        ensure_phase_catalog(mock_uow)
        mock_uow.phases.list.assert_not_called()
        uow.close()
