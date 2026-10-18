from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from project_workflow.config import Settings, get_settings
from project_workflow.interfaces.ui.sso import install_sso


@pytest.mark.parametrize("prefix", ["", "/workflow"])
def test_public_login_uses_configured_callback_and_cookie_path(monkeypatch, prefix):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("AUTH_ISSUER", "https://dev.example.test")
    monkeypatch.setenv("AUTH_PUBLIC_ORIGIN", "https://dev.example.test")
    monkeypatch.setenv("AUTH_INTERNAL_BASE_URL", "http://auth:7701")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "a-test-session-secret-with-more-than-32-characters")
    monkeypatch.setenv("UI_BASE_PATH", prefix)
    get_settings.cache_clear()
    try:
        app = FastAPI()
        install_sso(app)
        with TestClient(app, base_url="https://dev.example.test", follow_redirects=False) as client:
            response = client.get("/login", params={"next": "/tasks"})
            assert response.status_code == 303
            query = parse_qs(urlsplit(response.headers["location"]).query)
            assert query["redirect_uri"] == ["https://dev.example.test" + prefix + "/sso/callback"]
            assert "Path=" + prefix + "/sso/callback" in response.headers["set-cookie"]
            assert query["client_id"] == ["project-workflow"]
            assert query["code_challenge_method"] == ["S256"]
            response = client.get("/tasks")
            assert response.status_code == 303
            assert urlsplit(response.headers["location"]).path == prefix + "/login"
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("prefix", ["//evil.example", "/workflow/../admin", "/workflow?next=x", "/workflow/nested"])
def test_deployment_prefix_rejects_nonlocal_or_ambiguous_paths(prefix):
    with pytest.raises(ValueError):
        Settings(DATABASE_URL="sqlite+pysqlite:///:memory:", UI_BASE_PATH=prefix)
