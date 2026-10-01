"""Platform service catalog switcher (catalog v1.1)."""
import io
import json
from pathlib import Path

import pytest

from project_workflow.interfaces.ui.platform_services import (
    _normalize,
    load_other_services,
    load_service_catalog,
)


def test_normalize_skips_only_api_services_and_keeps_current_health():
    assert _normalize({"key": "project-workflow", "label": "PW", "ui_url": "http://x", "health": "unreachable"}) == {
        "key": "project-workflow", "label": "PW", "url": "http://x", "health": "unreachable",
    }
    assert _normalize({"key": "java-agent", "label": "JA", "url": "http://x:7761", "ui_url": None}) is None
    assert _normalize(
        {"key": "wiki", "label": "Wiki", "url": "http://x", "ui_url": "http://x:7732", "health": "healthy"}
    ) == {"key": "wiki", "label": "Wiki", "url": "http://x:7732", "health": "healthy"}


@pytest.mark.parametrize("health", ["weird", None, [], {}])
def test_normalize_degrades_unknown_health(health):
    entry = _normalize({"key": "a", "label": "A", "url": "http://a", "ui_url": "http://a", "health": health})
    assert entry is not None and entry["health"] == "unknown"


@pytest.mark.parametrize("url", ["http://", "http://user:password@host", "http://host:bad", "javascript:alert(1)"])
def test_normalize_rejects_invalid_or_credential_bearing_navigation_targets(url):
    assert _normalize({"key": "wiki", "label": "Wiki", "ui_url": url}) is None


def test_fallback_without_catalog_url():
    services = load_other_services(None)
    assert all(s["key"] != "project-workflow" for s in services)
    assert len(services) >= 5


def test_fallback_reuses_remote_request_host():
    services = load_other_services(None, request_url="http://192.168.1.135:8811/tasks")

    assert {service["url"] for service in services} == {
        "http://192.168.1.135:7712",
        "http://192.168.1.135:7722",
        "http://192.168.1.135:7732",
        "http://192.168.1.135:7742",
        "http://192.168.1.135:7772",
    }


def test_fallback_preserves_localhost_without_request_url():
    services = load_other_services(None)
    assert all("localhost" in str(service["url"]) for service in services)


@pytest.mark.parametrize("request_url", [
    "http://localhost:8812/",
    "http://127.0.0.1:8812/",
    "http://[::1]:8812/",
])
def test_local_browsing_preserves_canonical_service_origins(request_url):
    services = load_other_services(None, request_url=request_url)

    assert {service["url"] for service in services} == {
        service["url"] for service in load_other_services(None)
    }


def test_service_switcher_is_accessible_and_localizes_health():
    template = (Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/base.html").read_text(
        encoding="utf-8"
    )

    assert '<div role="menu" aria-label="Сервисы платформы">' in template
    assert '{% endfor %}\n          </div>\n          {% set catalog_source' in template
    assert 'aria-current="page"' in template
    assert "Project Workflow" in template
    assert "Состояние неизвестно" in template
    assert "event.key==='Escape'" in template
    assert ".service-menu-popover{position:absolute;left:0;right:auto;" in template


def test_shell_controls_have_mobile_touch_targets_and_sidebar_focus_management():
    template = (Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/base.html").read_text(
        encoding="utf-8"
    )

    assert ".service-menu summary{height:40px" in template
    assert ".namespace-icon-action{width:40px;height:40px" in template
    assert ".sidebar-link{display:flex;min-height:44px" in template
    assert ".sidebar-logout{display:none;min-width:40px;min-height:40px" in template
    assert 'aria-label="Открыть навигацию" aria-controls="sidebar" aria-expanded="false"' in template
    assert 'aria-label="Закрыть навигацию"' in template
    assert "sidebar.inert=dialogOpen||(mobile&&!sidebar.classList.contains('open'))" in template
    assert "main.inert=dialogOpen||(mobile&&sidebar.classList.contains('open'))" in template
    assert "setAttribute('aria-label','Закрыть навигацию')" in template
    assert "if(event.key==='Tab'&&sidebar.classList.contains('open'))" in template


def test_fallback_on_unreachable_catalog(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("down")

    import project_workflow.interfaces.ui.platform_services as ps

    monkeypatch.setattr(ps, "_cached_services", [], raising=False)
    monkeypatch.setattr(ps, "urlopen", boom)
    services = load_other_services("http://127.0.0.1:1/api")
    assert services  # fail-safe fallback
    assert load_service_catalog("http://127.0.0.1:1/api").source == "fallback-unreachable"


def test_runtime_catalog_order_and_source(monkeypatch):
    import project_workflow.interfaces.ui.platform_services as ps

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    payload = {"services": [
        {"key": "wiki", "label": "Wiki", "ui_url": "http://localhost:7732"},
        {"key": "admin-panel", "label": "Admin Panel", "ui_url": "http://localhost:7772"},
        {"key": "java-agent", "label": "Java Agent", "ui_url": None},
    ]}
    monkeypatch.setattr(ps, "_cached_services", [], raising=False)
    monkeypatch.setattr(ps, "urlopen", lambda *_args, **_kwargs: Response(json.dumps(payload).encode()))
    catalog = load_service_catalog("http://admin/api", request_url="http://127.0.0.1:8812/tasks")
    assert catalog.source == "runtime"
    assert [service["key"] for service in catalog.services] == ["admin-panel", "wiki"]
    assert [service["url"] for service in catalog.services] == [
        "http://localhost:7772", "http://localhost:7732",
    ]


def test_malformed_runtime_catalog_uses_invalid_fallback(monkeypatch):
    import project_workflow.interfaces.ui.platform_services as ps

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(ps, "_cached_services", [], raising=False)
    for body in (b"not-json", b'{"services": {}}', b'{"services": [{"key": 1}]}'):
        monkeypatch.setattr(ps, "urlopen", lambda *_args, **_kwargs: Response(body))
        catalog = load_service_catalog("http://admin/api")
        assert catalog.source == "fallback-invalid"
        assert len(catalog.services) == 6

    monkeypatch.setattr(ps, "urlopen", lambda *_args, **_kwargs: Response(b'{"services": []}'))
    assert load_service_catalog("http://admin/api").source == "fallback-empty"


@pytest.fixture(autouse=True)
def isolated_catalog_cache(monkeypatch):
    from project_workflow.interfaces.ui import platform_services as ps

    monkeypatch.setattr(ps, "_cached_services", [])
    monkeypatch.setattr(ps, "_cached_at", 0.0)
    monkeypatch.setattr(ps, "_cached_url", None)


def test_catalog_fallback_contains_six_ordered_ui_with_unknown_current_health():
    catalog = load_service_catalog(None)
    assert catalog.source == "fallback-unreachable"
    assert [service["key"] for service in catalog.services] == [
        "admin-panel", "ci-cd", "task-tracker", "wiki", "fleet-control", "project-workflow",
    ]
    assert {service["health"] for service in catalog.services} == {"unknown"}
    assert catalog.services[-1]["url"] == "http://localhost:7752"
    assert len(load_other_services(None)) == 5


def _response(services):
    return io.BytesIO(json.dumps({"services": services}).encode())


def _runtime_services():
    return [
        {"key": "project-workflow", "label": "PW", "ui_url": "http://localhost:7752", "health": "unreachable"},
        {"key": "wiki", "label": "Wiki", "ui_url": "http://localhost:7732", "health": "healthy"},
        {"key": "central-auth", "label": "Auth", "ui_url": None},
    ]


@pytest.mark.parametrize("failure,expected_source", [
    (None, "fallback-unreachable"),
    ([], "fallback-empty"),
    ([{"key": "bad"}], "fallback-invalid"),
])
def test_expired_runtime_failure_uses_unknown_fallback_and_recovers(monkeypatch, failure, expected_source):
    from project_workflow.interfaces.ui import platform_services as ps

    now = [100.0]
    monkeypatch.setattr(ps.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(ps, "urlopen", lambda *_args, **_kwargs: _response(_runtime_services()))
    first = load_service_catalog("http://admin/api")
    assert first.source == "runtime"
    assert first.services[-1]["key"] == "project-workflow"
    assert first.services[-1]["health"] == "unreachable"
    now[0] += 61

    def failed(*_args, **_kwargs):
        if failure is None:
            raise OSError("catalog unavailable")
        return _response(failure)

    monkeypatch.setattr(ps, "urlopen", failed)
    fallback = load_service_catalog("http://admin/api")
    assert fallback.source == expected_source
    assert len(fallback.services) == 6
    assert {service["health"] for service in fallback.services} == {"unknown"}
    monkeypatch.setattr(ps, "urlopen", lambda *_args, **_kwargs: _response(_runtime_services()))
    restored = load_service_catalog("http://admin/api")
    assert restored == first


def test_catalog_cache_is_scoped_to_url_and_respects_ttl(monkeypatch):
    from project_workflow.interfaces.ui import platform_services as ps

    calls = []
    now = [100.0]
    monkeypatch.setattr(ps.time, "monotonic", lambda: now[0])

    def response(url, **_kwargs):
        calls.append(url)
        return _response(_runtime_services())

    monkeypatch.setattr(ps, "urlopen", response)
    load_service_catalog("http://admin-a/api")
    load_service_catalog("http://admin-a/api")
    assert calls == ["http://admin-a/api"]
    load_service_catalog("http://admin-b/api")
    assert calls[-1] == "http://admin-b/api"
    now[0] += 61
    load_service_catalog("http://admin-b/api")
    assert len(calls) == 3


@pytest.mark.parametrize("invalid", [None, {"key": "wiki", "label": "Duplicate", "ui_url": "http://x"},
                                     {"key": "broken", "label": "Broken", "ui_url": "javascript:alert(1)"}])
def test_mixed_invalid_catalog_does_not_silently_drop_bad_rows(monkeypatch, invalid):
    from project_workflow.interfaces.ui import platform_services as ps

    monkeypatch.setattr(ps, "urlopen", lambda *_args, **_kwargs: _response([*_runtime_services(), invalid]))
    catalog = load_service_catalog("http://admin/api")
    assert catalog.source == "fallback-invalid"
    assert len(catalog.services) == 6


def test_rendered_switcher_uses_current_runtime_health_without_duplicate(monkeypatch):
    from project_workflow.interfaces.ui import platform_services as ps
    from project_workflow.interfaces.ui.templates import templates

    monkeypatch.setattr(ps, "urlopen", lambda *_args, **_kwargs: _response(_runtime_services()))
    catalog = load_service_catalog("http://admin/api")
    html = templates.get_template("base.html").render(
        page="tasks", other_services=catalog.services, services_source=catalog.source,
    )
    menu = html.split('id="serviceMenu"', 1)[1].split("</details>", 1)[0]
    assert menu.count('aria-current="page"') == 1
    assert 'service-health unreachable' in menu
    assert 'service-health healthy' in menu
    assert 'service-health unknown' not in menu
    assert 'Project Workflow' not in menu  # runtime label is PW, not a fabricated replacement
    assert 'Central Auth' not in menu
    assert 'href="/" role="menuitem" aria-current="page"' in menu
