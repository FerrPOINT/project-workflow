"""Tests for interfaces.ui.skills catalog helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from project_workflow.interfaces.ui import skills as skills_mod


def test_scan_hermes_skills_missing_tool():
    with patch("importlib.import_module", side_effect=ImportError("no module")):
        assert skills_mod._scan_hermes_skills() == []


def test_scan_hermes_skills_missing_attr():
    fake_module = MagicMock()
    del fake_module._find_all_skills
    with patch("importlib.import_module", return_value=fake_module):
        assert skills_mod._scan_hermes_skills() == []


def test_scan_hermes_skills_filters_items():
    fake_module = MagicMock()
    fake_module._find_all_skills.return_value = [
        {"name": "skill_a", "description": " A ", "category": "cat"},
        {"name": "  "},
        "not-a-dict",
        {"name": "skill_b"},
    ]
    with patch("importlib.import_module", return_value=fake_module):
        result = skills_mod._scan_hermes_skills()
    assert len(result) == 2
    # Results sorted by category, then name; skill_a has category, skill_b has None.
    assert result[0]["name"] == "skill_b"
    assert result[0]["description"] is None
    assert result[1]["name"] == "skill_a"
    assert result[1]["description"] == "A"


def test_load_skills_catalog_refreshes(monkeypatch):
    skills_mod._skills_catalog_cache = None
    skills_mod._skills_catalog_cached_at = 0
    scanner = MagicMock(return_value=[{"name": "cached"}])
    # The function resolves the scanner via the parent ui package namespace.
    import project_workflow.interfaces.ui as ui_pkg
    monkeypatch.setattr(ui_pkg, "_scan_hermes_skills", scanner)
    first = skills_mod._load_skills_catalog()
    assert first == [{"name": "cached"}]
    second = skills_mod._load_skills_catalog()
    assert second == first
    assert scanner.call_count == 1
    third = skills_mod._load_skills_catalog(refresh=True)
    assert third == first
    assert scanner.call_count == 2
