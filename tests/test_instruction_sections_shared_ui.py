"""Base supplies section paint; Workflow retains editable instruction identities."""

import json
import re
import subprocess

import pytest

from project_workflow.interfaces.ui.controller_assets import controller_source
from tests import test_ui_shell_template as shell

pytestmark = pytest.mark.ui


def render_instructions(groups, namespace_id=None):
    return shell.SharedShellTemplateTests().render_shell(
        [], template="instructions.html", phase={"id": 41, "name": "Phase <safe>"},
        instruction_groups=groups,
        selected_namespace={"id": namespace_id} if namespace_id is not None else None,
    )


@pytest.mark.parametrize("namespace_id", [None, 73])
@pytest.mark.parametrize("populated", [False, True])
def test_instruction_sections_keep_fields_handlers_and_owner_data(populated, namespace_id):
    instructions = [
        dict(id=81, step_num=1, description="First <safe>", execution_type="sync", skills=["rust"]),
        dict(id=92, step_num=2, description="Second <safe>", execution_type="parallel", skills=[]),
    ] if populated else []
    html = render_instructions([instructions] if instructions else [], namespace_id)
    elements = shell.Elements(html).elements
    rows = [attrs for _, attrs in elements if "instruction-row" in attrs.get("class", "").split()]
    assert [row["data-instruction-id"] for row in rows] == (["81", "92"] if populated else [])
    assert [row["data-step-num"] for row in rows] == (["1", "2"] if populated else [])
    for row in rows:
        assert "base-content-section" in row["class"].split()
        assert (row["data-dividers"], row["data-inset"], row["data-density"]) == ("end", "both", "compact")
        assert "role" not in row and "tabindex" not in row
    descriptions = [attrs for tag, attrs in elements if tag == "textarea"]
    assert [attrs["data-original-description"] for attrs in descriptions] == [
        item["description"] for item in instructions
    ]
    assert all(attrs["onchange"] == "updateInstruction(this)" for attrs in descriptions)
    skills = [attrs for tag, attrs in elements if tag == "input" and "skills-input" in attrs.get("class", "").split()]
    assert [attrs["value"] for attrs in skills] == (["rust", ""] if populated else [])
    assert all(attrs["onchange"] == "updateSkills(this)" for attrs in skills)
    assert sum("parallel-group" in attrs.get("class", "").split() for _, attrs in elements) == int(populated)
    panel = next(attrs for _, attrs in elements if "add-panel" in attrs.get("class", "").split())
    assert "base-content-section" in panel["class"].split()
    assert panel["data-dividers"] == "start" and panel["data-inset"] == "start"
    new_field = next(attrs for tag, attrs in elements if tag == "input" and attrs.get("id") == "newInstructionText")
    assert "base-input" in new_field["class"].split()
    assert any(tag == "button" and attrs.get("onclick") == "addInstruction()" for tag, attrs in elements)
    assert ('data-page-state="empty"' in html) is not populated
    data = json.loads(re.search(r"<script[^>]*data-workflow-view-data[^>]*>([\s\S]*?)</script>", html)[1])
    assert data["phaseId"] == 41 and data["professionId"] == namespace_id
    owner = controller_source("instructions", True)[0].decode()
    assert "const PHASE_ID = config.phaseId;" in owner
    assert "const selectedNamespaceId = config.professionId;" in owner
    checked = subprocess.run(["node", "--check", "-"], input=owner, text=True,
                             encoding="utf-8", capture_output=True, timeout=10)
    assert checked.returncode == 0, checked.stderr
