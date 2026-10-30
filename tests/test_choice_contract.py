"""Active SSR choices must use the exported Base enhancement, not product widgets."""
import re
from pathlib import Path

from jinja2 import nodes

from project_workflow.interfaces.ui.templates import templates

TEMPLATES = Path(__file__).resolve().parents[1] / "project_workflow/interfaces/ui/templates"


def test_all_active_choices_use_base_adapter_and_keep_native_fallback():
    calls = {}
    for source in TEMPLATES.glob("*.html"):
        text = source.read_text(encoding="utf-8")
        assert not re.search(r"<select\b", text), f"{source.name}: use the public Base macro"
        count = sum(
            isinstance(call.node, nodes.Getattr) and call.node.attr == "select_control"
            and isinstance(call.node.node, nodes.Name) and call.node.node.name == "base_ui"
            for call in templates.env.parse(text).find_all(nodes.Call)
        )
        if count:
            calls[source.name] = count
    assert calls == {"namespaces.html": 2, "phase_detail.html": 1, "profession_selector.html": 1,
                     "workflows.html": 3}

    # Check the actual product composition and pinned Base renderer, not the retired raw markup.
    selector = templates.get_template("profession_selector.html").module.profession_selector
    html = str(selector("choice-proof", [{"id": 73, "name": "Вариант <73>",
                                         "theme_icon": "rocket", "theme_color": "#2563eb"}], None))
    controls = re.findall(r"<select\b([^>]*)>", html)
    assert len(controls) == 1
    assert "data-base-choice" in controls[0]
    assert " hidden" not in controls[0], "Fallback is hidden only after successful initialization"
    assert 'id="choice-proof"' in controls[0]
    assert 'onchange="switchNamespace(this.value)"' in controls[0]
    assert 'value="73"' in html and "Вариант &lt;73&gt;" in html
    assert "rollback" not in html
    bootstrap = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert 'include "base/choice-runtime.js"' in bootstrap
    assert "initChoice(control" in bootstrap
    assert "refreshChoice(select)" in bootstrap
    assert "namespace-option" not in bootstrap
    assert "picker.addEventListener('keydown'" not in bootstrap


def test_combined_ssr_module_has_no_duplicate_bindings_or_syntax_errors(tmp_path):
    import subprocess
    from html.parser import HTMLParser

    from project_workflow.interfaces.ui.templates import templates

    class Scripts(HTMLParser):
        def __init__(self):
            super().__init__()
            self.active = False
            self.modules = []

        def handle_starttag(self, tag, attrs):
            if tag == "script":
                self.active = dict(attrs).get("type") == "module"

        def handle_endtag(self, tag):
            if tag == "script":
                self.active = False

        def handle_data(self, data):
            if self.active:
                self.modules.append(data)

    parsed = Scripts()
    parsed.feed(templates.get_template("base.html").render(
        namespaces=[], namespace_cookie_name="workflow_namespace_id", namespace_cookie_secure=False,
    ))
    assert parsed.modules
    for index, module in enumerate(parsed.modules):
        path = tmp_path / f"module-{index}.mjs"
        path.write_text(module, encoding="utf-8")
        result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr


def test_cancelled_profession_navigation_keeps_confirmed_controls_and_cookie():
    import subprocess

    from project_workflow.interfaces.ui.templates import templates

    html = templates.get_template("base.html").render(
        namespaces=[], namespace_cookie_name="workflow_namespace_id", namespace_cookie_secure=False,
    )
    handler = html.split("function switchNamespace(namespaceId){", 1)[1].split("function pluralizeRu", 1)[0]
    program = """
const assert = require('node:assert/strict');
const controls = [{value:'93'}, {value:'37'}];
const document = {cookie:'untouched', querySelectorAll: () => controls};
let confirmedProfessionId = '37';
const attempts = [];
const window = {location:{href:'https://workflow.example.test/phases?profession_id=37'},
  SdlcPlatformNavigation:{navigate:url=>attempts.push(url), embedded:false}};
const refreshNamespaceSelectors = () => {};
""" + "function switchNamespace(namespaceId){" + handler + """
switchNamespace('93');
assert.deepEqual(controls.map(control=>control.value), ['37','37']);
assert.equal(document.cookie, 'untouched');
assert.equal(new URL(attempts[0]).searchParams.get('profession_id'), '93');
"""
    result = subprocess.run(["node", "-e", program], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
