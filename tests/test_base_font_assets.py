"""Rendered Base CSS must resolve the packaged fonts through the public prefix."""

import re
from pathlib import Path

import pytest

from project_workflow.config import get_settings
from tests import test_ui_api as ui_fixtures

pytestmark = pytest.mark.ui
client = ui_fixtures.client


@pytest.mark.parametrize("prefix", ["", "/workflow"])
def test_rendered_base_font_urls_are_css_strings_and_serve_packaged_bytes(client, monkeypatch, prefix):
    monkeypatch.setenv("UI_BASE_PATH", prefix)
    get_settings.cache_clear()
    try:
        page = client.get("/namespaces")
        assert page.status_code == 200
        blocks = re.findall(r"<style\b[^>]*>(.*?)</style>", page.text, re.DOTALL)
        font_css = next(block for block in blocks if "@font-face" in block)
        escaped_quotes = "url(&#34;" in font_css
        assert not escaped_quotes, "Font URLs in a raw-text style element must not contain HTML entities"
        urls = re.findall(r'src:\s*url\("([^\"]+)"\)', font_css)
        assert urls, "The rendered stylesheet must contain the actual font-face sources"
        fonts = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/base/fonts"
        for url in urls:
            assert url.startswith(prefix + "/base-assets/fonts/")
            filename = url.rsplit("/", 1)[1]
            assert re.fullmatch(r"[a-z0-9-]+\.woff2", filename)
            # The configured reverse proxy strips the public deployment prefix.
            asset = client.get(url.removeprefix(prefix) if prefix else url)
            assert asset.status_code == 200
            assert asset.content.startswith(b"wOF2")
            assert asset.content == (fonts / filename).read_bytes()
    finally:
        get_settings.cache_clear()
