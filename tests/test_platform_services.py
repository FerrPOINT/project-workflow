"""Platform service catalog switcher (catalog v1.1)."""
from pathlib import Path

from project_workflow.interfaces.ui.platform_services import (
    _normalize,
    load_other_services,
)


def test_normalize_skips_api_only_and_current():
    assert _normalize({"key": "project-workflow", "label": "PW", "url": "http://x", "ui_url": "http://x"}) is None
    assert _normalize({"key": "java-agent", "label": "JA", "url": "http://x:7761", "ui_url": None}) is None
    assert _normalize(
        {"key": "wiki", "label": "Wiki", "url": "http://x", "ui_url": "http://x:7732", "health": "healthy"}
    ) == {"key": "wiki", "label": "Wiki", "url": "http://x:7732", "health": "healthy"}


def test_normalize_degrades_unknown_health():
    entry = _normalize({"key": "a", "label": "A", "url": "http://a", "ui_url": "http://a", "health": "weird"})
    assert entry is not None and entry["health"] == "unknown"


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


def test_service_switcher_is_accessible_and_localizes_health():
    template = (Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/base.html").read_text(
        encoding="utf-8"
    )

    assert 'class="service-menu-popover" role="menu"' in template
    assert 'aria-current="page"' in template
    assert "Project Workflow" in template
    assert "Состояние неизвестно" in template
    assert "event.key==='Escape'" in template
    assert ".service-menu-popover{left:0;right:auto}" in template


def test_fallback_on_unreachable_catalog(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("down")

    import project_workflow.interfaces.ui.platform_services as ps

    monkeypatch.setattr(ps, "_cached_services", [], raising=False)
    monkeypatch.setattr(ps, "urlopen", boom)
    services = load_other_services("http://127.0.0.1:1/api")
    assert services  # fail-safe fallback
