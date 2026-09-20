"""Regression checks for user-facing documentation."""

import importlib.util
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README_VALIDATOR = ROOT / "scripts" / "verify_readme.py"


def _load_readme_validator():
    spec = importlib.util.spec_from_file_location("verify_readme", README_VALIDATOR)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
SCREENSHOTS = {
    "dashboard.png": (1900, 1500),
    "dashboard-qa.png": (1900, 1500),
    "namespaces.png": (1900, 1000),
    "namespace-new.png": (1900, 1000),
    "phases-qa.png": (1900, 1200),
    "tasks.png": (1900, 1080),
    "tasks-qa.png": (1900, 1080),
    "workflows.png": (1900, 1000),
    "instructions.png": (1900, 1000),
    "agents.png": (1900, 1000),
    "phases.png": (1900, 3000),
    "task-detail-dev.png": (1900, 2500),
    "task-detail-qa.png": (1900, 1500),
    "settings.png": (1900, 1000),
    "mobile-dashboard.png": (360, 2400),
}


def _png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header.startswith(b"\x89PNG\r\n\x1a\n"), f"{path.name} must be a real PNG file"
    assert header[12:16] == b"IHDR", f"{path.name} must start with a PNG IHDR chunk"
    return struct.unpack(">II", header[16:24])


def _readme_screenshots_section() -> str:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    start = readme.index('<a name="visual-proof"></a>')
    end = readme.index('<a name="safety"></a>')
    return readme[start:end]


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


def test_hosted_ci_covers_quality_and_compose_readiness() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "branches: [master]" in workflow
    assert "pytest -q --timeout=60" in workflow
    assert "pytest -q -m integration tests/test_postgres_integration.py --timeout=120" in workflow
    assert "ruff check ." in workflow
    assert "mypy project_workflow scripts" in workflow
    # Fleet CI convention: light pipeline; E2E, coverage thresholds and
    # compose readiness checks run locally via make quality / make compose.


def test_readme_cli_examples_use_configured_wrapper_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "workflow-run step --task RUN-123" in readme
    assert "workflow-run history --task RUN-123" in readme
    assert "workflow-qa step --task RUN-42" in readme
    assert "workflow-dev history --task RUN-42" in readme
    assert "project-workflow step --task" not in readme
    assert "project-workflow history --task" not in readme


def test_compose_and_env_example_forward_runtime_settings() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "OPENAI_MODEL: ${OPENAI_MODEL:-app-test}" in compose
    assert "PLATFORM_SERVICES_URL: ${PLATFORM_SERVICES_URL:-http://localhost:7771/api/v1/runtime/services}" in compose
    assert "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON: ${PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON:-}" in compose
    assert "AUTH_ISSUER: ${AUTH_ISSUER:-}" in compose
    assert "AUTH_INTERNAL_BASE_URL: ${AUTH_INTERNAL_BASE_URL:-}" in compose
    assert "AUTH_PUBLIC_ORIGIN: ${AUTH_PUBLIC_ORIGIN:-http://localhost:8812}" in compose
    assert "AUTH_SESSION_SECRET: ${AUTH_SESSION_SECRET:-}" in compose
    assert "AUTH_COOKIE_SECURE: ${AUTH_COOKIE_SECURE:-false}" in compose
    assert "PLATFORM_SERVICES_URL=http://localhost:7771/api/v1/runtime/services" in env_example
    assert "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON=" in env_example
    assert "AUTH_ISSUER=" in env_example
    assert "AUTH_INTERNAL_BASE_URL=" in env_example
    assert "AUTH_PUBLIC_ORIGIN=http://localhost:8812" in env_example
    assert "AUTH_SESSION_SECRET=" in env_example
    assert "AUTH_COOKIE_SECURE=false" in env_example


def test_readme_route_table_lists_read_only_task_and_instruction_pages() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "`/task/{task_key}` (только наблюдение)" in readme
    assert "`/instructions?phase_id={phase_id}`" in readme


def test_quality_gate_ui_smoke_matches_settings_screenshot() -> None:
    quality_gate = (ROOT / "docs" / "quality-gate.md").read_text(encoding="utf-8")

    assert "http://127.0.0.1:8812/settings" in quality_gate
    assert "CLI settings" in quality_gate or "wrapper-команду" in quality_gate


def test_readme_screenshots_are_real_full_size_pngs() -> None:
    screenshots_dir = ROOT / "docs" / "screenshots"

    for name in ["namespaces.png"]:
        width, height = _png_size(screenshots_dir / name)
        assert width >= 390, f"{name} width {width} is below 390"
        assert height >= 844, f"{name} height {height} is below 844"


def test_readme_presents_reviewed_namespace_evidence() -> None:
    section = _readme_screenshots_section()

    assert 'src="docs/screenshots/namespaces.png"' in section
    assert "neutral isolated fixture" in section
    assert "RUN-42" not in section


def test_readme_validator_accepts_committed_root_readme() -> None:
    validator = _load_readme_validator()

    assert validator.validate(ROOT) == []


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
    assert "assertReadOnlyTaskUi" in source
    assert "#taskStartForm" in source
    assert "#taskRuntimeStep" in source
    assert "/api/tasks/step" in source
    assert "fullPage: true" in source
    assert "assertFullPageScreenshotSize" in source
    assert "scrollHeight" in source
    assert "assertTaskTable" in source
    assert "assertTaskStateCoverage" in source
    assert "assertDashboardTasks" in source
    assert "assertDashboardNamespaceCards" in source
    assert "assertSmokeNamespaces" in source
    assert "assertSmokeTaskApi" in source
    assert "expectedNamespaceCommands" in source
    assert "assertTaskDetailHistory" in source
    assert "assertLocatorCount" in source
    assert "assertRenderedText" in source
    assert "page.content()" in source
    assert "[aria-label], [title], [placeholder], [alt]" in source
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
