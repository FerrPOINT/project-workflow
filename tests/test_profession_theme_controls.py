"""Profession appearance uses the existing icon/color fields in one visual row."""

from html.parser import HTMLParser

import pytest

from project_workflow.domain.project_theme import PROJECT_THEME_ICONS
from project_workflow.interfaces.ui.schemas import NamespaceUpdate
from project_workflow.interfaces.ui.templates import PROJECT_ICON_PATHS, templates


class ThemeInputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.radios = []

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "input" and fields.get("name") == "namespaceThemeIcon":
            self.radios.append(fields)


@pytest.mark.parametrize("icon", [None, "folder", "code", "rocket", "palette", "users"])
def test_theme_controls_show_all_icons_and_select_current_value(icon):
    edited = None if icon is None else {
        "id": 123, "name": "Profession", "cli_command": "workflow-profession",
        "description": "", "theme_icon": icon, "theme_color": "#22C55E",
    }
    html = templates.get_template("namespaces.html").render(
        namespaces=[], selected_namespace=None, edited_namespace=edited,
        create_mode=edited is None, page="namespaces", ui_port=8812,
        namespace_cookie_name="workflow_namespace_id", namespace_cookie_secure=False,
    )
    parsed = ThemeInputs()
    parsed.feed(html)
    assert {radio["value"] for radio in parsed.radios} == set(PROJECT_THEME_ICONS)
    assert [radio["value"] for radio in parsed.radios if "checked" in radio] == [icon or "folder"]
    assert all(radio["type"] == "radio" and radio["aria-label"] for radio in parsed.radios)
    assert 'role="radiogroup" aria-label="Иконка"' in html
    assert '<details class="theme-icon-select" id="namespaceIconSelect">' in html
    assert '<summary aria-label="Выбрать иконку">' in html
    assert 'id="namespaceThemeControls"' in html
    assert 'id="namespaceThemePreview"' not in html
    assert 'id="namespaceThemeIcon"' not in html
    assert "<path d=" in html
    assert "style.setProperty('--namespace-color', color)" in html


@pytest.mark.parametrize("icon", PROJECT_THEME_ICONS)
def test_every_catalog_icon_is_accepted_by_the_api_and_has_its_own_drawing(icon):
    assert NamespaceUpdate(theme_icon=icon).theme_icon == icon
    assert PROJECT_ICON_PATHS[icon]
    assert len(set(PROJECT_ICON_PATHS[name] for name in PROJECT_THEME_ICONS)) == len(PROJECT_THEME_ICONS)
