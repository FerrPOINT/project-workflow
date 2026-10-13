"""Export the generated read-only Base namespace binding owner contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_workflow.interfaces.ui.app import create_app

OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "base-binding-openapi.json"


def base_binding_openapi() -> dict[str, Any]:
    schema = create_app().openapi()
    path = "/internal/runtime/base/namespace-bindings/{namespace_id}"
    paths = {path: schema["paths"][path]}
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
    return {"openapi": schema["openapi"], "info": schema["info"], "paths": paths, "components": {"schemas": components}}


if __name__ == "__main__":
    OUTPUT.write_text(json.dumps(base_binding_openapi(), indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                      encoding="utf-8")
