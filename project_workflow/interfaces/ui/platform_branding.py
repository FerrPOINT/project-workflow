"""Same-origin bridge to the configured public Base branding document."""

from __future__ import annotations

import asyncio

import httpx
from fastapi import Request
from starlette.responses import Response

from ...config import get_settings

BRANDING_TIMEOUT_SECONDS = 2.0


def branding_url() -> str | None:
    settings = get_settings()
    if settings.PLATFORM_BRANDING_URL is not None:
        return settings.PLATFORM_BRANDING_URL or None
    catalog = settings.PLATFORM_SERVICES_URL
    suffix = "/api/v1/runtime/services"
    return catalog.removesuffix(suffix) + "/api/v1/runtime/branding" if catalog.endswith(suffix) else None


async def platform_branding(request: Request) -> Response:
    url = branding_url()
    if not url:
        return Response(status_code=404)
    headers = {}
    validator = request.headers.get("if-none-match")
    if validator:
        headers["If-None-Match"] = validator
    try:
        async with asyncio.timeout(BRANDING_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(timeout=BRANDING_TIMEOUT_SECONDS, follow_redirects=False) as client:
                async with client.stream("GET", url, headers=headers) as upstream:
                    if upstream.status_code not in {200, 304, 404}:
                        return Response(status_code=502)
                    forwarded = {
                        key: value
                        for key, value in upstream.headers.items()
                        if key.lower() in {"etag", "cache-control"}
                        or (upstream.status_code == 200 and key.lower() == "content-type")
                    }
                    if upstream.status_code in {304, 404}:
                        return Response(status_code=upstream.status_code, headers=forwarded)
                    media_type = upstream.headers.get("content-type", "").partition(";")[0].strip().lower()
                    if media_type != "application/json" and not media_type.endswith("+json"):
                        return Response(status_code=502)
                    body = bytearray()
                    async for chunk in upstream.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 65536:
                            return Response(status_code=502)
                    return Response(bytes(body), status_code=upstream.status_code, headers=forwarded)
    except (httpx.HTTPError, ValueError, TimeoutError):
        return Response(status_code=503)
