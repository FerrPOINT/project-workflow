"""Fixed owner endpoints and limited service credentials, never a forwarded user PAT."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from project_workflow.domain.resource_context import ExecutionContextV2


class OwnerUnavailable(RuntimeError):
    pass


async def read_owner(owner: str, path: str, context: ExecutionContextV2) -> dict:
    prefix = f"PROJECT_WORKFLOW_NAMESPACE__{owner}"
    url = os.environ.get(f"{prefix}_URL", "")
    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError:
        raise OwnerUnavailable("Context reader is not configured") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise OwnerUnavailable("Context reader is not configured")
    try:
        token = Path(os.environ[f"{prefix}_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
    except (KeyError, OSError, UnicodeError):
        raise OwnerUnavailable("Context reader credential is unavailable") from None
    if not token or not token.isascii() or any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise OwnerUnavailable("Context reader credential is invalid")
    params = {
        "registry_instance_id": str(context.namespace.registry_instance_id),
        "namespace_id": str(context.namespace.namespace_id),
    }
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            async with client.stream(
                "GET", url.rstrip("/") + "/" + path, params=params, headers={"Authorization": f"Bearer {token}"}
            ) as response:
                if response.status_code in {403, 404}:
                    raise ValueError("Foreign or missing context resource")
                if response.status_code != 200:
                    raise OwnerUnavailable("Context owner is unavailable")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > 65536:
                        raise OwnerUnavailable("Invalid context owner readback")
                    data.extend(chunk)
    except httpx.RequestError:
        raise OwnerUnavailable("Context owner is unavailable") from None
    try:
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise OwnerUnavailable("Invalid context owner readback") from None
