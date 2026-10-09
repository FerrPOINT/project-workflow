"""Reader transport contracts against an owned HTTP fixture, not live acceptance."""

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from time import sleep
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from project_workflow.infrastructure.resource_context_reader import OwnerUnavailable, read_owner
from tests.test_resource_context import context


def test_owner_reader_uses_private_credential_and_bounded_nonredirecting_http(monkeypatch, tmp_path):
    calls = []
    payload = {"state": "active"}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.path, self.headers.get("Authorization")))
            path = urlsplit(self.path).path
            if path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/followed")
                self.end_headers()
                return
            code = int(path[1:]) if path[1:].isdigit() else 200
            body = payload if path == "/valid" else ([1] if path == "/array" else "invalid")
            data = (
                b"x" * 65537 if path == "/large" else json.dumps(body).encode() if path != "/invalid" else b"not-json"
            )
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token = tmp_path / "owner-token"
    token.write_text("owner-reader\n")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE__TRACKER_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE__TRACKER_TOKEN_FILE", str(token))
    item = context()
    try:
        assert asyncio.run(read_owner("TRACKER", "valid", item)) == payload
        path, bearer = calls[0]
        assert bearer == "Bearer owner-reader"
        assert parse_qs(urlsplit(path).query) == {
            "registry_instance_id": [str(item.namespace.registry_instance_id)],
            "namespace_id": [str(item.namespace.namespace_id)],
        }
        async def shared_client():
            async with httpx.AsyncClient(follow_redirects=True) as client:
                assert await read_owner("TRACKER", "valid", item, client=client) == payload
                with pytest.raises(OwnerUnavailable):
                    await read_owner("TRACKER", "redirect", item, client=client)

        asyncio.run(shared_client())
        for path in ["redirect", "500", "401", "large", "array", "invalid"]:
            with pytest.raises(OwnerUnavailable):
                asyncio.run(read_owner("TRACKER", path, item))
        for path in ["403", "404"]:
            with pytest.raises(ValueError, match="Foreign or missing"):
                asyncio.run(read_owner("TRACKER", path, item))
        assert all(urlsplit(path).path != "/followed" for path, _ in calls)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    # Network failure remains unavailable; it cannot silently produce an empty context.
    with pytest.raises(OwnerUnavailable):
        asyncio.run(read_owner("TRACKER", "valid", item))


def test_invalid_reader_origin_and_credential_fail_before_network(monkeypatch, tmp_path):
    item = context()
    for url in [
        "",
        "ftp://example.test",
        "http://user:secret@example.test",
        "http://example.test/path",
        "http://example.test/?q=x",
        "http://example.test/#fragment",
        "http://example.test:bad",
        "http://[",
    ]:
        monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE__TRACKER_URL", url)
        with pytest.raises(OwnerUnavailable, match="configured"):
            asyncio.run(read_owner("TRACKER", "valid", item))
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE__TRACKER_URL", "http://127.0.0.1:1")
    monkeypatch.delenv("PROJECT_WORKFLOW_NAMESPACE__TRACKER_TOKEN_FILE", raising=False)
    with pytest.raises(OwnerUnavailable, match="credential"):
        asyncio.run(read_owner("TRACKER", "valid", item))
    path = tmp_path / "missing"
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE__TRACKER_TOKEN_FILE", str(path))
    with pytest.raises(OwnerUnavailable, match="credential"):
        asyncio.run(read_owner("TRACKER", "valid", item))
    for token in [b"", b"one\ntwo", b"\xff", "я".encode(), b"one\x00two", b"one two"]:
        path.write_bytes(token)
        with pytest.raises(OwnerUnavailable, match="credential"):
            asyncio.run(read_owner("TRACKER", "valid", item))


def test_streaming_reader_has_total_deadline_and_accepts_fast_response(monkeypatch, tmp_path):
    from project_workflow.infrastructure import resource_context_reader as reader

    monkeypatch.setattr(reader, "READER_TIMEOUT_SECONDS", 0.12, raising=False)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = b'{"state":"active"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            delay = 0.08 if urlsplit(self.path).path == "/slow" else 0.01
            try:
                for part in (payload[:5], payload[5:]):
                    sleep(delay)
                    self.wfile.write(part)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token = tmp_path / "reader-token"
    token.write_text("owned-reader")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE__TRACKER_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE__TRACKER_TOKEN_FILE", str(token))
    try:
        assert asyncio.run(read_owner("TRACKER", "fast", context())) == {"state": "active"}
        with pytest.raises(OwnerUnavailable, match="deadline"):
            asyncio.run(read_owner("TRACKER", "slow", context()))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
