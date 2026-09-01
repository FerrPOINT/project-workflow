"""Regression checks for user-facing documentation."""

import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = {
    "dashboard.png": (1900, 1700),
    "dashboard-qa.png": (1900, 1700),
    "namespaces.png": (1900, 1000),
    "namespace-new.png": (1900, 1000),
    "phases-qa.png": (1900, 1200),
    "tasks.png": (1900, 1080),
    "tasks-qa.png": (1900, 1080),
    "workflows.png": (1900, 1000),
    "instructions.png": (1900, 1000),
    "agents.png": (1900, 1000),
    "phases.png": (1900, 3000),
    "task-detail-dev.png": (1900, 3500),
    "task-detail-qa.png": (1900, 2200),
    "settings.png": (1900, 1000),
    "mobile-dashboard.png": (360, 3000),
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


def test_readme_does_not_advertise_absent_systemd_unit() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "project-workflow-ui.service" not in readme
    assert "sudo systemctl" not in readme
    assert "curl --fail http://127.0.0.1:8811/health" not in readme
    assert "curl --fail http://127.0.0.1:8812/health" in readme


def test_readme_cli_examples_use_configured_wrapper_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "workflow-run step --task RUN-123" in readme
    assert "workflow-run history --task RUN-123" in readme
    assert "workflow-qa step --task RUN-42" in readme
    assert "workflow-dev history --task RUN-42" in readme
    assert "project-workflow step --task" not in readme
    assert "project-workflow history --task" not in readme


def test_quality_gate_ui_smoke_matches_settings_screenshot() -> None:
    quality_gate = (ROOT / "docs" / "quality-gate.md").read_text(encoding="utf-8")

    assert "http://127.0.0.1:8812/settings" in quality_gate
    assert "CLI settings" in quality_gate or "wrapper-команду" in quality_gate


def test_readme_screenshots_are_real_full_size_pngs() -> None:
    screenshots_dir = ROOT / "docs" / "screenshots"

    for name, (min_width, min_height) in SCREENSHOTS.items():
        width, height = _png_size(screenshots_dir / name)

        assert width >= min_width, f"{name} width {width} is below {min_width}"
        assert height >= min_height, f"{name} height {height} is below {min_height}"


def test_screenshot_capture_script_checks_full_smoke_data() -> None:
    source = (ROOT / "scripts" / "capture_ui_screenshots.mjs").read_text(encoding="utf-8")

    for name in SCREENSHOTS:
        assert f'name: "{name}"' in source
    for task_key in (
        "RUN-42",
        "RUN-77",
        "RUN-88",
        "RUN-105",
        "RUN-120",
        "RUN-130",
        "RUN-143",
        "RUN-160",
        "RUN-171",
        "RUN-180",
        "RUN-190",
        "RUN-205",
        "RUN-215",
        "RUN-225",
        "RUN-240",
        "RUN-255",
        "RUN-270",
        "RUN-285",
    ):
        assert task_key in source
    assert "fullPage: true" in source
    assert "assertFullPageScreenshotSize" in source
    assert "scrollHeight" in source
    assert "assertTaskTable" in source
    assert "assertTaskStateCoverage" in source
    assert "assertDashboardTasks" in source
    assert "assertDashboardNamespaceCards" in source
    assert "assertSmokeNamespaces" in source
    assert "expectedNamespaceCommands" in source
    assert "assertTaskDetailHistory" in source
    assert "assertLocatorCount" in source
    assert "forbiddenVisibleText" in source
    assert "/Hermes/i" in source
    assert "/Гермес/i" in source
    assert "/project-workflow/i" in source
    assert "sdlc-" in source
    assert "\\bflow-[a-z0-9_-]+\\b" in source
    assert "launch-[a-z0-9_-]+" in source
    assert "\\bsmoke\\b" in source
    assert "Default Namespace" in source
    assert "orchestrator" in source
    assert "codex-operator" in source
    assert "Профиль запуска" in source
    assert "Relevanter" in source
    assert "dueDate" in source
    assert "\\bBusiness\\b" in source
    assert "Business-" in source
    assert "\\bTech\\b" in source
    assert "Tech-" in source
    assert "бизнес" in source
    assert "Maintainer" in source
    assert "desktopViewport" in source
    assert "1920" in source
    assert "1080" in source
    assert 'name: "settings.png"' in source
    assert "workflow-dev step" in source
    assert "КЛЮЧ ЗАПУСКА" in source
    assert "run-dev" in source


def test_screenshot_capture_script_replaces_pngs_only_after_success() -> None:
    source = (ROOT / "scripts" / "capture_ui_screenshots.mjs").read_text(encoding="utf-8")

    assert "fs.mkdtempSync(path.join(outputDir, \".capture-\"))" in source
    assert "fs.copyFileSync(path.join(tempOutputDir, name), path.join(outputDir, name))" in source
    assert "function removeTempOutputDir(tempOutputDir)" in source
    assert "path.relative(outputDir, tempOutputDir)" in source
    assert 'path.basename(tempOutputDir).startsWith(".capture-")' in source
    assert "fs.rmSync(tempOutputDir, { recursive: true, force: true })" in source
    assert "fs.rmSync(path.join(outputDir, name)" not in source
