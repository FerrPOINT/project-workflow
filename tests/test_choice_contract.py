"""Active SSR choices must use the exported Base enhancement, not product widgets."""
import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "project_workflow/interfaces/ui/templates"


def test_all_active_choices_use_base_adapter_and_keep_native_fallback():
    controls = []
    for source in TEMPLATES.glob("*.html"):
        for control in re.findall(r"<select\b([^>]*)>", source.read_text(encoding="utf-8")):
            controls.append((source.name, control))
            assert "data-base-choice" in control, (source.name, control)
            assert " hidden" not in control, "Fallback is hidden only after successful initialization"
    assert len(controls) == 6
    assert not any("rollback" in control for _, control in controls)
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
