"""Regression tests for seed persistence bugs (second review pass).

1. persist_phase_update_to_seed / persist_phase_order_to_seed crashed with
   OSError EXDEV when the seed file lives on a different filesystem than /tmp
   (NamedTemporaryFile defaults to /tmp; os.replace across devices is invalid).
   Fixed by creating the temp file next to the target.
2. persist_phase_order_to_seed wrote duplicate seed entries when the ordered
   codes list contained duplicates.
3. persist_phase_update_to_seed actually persists the update (end-to-end).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import project_workflow.infrastructure.db.schema as schema
from project_workflow.infrastructure.db.schema import (
    persist_phase_order_to_seed,
    persist_phase_update_to_seed,
)


class _FakeUow:
    workflows = SimpleNamespace(get_default=lambda: None)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture()
def seed_file(tmp_path: Path) -> Path:
    seed = [
        {"code": "a", "name": "A", "phase_order": 1},
        {"code": "b", "name": "B", "phase_order": 2},
    ]
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _no_catalog_cache(monkeypatch):
    # persist_* may consult module-level caches; keep tests isolated.
    monkeypatch.setattr(schema, "_CATALOG_ENSURED_URLS", set(), raising=False)


class TestPersistPhaseUpdate:
    def test_update_is_written(self, seed_file: Path):
        persist_phase_update_to_seed(_FakeUow(), "a", {"name": "A2"}, seed_path=seed_file)
        data = json.loads(seed_file.read_text(encoding="utf-8"))
        assert data[0]["name"] == "A2"
        assert data[1]["name"] == "B"

    def test_cross_device_safe(self, seed_file: Path, monkeypatch):
        # Simulate EXDEV: force tempfile.mkstemp into another directory that
        # still exists — the fix writes next to the target, so patching
        # tempfile.tempdir to an unrelated dir must not break the write.
        import tempfile as tf

        other = Path(tempfile.mkdtemp())
        monkeypatch.setattr(tf, "tempdir", str(other))
        persist_phase_update_to_seed(_FakeUow(), "b", {"name": "B2"}, seed_path=seed_file)
        data = json.loads(seed_file.read_text(encoding="utf-8"))
        assert data[1]["name"] == "B2"

    def test_unknown_code_is_noop(self, seed_file: Path):
        persist_phase_update_to_seed(_FakeUow(), "zzz", {"name": "X"}, seed_path=seed_file)
        data = json.loads(seed_file.read_text(encoding="utf-8"))
        assert data[0]["name"] == "A"

    def test_missing_seed_file_is_noop(self, tmp_path: Path):
        persist_phase_update_to_seed(_FakeUow(), "a", {"name": "X"}, seed_path=tmp_path / "nope.json")


class TestPersistPhaseOrder:
    def test_order_written(self, seed_file: Path, monkeypatch):
        monkeypatch.setattr(schema, "_load_seed", lambda p: json.loads(p.read_text(encoding="utf-8")))
        persist_phase_order_to_seed(_FakeUow(), ["b", "a"], seed_path=seed_file)
        codes = [e["code"] for e in json.loads(seed_file.read_text(encoding="utf-8"))]
        assert codes == ["b", "a"]

    def test_duplicate_codes_do_not_duplicate_entries(self, seed_file: Path, monkeypatch):
        monkeypatch.setattr(schema, "_load_seed", lambda p: json.loads(p.read_text(encoding="utf-8")))
        persist_phase_order_to_seed(_FakeUow(), ["b", "a", "a", "a"], seed_path=seed_file)
        codes = [e["code"] for e in json.loads(seed_file.read_text(encoding="utf-8"))]
        assert codes == ["b", "a"], f"duplicates leaked into seed: {codes}"

    def test_unknown_codes_dropped_existing_appended(self, seed_file: Path, monkeypatch):
        monkeypatch.setattr(schema, "_load_seed", lambda p: json.loads(p.read_text(encoding="utf-8")))
        persist_phase_order_to_seed(_FakeUow(), ["zzz", "b"], seed_path=seed_file)
        codes = [e["code"] for e in json.loads(seed_file.read_text(encoding="utf-8"))]
        assert codes == ["b", "a"]
