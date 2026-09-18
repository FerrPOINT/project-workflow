#!/usr/bin/env python3
"""Install or verify the complete seven-namespace Hermes configuration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.install_hermes_workflow import install, load_bundle

ROLES = (
    "project_manager",
    "analyst",
    "architect",
    "developer",
    "reviewer",
    "tester",
    "devops",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-root", type=Path, default=Path("configs/hermes"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    paths = sorted(args.config_root.glob("*.json"))
    if [path.stem for path in paths] != sorted(ROLES):
        raise SystemExit("config root must contain exactly seven canonical role bundles")
    bundles = {bundle["role"]: bundle for bundle in (load_bundle(path) for path in paths)}
    results = []
    for role in ROLES:
        variable = f"PROJECT_WORKFLOW_{role.upper()}_DATABASE_URL"
        database_url = os.environ.get(variable, "").strip()
        if not database_url:
            raise SystemExit(f"missing database URL in {variable}")
        results.append(install(bundles[role], check_only=args.check, database_url=database_url))
    print(json.dumps(results, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
