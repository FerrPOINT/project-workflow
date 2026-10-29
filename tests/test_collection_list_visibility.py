"""Collection navigation stays available for every nonempty collection."""
import pytest

from project_workflow.interfaces.ui.controller_assets import controller_source
from project_workflow.interfaces.ui.templates import templates


@pytest.mark.parametrize("can_administer", [False, True])
@pytest.mark.parametrize("count", [0, 1, 2])
@pytest.mark.parametrize("name", ["workflows.html", "namespaces.html", "phases.html"])
def test_list_visibility_depends_on_empty_collection_only(name, count, can_administer):
    entries = [
        {
            "id": number + 1, "name": f"Entry {number + 1}", "description": "",
            "namespace_count": 1, "phase_count": 1, "task_count": 0,
            "cli_command": f"workflow-entry-{number + 1}", "theme_icon": "folder",
            "theme_color": "#5E6AD2", "modes": [],
        }
        for number in range(count)
    ]
    html = templates.get_template(name).render(
        namespaces=entries, workflows=entries, selected_namespace=None, selected_workflow=None,
        selected_workflow_id=None, edited_namespace=None, create_mode=True, phases=[], phase_blocks=[],
        phase_count=0, modes=[], selected_mode=None, page="workflows", ui_port=8812,
        namespace_cookie_name="workflow_namespace_id", namespace_cookie_secure=False,
        can_administer=can_administer,
    )
    controller = "workflows" if name in {"workflows.html", "phases.html"} else "namespaces"
    source, digest = controller_source(controller, can_administer)
    assert f"/{digest}/{controller}.js" in html
    script = source.decode()
    if name in {"workflows.html", "phases.html"}:
        assert ('class="workflow-crud is-empty"' in html) is (count == 0)
        assert '.workflow-crud.is-empty .workflow-nav{display:none}' in html
        assert ("classList.toggle('is-empty', workflowStore.length === 0)" in script) == can_administer
    elif name == "namespaces.html":
        assert ('class="namespace-crud is-empty"' in html) is (count == 0)
        assert ("classList.toggle('is-empty', namespaceStore.length === 0)" in script) == can_administer
    assert "is-single" not in html
