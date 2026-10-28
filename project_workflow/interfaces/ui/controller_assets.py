"""Immutable, request-independent controller assets for the SSR owner UI."""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
from pathlib import Path

from fastapi import HTTPException
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from starlette.responses import Response

from project_workflow.domain.project_theme import DEFAULT_PROJECT_ICON

CONTROLLERS = ("namespaces", "workflows", "phase_detail", "instructions")
_environment = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                           undefined=StrictUndefined, autoescape=False)


@lru_cache(maxsize=len(CONTROLLERS) * 2)
def controller_source(name: str, administration: bool) -> tuple[bytes, str]:
    # Only a fixed role variant is rendered here. User/view data belongs exclusively
    # to the private no-store HTML configuration, never to this public cache.
    if name not in CONTROLLERS:
        raise ValueError("Unknown page controller")
    from .templates import PROJECT_ICON_PATHS

    body = _environment.get_template(f"controllers/{name}.js").render(
        can_administer=administration, icon_paths=PROJECT_ICON_PATHS, default_icon=DEFAULT_PROJECT_ICON,
    ).encode()
    return body, sha256(body).hexdigest()


def page_controller_assets(administration: bool) -> list[str]:
    variant = "admin" if administration else "user"
    return [f"/ui-assets/controllers/{variant}/{controller_source(name, administration)[1]}/{name}.js"
            for name in CONTROLLERS]


def controller_response(variant: str, digest: str, name: str) -> Response:
    if variant not in {"admin", "user"} or name not in CONTROLLERS:
        raise HTTPException(404)
    body, expected = controller_source(name, variant == "admin")
    if digest != expected:
        raise HTTPException(404)
    return Response(body, media_type="text/javascript",
                    headers={"Cache-Control": "public, max-age=31536000, immutable", "ETag": f'"{expected}"'})
