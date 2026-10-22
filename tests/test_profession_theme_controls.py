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
        self.icon_options = []
        self.in_icon_selector = False
        self.root_attrs = {}
        self.brand_attrs = {}
        self.selector_attrs = []
        self.selector_options = []
        self.in_selector = False

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "html":
            self.root_attrs = fields
        if "base-platform-mark" in fields.get("class", "").split():
            self.brand_attrs = fields
        if tag == "select":
            self.in_icon_selector = fields.get("name") == "namespaceThemeIcon"
            self.in_selector = "data-namespace-selector" in fields
            if self.in_selector:
                self.selector_attrs.append(fields)
        if tag == "option" and self.in_icon_selector:
            self.icon_options.append(fields)
        if tag == "option" and self.in_selector:
            self.selector_options.append(fields)
        if tag == "input" and fields.get("name") == "namespaceThemeIcon":
            self.radios.append(fields)

    def handle_endtag(self, tag):
        if tag == "select":
            self.in_selector = False
            self.in_icon_selector = False


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
        create_mode=edited is None, page="namespaces", ui_port=8812, can_administer=True,
        namespace_cookie_name="workflow_namespace_id", namespace_cookie_secure=False,
    )
    parsed = ThemeInputs()
    parsed.feed(html)
    assert "style" not in parsed.root_attrs
    assert parsed.brand_attrs
    assert "style" not in parsed.brand_attrs
    if edited:
        assert len(parsed.selector_attrs) == 2
        assert all("data-base-choice" in control for control in parsed.selector_attrs)
        assert all(option["data-color"] == color for option in parsed.selector_options if "selected" in option)
    assert {option["value"] for option in parsed.icon_options} == set(PROJECT_THEME_ICONS)
    assert [option["value"] for option in parsed.icon_options if "selected" in option] == [icon or "folder"]
    assert 'for="namespaceThemeIcon">Иконка</label>' in html
    assert 'data-base-choice class="base-control" id="namespaceThemeIcon"' in html
    assert 'renderOption: renderNamespaceIconChoice' in html
    assert 'namespaceIconSelect' not in html
    assert 'id="namespaceThemeControls"' in html
    assert 'id="namespaceThemePreview"' not in html
    assert "<path d=" in html
    assert "option.dataset.color = color || defaultNamespaceThemeColor" in html


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
        selected = [option for option in parsed.selector_options if "selected" in option]
        assert len(selected) == 2
        assert all(option["data-color"] == current["theme_color"] for option in selected)
        assert all(option["value"] == str(current["id"]) for option in selected)
        assert "initChoice(control" in html
        for profession in professions:
            assert html.count(f'data-icon="{profession["theme_icon"]}" data-color="{profession["theme_color"]}"') == 2
            assert sum(option['value'] == str(profession['id']) for option in parsed.selector_options) == 2
        logos.append(html.split('<a class="brand-link"', 1)[1].split('</a>', 1)[0])
    assert logos[0] == logos[1]
    assert 'data-base-platform-mark' in logos[0]
    assert 'data-base-brand-initials' in logos[0]


@pytest.mark.parametrize("icon", PROJECT_THEME_ICONS)
def test_every_catalog_icon_is_accepted_by_the_api_and_has_its_own_drawing(icon):
    assert NamespaceUpdate(theme_icon=icon).theme_icon == icon
    assert PROJECT_ICON_PATHS[icon]
    assert len(set(PROJECT_ICON_PATHS[name] for name in PROJECT_THEME_ICONS)) == len(PROJECT_THEME_ICONS)
