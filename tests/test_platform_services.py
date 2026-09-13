"""Platform service catalog switcher (catalog v1.1)."""
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


def test_fallback_on_unreachable_catalog(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("down")

    import project_workflow.interfaces.ui.platform_services as ps

    monkeypatch.setattr(ps, "_cached_services", [], raising=False)
    monkeypatch.setattr(ps, "urlopen", boom)
    services = load_other_services("http://127.0.0.1:1/api")
    assert services  # fail-safe fallback
