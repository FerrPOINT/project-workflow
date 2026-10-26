"""Canonical quality commands shared by Make, PowerShell and CI."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

UV = "uv run --python 3.11.15 --frozen --all-extras"
TARGETS = (
    "test", "test-verbose", "test-integration", "coverage", "lint", "quality", "warnings",
    "compose-ready", "unit", "integration", "slow", "release",
)


def verify_constraint_versions(root: Path) -> None:
    """Shared pins must agree; conditional lock-only/build-only nodes are valid."""
    import tomllib

    def normalize(name: str) -> str:
        return re.sub(r"[-_.]+", "-", name).lower()

    pins: dict[str, str] = {}
    for line in (root / "constraints.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", line)
        if not match:
            raise ValueError("Quality constraints require exact name==version pins")
        name, version = normalize(match[1]), match[2]
        if name in pins:
            raise ValueError(f"Duplicate quality constraint: {name}")
        pins[name] = version
    packages = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))["package"]
    if not pins or not packages:
        raise ValueError("Quality lock and constraints must be nonempty")
    for package in packages:
        name = normalize(package["name"])
        if name in pins and package["version"] != pins[name]:
            raise ValueError(
                f"Quality pin mismatch: {name}: uv.lock={package['version']}, constraints={pins[name]}"
            )


def unit_test_paths() -> list[str]:
    root = Path(__file__).resolve().parents[1] / "tests"
    names = json.loads((root / "lanes.json").read_text(encoding="utf-8"))["unit"]
    if not isinstance(names, list) or not names:
        raise ValueError("Unit lane requires a nonempty reviewed file list")
    for name in names:
        if (
            not isinstance(name, str)
            or Path(name).is_absolute()
            or ".." in Path(name).parts
            or not (root / name).resolve().is_relative_to(root)
            or not (root / name).is_file()
        ):
            raise ValueError("Unit lane contains an invalid test path")
    return ["tests/" + name for name in names]


def commands(target: str, *, scoped: bool = False, prepared: bool = False) -> list[list[str]]:
    prefix = [sys.executable, "-m"] if prepared else shlex.split(os.environ.get("WORKFLOW_QUALITY_UV", UV))
    test = ["pytest", "-v" if target == "test-verbose" else "-q", "--timeout=60", "--durations=25"]
    # Filtering markers after collecting every integration module still imports
    # its dependencies. Default builds collect only the reviewed unit files.
    reviewed = (
        unit_test_paths()
        if target in ("unit", "test", "test-verbose", "quality", "warnings") else []
    )
    unit = [*test, "-m", "unit and not integration and not slow", *([] if scoped else reviewed)]
    if scoped and reviewed:
        # Pytest distinguishes positional paths from option values. Use its
        # default collection for flags-only calls without widening explicit paths.
        unit += ["-o", "testpaths=" + shlex.join(reviewed)]
    coverage = [
        "pytest",
        "-q",
        "-n",
        "2",
        "--dist=load",
        "-m",
        "not postgres",
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
        "postgres",
        "tests/test_postgres_integration.py",
        "--timeout=120",
        "--durations=25",
    ]
    lint = [prefix + ["ruff", "check", "."], prefix + ["mypy", "project_workflow", "scripts"]]
    choices = {
        "test": [prefix + unit],
        "test-verbose": [prefix + unit],
        "unit": [prefix + unit],
        "integration": [prefix + test + ["-m", "integration and not slow and not postgres"]],
        "slow": [prefix + test + ["-m", "slow and not postgres"]],
        "test-integration": [prefix + integration],
        "coverage": [prefix + coverage],
        "lint": lint,
        "quality": [prefix + unit, *lint, ["git", "diff", "--check"]],
        "release": [prefix + coverage, prefix + integration, *lint, ["git", "diff", "--check"]],
        "warnings": [
            prefix + unit + ["-W", "error::ResourceWarning", "-W", "error::pytest.PytestUnraisableExceptionWarning"]
        ],
        "compose-ready": [
            ["docker", "compose", "up", "--build", "-d", "--wait"],
            ["curl.exe" if os.name == "nt" else "curl", "--fail", "http://127.0.0.1:8812/health"],
        ],
    }
    return choices[target]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("target", choices=TARGETS, default="quality", nargs="?")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    extra = args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args
    if extra and args.target not in ("test", "unit", "integration", "slow"):
        parser.error("Scoped pytest arguments require a single test lane")
    root = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": os.environ.get(
            "WORKFLOW_QUALITY_ENVIRONMENT", str(root / ".local" / "quality-python" / os.name / "3.11.15")
        ),
    }
    # The workspace shell may pin Python 3.12; uv owns this lane's frozen 3.11 runtime.
    environment.pop("PYTHONHOME", None)
    environment.pop("VIRTUAL_ENV", None)
    if args.prepared and sys.version_info[:3] != (3, 11, 15):
        parser.error("Prepared quality operation requires the pinned Python 3.11.15")
    prefix = shlex.split(os.environ.get("WORKFLOW_QUALITY_UV", UV))
    if args.target != "compose-ready" and (args.prepared or prefix == shlex.split(UV)):
        # A Python 3.10 launcher has no stdlib TOML reader; its pinned 3.11 child
        # validates before any tool. Newer launchers also refuse before uv sync.
        if args.prepared or sys.version_info >= (3, 11):
            try:
                verify_constraint_versions(root)
            except (OSError, ValueError, KeyError, TypeError) as error:
                parser.error(str(error))
    if not args.prepared and args.target != "compose-ready" and prefix == shlex.split(UV):
        # uv prepares one frozen project environment. Every tool
        # then runs inside that operation with the prepared interpreter.
        child = prefix + ["python", str(Path(__file__).resolve()), "--prepared", args.target]
        if extra:
            child += ["--", *extra]
        return subprocess.run(child, cwd=root, env=environment, check=False).returncode
    for command in commands(args.target, scoped=bool(extra), prepared=args.prepared):
        if args.target in ("test", "unit", "integration", "slow"):
            command = [*command, *extra]
        result = subprocess.run(command, cwd=root, env=environment, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
