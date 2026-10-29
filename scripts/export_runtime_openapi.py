"""Export the common Workflow CLI/API contract from its actual route models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from project_workflow.interfaces.ui.app import create_app

OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "runtime-openapi.json"
RUNTIME_PATHS = {
    "/internal/runtime/capabilities", "/internal/runtime/assign", "/internal/runtime/step",
    "/internal/runtime/history", "/internal/runtime/terminal-receipt/readback",
}


def runtime_openapi() -> dict[str, Any]:
    schema = create_app().openapi()
    paths = {path: schema["paths"][path] for path in sorted(RUNTIME_PATHS)}
    components: dict[str, Any] = {}

    def include_refs(value: Any) -> None:
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[-1]
                if name not in components:
                    components[name] = schema["components"]["schemas"][name]
                    include_refs(components[name])
            for item in value.values():
                include_refs(item)
        elif isinstance(value, list):
            for item in value:
                include_refs(item)

    include_refs(paths)
    return {"openapi": schema["openapi"], "info": schema["info"], "paths": paths,
            "components": {"schemas": components}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(runtime_openapi(), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if args.check:
        return 0 if OUTPUT.read_text(encoding="utf-8") == expected else 1
    OUTPUT.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
