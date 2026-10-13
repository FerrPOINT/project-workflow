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
        self.root_attrs = {}
        self.brand_attrs = {}
        self.selector_attrs = []

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "html":
            self.root_attrs = fields
        if fields.get("class") == "brand-mark":
            self.brand_attrs = fields
        if fields.get("class") == "namespace-trigger":
            self.selector_attrs.append(fields)
        if tag == "input" and fields.get("name") == "namespaceThemeIcon":
            self.radios.append(fields)


@pytest.mark.parametrize("icon", [None, "folder", "code", "rocket", "palette", "users"])
def test_theme_controls_show_all_icons_and_select_current_value(icon):
    color = "#D2608E" if icon in {"code", "palette"} else "#22C55E"
    edited = None if icon is None else {
        "id": 123, "name": "Profession", "cli_command": "workflow-profession",
        "description": "", "theme_icon": icon, "theme_color": color, "task_count": 0,
    }
    html = templates.get_template("namespaces.html").render(
        namespaces=[edited] if edited else [], selected_namespace=edited,
        edited_namespace=edited, theme_namespace=edited,
        create_mode=edited is None, page="namespaces", ui_port=8812,
        namespace_cookie_name="workflow_namespace_id", namespace_cookie_secure=False,
    )
    parsed = ThemeInputs()
    parsed.feed(html)
    assert "style" not in parsed.root_attrs
    assert "style" not in parsed.brand_attrs
    if edited:
        assert len(parsed.selector_attrs) == 2
        assert all(trigger["style"] == f"--namespace-color:{color}" for trigger in parsed.selector_attrs)
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


def test_header_logo_is_constant_and_each_profession_option_has_its_own_identity():
    professions = [
        {"id": 37, "name": "Design", "theme_icon": "palette", "theme_color": "#D2608E"},
        {"id": 93, "name": "Testing", "theme_icon": "flask", "theme_color": "#22C55E"},
    ]
    logos = []
    for current in professions:
        html = templates.get_template("base.html").render(
            namespaces=professions, theme_namespace=current, namespace_cookie_name="workflow_namespace_id",
            namespace_cookie_secure=False,
        )
        parsed = ThemeInputs()
        parsed.feed(html)
        assert "style" not in parsed.brand_attrs
        assert all(
            trigger["style"] == f"--namespace-color:{current['theme_color']}"
            for trigger in parsed.selector_attrs
        )
        assert html.count('role="listbox" aria-label="Профессии"') == 2
        for profession in professions:
            assert html.count(f'data-icon="{profession["theme_icon"]}" data-color="{profession["theme_color"]}"') == 2
            assert html.count(f'data-value="{profession["id"]}"') == 2
        logos.append(html.split('<a class="brand-link"', 1)[1].split('</a>', 1)[0])
    assert logos[0] == logos[1]
    assert 'd="M7 11v4a2 2 0 0 0 2 2h4"' in logos[0]


@pytest.mark.parametrize("icon", PROJECT_THEME_ICONS)
def test_every_catalog_icon_is_accepted_by_the_api_and_has_its_own_drawing(icon):
    assert NamespaceUpdate(theme_icon=icon).theme_icon == icon
    assert PROJECT_ICON_PATHS[icon]
    assert len(set(PROJECT_ICON_PATHS[name] for name in PROJECT_THEME_ICONS)) == len(PROJECT_THEME_ICONS)
