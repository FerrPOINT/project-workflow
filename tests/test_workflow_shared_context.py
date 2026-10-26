"""Workflow owns routes/data; Base owns navigation, action layout and guidance."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from tests import test_ui_shell_template as shell_helpers


def workflow_context(count=3, admin=True, selected_mode=73, scope=None):
    phases = [dict(id=i, phase_num=i, name=f"Phase <{i}>", description="Owner description", execution_type="sync")
              for i in range(1, count + 1)]
    workflow = dict(id=31, name="Owner workflow", description="Owner <description>",
                    phase_count=count, namespace_count=1)
    namespace = dict(id=19, name="Owner profession", theme_icon="code", theme_color="#123456")
    modes = [dict(id=i, key=str(i), name="Same <mode>") for i in [42, 73]]
    blocks = ([dict(kind="parallel", phases=phases[:2]), *[dict(kind="sync", phases=[p]) for p in phases[2:]]]
              if count >= 3 else [dict(kind="sync", phases=[p]) for p in phases])
    request = SimpleNamespace(query_params={"project_scope": scope} if scope else {}, state=SimpleNamespace())
    return dict(
        namespaces=[namespace], workflows=[workflow], selected_workflow=workflow,
        selected_workflow_id=31, selected_namespace=namespace, modes=modes, selected_mode_id=selected_mode,
        selected_mode=modes[1 if selected_mode == 73 else 0], phases=phases, phase_count=count,
        phase_blocks=blocks, can_administer=admin, request=request,
    )


def render_workflows(**kwargs):
    return shell_helpers.SharedShellTemplateTests().render_shell(
        template="workflows.html", **workflow_context(**kwargs)
    )


@pytest.mark.parametrize("scope", [None, "all"])
@pytest.mark.parametrize("selected_mode", [42, 73])
def test_route_modes_use_base_navigation_with_distinct_owner_ids(scope, selected_mode):
    html = render_workflows(selected_mode=selected_mode, scope=scope)
    elements = shell_helpers.Elements(html).elements
    nav = [attrs for tag, attrs in elements if tag == "nav" and attrs.get("aria-label") == "Режимы воркфлоу"]
    assert len(nav) == 1 and "base-section-navigation" in nav[0]["class"].split()
    links = [attrs for tag, attrs in elements if tag == "a" and "data-mode-id" in attrs]
    assert len(links) == 2
    for link, mode_id in zip(links, [42, 73], strict=True):
        assert {"base-section-navigation-item", "base-control"} <= set(link["class"].split())
        assert link["data-mode-id"] == str(mode_id)
        assert link["data-testid"] == f"workflow-mode-tab-{mode_id}"
        assert link.get("aria-current") == ("page" if mode_id == selected_mode else None)
        assert urlsplit(link["href"]).path == "/workflow/workflows"
        query = parse_qs(urlsplit(link["href"]).query)
        assert query == {"workflow_id": ["31"], "mode_id": [str(mode_id)], "profession_id": ["19"],
                         **({"project_scope": ["all"]} if scope else {})}
    assert html.count("Same &lt;mode&gt;</a>") == 2
    assert not any(attrs.get("role") in {"tab", "tablist"} for _, attrs in elements)


@pytest.mark.parametrize("count", [0, 1, 2, 7, 8, 9])
@pytest.mark.parametrize("admin", [False, True])
def test_shared_actions_preserve_native_types_permissions_and_view_controls(count, admin):
    html = render_workflows(count=count, admin=admin)
    elements = shell_helpers.Elements(html).elements
    actions = [attrs for _, attrs in elements if "panel-actions" in attrs.get("class", "").split()]
    assert len(actions) == int(admin)
    if actions:
        assert "base-action-group" in actions[0]["class"].split()
        assert actions[0]["data-align"] == "start"
        buttons = {attrs.get("id"): attrs for tag, attrs in elements if tag == "button" and "id" in attrs}
        assert buttons["workflowSubmitButton"]["type"] == "submit"
        assert buttons["cancelCreateWorkflowButton"]["type"] == "button"
        assert buttons["deleteWorkflowButton"]["type"] == "button"
        assert buttons["deleteWorkflowButton"]["onclick"] == "deleteWorkflow()"
    view = [attrs for _, attrs in elements if "phase-view-controls" in attrs.get("class", "").split()]
    assert len(view) == int(count > 1)
    if view:
        assert "base-action-group" in view[0]["class"].split()
        assert view[0]["data-align"] == "between"
    radios = [attrs for tag, attrs in elements if tag == "input" and attrs.get("name") == "phase-view"]
    assert len(radios) == (2 if count > 1 else 0)
    if radios:
        assert [item["value"] for item in radios if "checked" in item] == ["compact" if count >= 8 else "timeline"]
    assert sum(attrs.get("id") == "phaseJump" for _, attrs in elements) == int(count >= 8)


def test_parallel_guidance_keeps_barrier_text_and_quiet_common_presentation():
    html = render_workflows()
    elements = shell_helpers.Elements(html).elements
    messages = [attrs for _, attrs in elements if "base-notice" in attrs.get("class", "").split()]
    assert len(messages) == 1
    assert messages[0]["data-appearance"] == "inline" and messages[0]["data-separated"] == "true"
    assert "role" not in messages[0] and "aria-live" not in messages[0]
    assert "Следующий этап — после завершения всех фаз группы." in html
    assert html.count('data-phase-id="') == 3
    assert "Phase &lt;1&gt;" in html and "Owner &lt;description&gt;" in html
    assert "function setPhaseView(view,persist=true)" in html
    assert "localStorage.setItem('phase-view-mode',view)" in html
