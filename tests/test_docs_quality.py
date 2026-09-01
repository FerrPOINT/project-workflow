"""Regression checks for user-facing documentation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_does_not_advertise_removed_namespace_prefixes_or_aliases() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8").casefold()

    assert "task key prefixes" not in readme
    assert "key prefixes" not in readme
    assert "legacy alias routes remain" not in readme
