"""The SSR bridge forwards only a bounded public branding response."""

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from starlette.requests import Request

from project_workflow.interfaces.ui import platform_branding as bridge


def request(etag=None):
    return Request(
        {
            "type": "http",
            "headers": [(b"authorization", b"Bearer fictional-preview"), (b"cookie", b"session=fictional-preview")]
            + ([(b"if-none-match", etag.encode())] if etag else []),
        }
    )


@pytest.mark.parametrize(
    "configured,catalog,expected",
    [
        (None, "http://admin/api/v1/runtime/services", "http://admin/api/v1/runtime/branding"),
        (None, "http://admin/custom", None),
        ("", "http://admin/api/v1/runtime/services", None),
        ("http://admin/brand", "http://admin/custom", "http://admin/brand"),
    ],
)
def test_branding_source_is_explicit_or_derived_only_from_known_contract(configured, catalog, expected):
    settings = SimpleNamespace(PLATFORM_BRANDING_URL=configured, PLATFORM_SERVICES_URL=catalog)
    with patch.object(bridge, "get_settings", return_value=settings):
        assert bridge.branding_url() == expected


@pytest.mark.parametrize("status", [200, 304, 404, 500, 302])
def test_public_response_and_validator_are_forwarded_without_credentials(status):
    import asyncio

    calls = []

    def upstream(req):
        calls.append(req)
        return httpx.Response(
            status,
            content=b'{"revision":2}' if status == 200 else b"",
            headers={"ETag": '"r2"', "Set-Cookie": "private=secret", "Content-Type": "application/json"},
        )

    factory = httpx.AsyncClient
    with (
        patch.object(bridge, "branding_url", return_value="http://admin/brand"),
        patch.object(
            bridge.httpx, "AsyncClient", side_effect=lambda **kw: factory(transport=httpx.MockTransport(upstream), **kw)
        ),
    ):
        response = asyncio.run(bridge.platform_branding(request('"r1"')))
    assert response.status_code == (status if status in {200, 304, 404} else 502)
    assert "set-cookie" not in response.headers
    assert calls[0].headers["if-none-match"] == '"r1"'
    assert "authorization" not in calls[0].headers
    assert "cookie" not in calls[0].headers
    if status == 200:
        assert response.body == b'{"revision":2}'
        assert response.headers["etag"] == '"r2"'


@pytest.mark.parametrize("kind,expected", [("unavailable", 503), ("oversized", 502), ("disabled", 404)])
def test_failures_do_not_replace_cached_configuration(kind, expected):
    import asyncio

    def upstream(req):
        if kind == "unavailable":
            raise httpx.ConnectError("unavailable", request=req)
        return httpx.Response(200, content=b"x" * 65537, headers={"Content-Type": "application/json"})

    factory = httpx.AsyncClient
    with (
        patch.object(bridge, "branding_url", return_value=None if kind == "disabled" else "http://admin/brand"),
        patch.object(
            bridge.httpx, "AsyncClient", side_effect=lambda **kw: factory(transport=httpx.MockTransport(upstream), **kw)
        ),
    ):
        response = asyncio.run(bridge.platform_branding(request()))
    assert response.status_code == expected


@pytest.mark.parametrize("media_type", ["text/html", "text/javascript", ""])
def test_never_serves_upstream_active_content_on_the_workflow_origin(media_type):
    import asyncio

    factory = httpx.AsyncClient

    def upstream(req):
        return httpx.Response(200, content=b"<script>unexpected()</script>", headers={"Content-Type": media_type})

    with (
        patch.object(bridge, "branding_url", return_value="http://admin/brand"),
        patch.object(
            bridge.httpx, "AsyncClient", side_effect=lambda **kw: factory(transport=httpx.MockTransport(upstream), **kw)
        ),
    ):
        response = asyncio.run(bridge.platform_branding(request()))
    assert response.status_code == 502
    assert response.body == b""


def test_registered_route_uses_the_bridge_without_forwarding_browser_credentials(monkeypatch):
    from fastapi.testclient import TestClient

    from project_workflow.config import get_settings
    from project_workflow.interfaces.ui.app import create_app

    monkeypatch.setenv("AUTH_ISSUER", "")
    get_settings.cache_clear()
    calls = []
    factory = httpx.AsyncClient

    def upstream(req):
        calls.append(req)
        return httpx.Response(200, json={"revision": 2}, headers={"ETag": '"r2"'})

    with (
        patch.object(bridge, "branding_url", return_value="http://admin/brand"),
        patch.object(
            bridge.httpx, "AsyncClient", side_effect=lambda **kw: factory(transport=httpx.MockTransport(upstream), **kw)
        ),
        TestClient(create_app()) as client,
    ):
        response = client.get(
            "/api/platform/branding", headers={"If-None-Match": '"r1"', "Cookie": "session=fictional-preview"}
        )
    assert response.status_code == 200
    assert response.json() == {"revision": 2}
    assert calls[0].headers["if-none-match"] == '"r1"'
    assert "cookie" not in calls[0].headers


@pytest.mark.parametrize("media_type", ["application/json", "Application/Vnd.Branding+JSON; charset=utf-8"])
def test_accepts_an_exactly_64kib_json_response(media_type):
    import asyncio

    body = b'{"x":"' + b"x" * 65528 + b'"}'
    assert len(body) == 65536
    factory = httpx.AsyncClient
    with (
        patch.object(bridge, "branding_url", return_value="http://admin/brand"),
        patch.object(
            bridge.httpx,
            "AsyncClient",
            side_effect=lambda **kw: factory(
                transport=httpx.MockTransport(
                    lambda req: httpx.Response(200, content=body, headers={"Content-Type": media_type})
                ),
                **kw,
            ),
        ),
    ):
        response = asyncio.run(bridge.platform_branding(request()))
    assert response.status_code == 200
    assert response.body == body


@pytest.mark.parametrize("status", [304, 404])
def test_cache_and_absence_responses_do_not_forward_upstream_html(status):
    import asyncio

    factory = httpx.AsyncClient
    with (
        patch.object(bridge, "branding_url", return_value="http://admin/brand"),
        patch.object(
            bridge.httpx,
            "AsyncClient",
            side_effect=lambda **kw: factory(
                transport=httpx.MockTransport(
                    lambda req: httpx.Response(
                        status,
                        content=b"<script>unexpected()</script>",
                        headers={"Content-Type": "text/html", "ETag": '"r2"'},
                    )
                ),
                **kw,
            ),
        ),
    ):
        response = asyncio.run(bridge.platform_branding(request()))
    assert response.status_code == status
    assert response.body == b""
    assert response.headers["etag"] == '"r2"'
    assert "content-type" not in response.headers


def test_does_not_follow_redirects_to_a_different_origin():
    import asyncio

    calls = []
    factory = httpx.AsyncClient

    def upstream(req):
        calls.append(req)
        return httpx.Response(302, headers={"Location": "https://outside.example/other"})

    with (
        patch.object(bridge, "branding_url", return_value="http://admin/brand"),
        patch.object(
            bridge.httpx, "AsyncClient", side_effect=lambda **kw: factory(transport=httpx.MockTransport(upstream), **kw)
        ),
    ):
        response = asyncio.run(bridge.platform_branding(request()))
    assert response.status_code == 502
    assert len(calls) == 1


@pytest.mark.parametrize(
    "source,expected", [(None, None), ("http://configured/branding", "/workflow/api/platform/branding")]
)
def test_browser_runtime_uses_the_configured_same_origin_bridge(source, expected):
    from project_workflow.interfaces.ui import templates as ui_templates

    with (
        patch.object(bridge, "branding_url", return_value=source),
        patch.object(ui_templates, "get_settings", return_value=SimpleNamespace(UI_BASE_PATH="/workflow/")),
    ):
        assert ui_templates._platform_branding_url() == expected


def test_total_deadline_bounds_a_slow_stream_even_when_each_chunk_is_timely(monkeypatch):
    import asyncio

    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(0.01)
                yield b" "

    factory = httpx.AsyncClient
    monkeypatch.setattr(bridge, "BRANDING_TIMEOUT_SECONDS", 0.025)
    with (
        patch.object(bridge, "branding_url", return_value="http://admin/brand"),
        patch.object(
            bridge.httpx,
            "AsyncClient",
            side_effect=lambda **kw: factory(
                transport=httpx.MockTransport(
                    lambda req: httpx.Response(200, stream=SlowBody(), headers={"Content-Type": "application/json"})
                ),
                **kw,
            ),
        ),
    ):
        response = asyncio.run(bridge.platform_branding(request()))
    assert response.status_code == 503
    assert response.body == b""


@pytest.mark.parametrize("slow", [False, True])
def test_total_deadline_uses_the_python310_asyncio_contract(monkeypatch, slow):
    import asyncio

    # Do not modify the event loop module globally: emulate only the API
    # available to the bridge on the declared minimum Python version.
    monkeypatch.setattr(
        bridge, "asyncio", SimpleNamespace(wait_for=asyncio.wait_for, TimeoutError=asyncio.TimeoutError)
    )
    monkeypatch.setattr(bridge, "BRANDING_TIMEOUT_SECONDS", 0.01)
    factory = httpx.AsyncClient

    async def upstream(req):
        if slow:
            await asyncio.sleep(0.1)
        return httpx.Response(200, json={"revision": 2})

    with (
        patch.object(bridge, "branding_url", return_value="http://admin/brand"),
        patch.object(
            bridge.httpx, "AsyncClient", side_effect=lambda **kw: factory(transport=httpx.MockTransport(upstream), **kw)
        ),
    ):
        response = asyncio.run(bridge.platform_branding(request()))
    assert response.status_code == (503 if slow else 200)
