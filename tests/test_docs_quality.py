"""Regression checks for user-facing documentation."""

import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = {
    "dashboard.png": (1400, 850),
    "namespaces.png": (1400, 850),
    "namespace-new.png": (1400, 850),
    "phases-qa.png": (1400, 850),
    "tasks.png": (1400, 850),
    "workflows.png": (1400, 850),
    "phases.png": (1400, 900),
    "task-detail-dev.png": (1400, 1200),
    "task-detail-qa.png": (1400, 900),
    "mobile-dashboard.png": (360, 650),
}


def _png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header.startswith(b"\x89PNG\r\n\x1a\n"), f"{path.name} must be a real PNG file"
    assert header[12:16] == b"IHDR", f"{path.name} must start with a PNG IHDR chunk"
    return struct.unpack(">II", header[16:24])


def test_readme_does_not_advertise_removed_namespace_prefixes_or_aliases() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8").casefold()

    assert "task key prefixes" not in readme
    assert "key prefixes" not in readme
    assert "legacy alias routes remain" not in readme


def test_readme_does_not_claim_public_task_crud() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8").casefold()

    assert "crud для workflows, phases, namespaces, agents и tasks" not in readme
    assert "просмотр задач" in readme


def test_readme_screenshots_are_real_full_size_pngs() -> None:
    screenshots_dir = ROOT / "docs" / "screenshots"

    for name, (min_width, min_height) in SCREENSHOTS.items():
        width, height = _png_size(screenshots_dir / name)

        assert width >= min_width, f"{name} width {width} is below {min_width}"
        assert height >= min_height, f"{name} height {height} is below {min_height}"
