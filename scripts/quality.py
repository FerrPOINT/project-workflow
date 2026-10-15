"""Canonical quality commands shared by Make, PowerShell and CI."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
from pathlib import Path

UV = "uv run --python 3.11.15 --frozen --with-requirements constraints.txt --all-extras"
TARGETS = ("test", "test-integration", "coverage", "lint", "quality", "warnings", "compose-ready")


def commands(target: str) -> list[list[str]]:
    prefix = shlex.split(os.environ.get("UV", UV))
    test = ["pytest", "-q", "--timeout=60", "--durations=25"]
    coverage = [
        "pytest",
        "-q",
        "--cov=project_workflow",
        "--cov-report=term",
        "--cov-report=xml",
        "--timeout=60",
        "--durations=25",
        "-W",
        "error::ResourceWarning",
        "-W",
        "error::pytest.PytestUnraisableExceptionWarning",
    ]
    integration = [
        "pytest",
        "-q",
        "-m",
        "integration",
        "tests/test_postgres_integration.py",
        "--timeout=120",
        "--durations=25",
    ]
    lint = [prefix + ["ruff", "check", "."], prefix + ["mypy", "project_workflow", "scripts"]]
    choices = {
        "test": [prefix + test],
        "test-integration": [prefix + integration],
        "coverage": [prefix + coverage],
        "lint": lint,
        "quality": [prefix + coverage, prefix + integration, *lint, ["git", "diff", "--check"]],
        "warnings": [
            prefix + test + ["-W", "error::ResourceWarning", "-W", "error::pytest.PytestUnraisableExceptionWarning"]
        ],
        "compose-ready": [
            ["docker", "compose", "up", "--build", "-d", "--wait"],
            ["curl.exe" if os.name == "nt" else "curl", "--fail", "http://127.0.0.1:8812/health"],
        ],
    }
    return choices[target]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=TARGETS, default="quality", nargs="?")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    extra = args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args
    if extra and args.target != "test":
        parser.error("Scoped pytest arguments require target test")
    root = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": os.environ.get(
            "WORKFLOW_QUALITY_ENVIRONMENT", str(root / ".local" / "quality-python" / os.name / "3.11.15")
        ),
    }
    for command in commands(args.target):
        if args.target == "test":
            command = [*command, *extra]
        result = subprocess.run(command, cwd=root, env=environment, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
