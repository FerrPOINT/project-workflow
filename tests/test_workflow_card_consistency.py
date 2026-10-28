"""The same five Base actions and visible parallel frames serve both card kinds."""
import re

import pytest

from tests.test_phase_editor_shared_ui import render_editor as instruction_editor
from tests.test_ui_shell_template import Elements
from tests.test_workflow_phase_view import render_editor as phase_editor

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("admin", [False, True])
def test_both_card_kinds_share_the_action_contract(admin):
    phase_html = phase_editor(admin, 2)
    instruction_html = instruction_editor(admin, True)
    toolbars = []
    for html, kind in [(phase_html, "phase"), (instruction_html, "instruction")]:
        match = re.search(r'<div class="workflow-card-actions ' + kind + r'-card-actions".*?</div>', html, re.S)
        assert (match is not None) == admin
        if match:
            buttons = [attrs for tag, attrs in Elements(match.group()).elements if tag == "button"]
            assert len(buttons) == 5
            assert all(button.get("aria-label") and button.get("title") for button in buttons)
            toolbars.append([(button["data-size"], button["data-variant"]) for button in buttons])
    if admin:
        assert toolbars[0] == toolbars[1]
        assert toolbars[0] == [("icon", "outline"), ("icon", "ghost"), ("icon", "ghost"),
                               ("icon", "outline"), ("icon", "destructive-outline")]


def test_parallel_instruction_frame_and_rebuild_use_shared_template():
    from pathlib import Path

    from tests.test_ui_shell_template import SharedShellTemplateTests

    html = SharedShellTemplateTests().render_instruction_editor(True)
    frames = [attrs for _, attrs in Elements(html).elements
              if "timeline-parallel-group" in attrs.get("class", "").split()]
    assert frames and all("workflow-parallel-group" in frame["class"].split() for frame in frames)
    assert 'id="instruction-parallel-group-template"' in html
    css = (Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/workflow-cards.css").read_text()
    assert 'border-color:#d97706' in css


@pytest.mark.parametrize("admin", [False, True])
def test_instruction_skill_chips_have_no_disclosure_and_use_plus_for_free_text(admin):
    html = instruction_editor(admin, True)
    elements = Elements(html).elements
    assert "instruction-skill-editor" not in html
    assert "skill_summary" not in html
    labels = [attrs["id"] for _, attrs in elements
              if attrs.get("id", "").startswith("instruction-skills-label-")]
    groups = [attrs.get("aria-labelledby") for _, attrs in elements
              if "instruction-skills" in attrs.get("class", "").split()]
    assert labels and groups == labels
    triggers = [attrs for tag, attrs in elements
                if tag == "button" and "skill-add-trigger" in attrs.get("class", "").split()]
    forms = [attrs for tag, attrs in elements if tag == "form" and "skill-add-form" in attrs.get("class", "").split()]
    assert bool(triggers) == admin
    assert bool(forms) == admin
    assert all("hidden" in form and form.get("method") == "post" for form in forms)
    assert all(button["aria-label"].startswith("Добавить навык") for button in triggers)
    assert all(button["data-size"] == "icon" for button in triggers)
    assert ('id="instruction-skill-chip-template"' in html) == admin
