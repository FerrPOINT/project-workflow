"""The owner changes the diagram layout; Base owns the view selection control."""

import json
import re
import subprocess

import pytest

from project_workflow.interfaces.ui.controller_assets import controller_source
from tests import test_ui_shell_template as shell

pytestmark = pytest.mark.ui


def render_editor(admin, count=8):
    workflow = dict(id=3, name="Delivery <3>", description="", phase_count=count, namespace_count=0)
    phases = [dict(id=i, phase_num=i, name=f"Phase {i}", description="", execution_type="sync")
              for i in range(1, count + 1)]
    return shell.SharedShellTemplateTests().render_shell(
        [], template="workflows.html", can_administer=admin,
        workflows=[workflow], selected_workflow=workflow, selected_workflow_id=3,
        selected_namespace=None, modes=[], selected_mode_id=None,
        phases=phases, phase_count=count,
        phase_blocks=[dict(kind="sync", phases=[phase]) for phase in phases],
    )


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("view", ["compact", "timeline"])
def test_phase_view_changes_base_skin_for_each_role_without_writing_during_restore(admin, view):
    code = controller_source("workflows", admin)[0].decode()
    start = code.index("function setPhaseView(")
    source = code[start:code.index("function jumpToPhase(", start)]
    script = """
const view=VIEW;
const classes=new Set(['base-resource-list-row']);
const toggles=values=>({toggle(name,on){on?values.add(name):values.delete(name);}});
const card={classList:toggles(classes)};
const timelineClasses=new Set(['is-compact']);
const timeline={classList:toggles(timelineClasses),querySelectorAll:()=>[card]};
const radios=['compact','timeline'].map(value=>({value,checked:value==='compact'}));
const legacyButtons=radios.map(r=>({dataset:{phaseView:r.value},setAttribute(){}}));
let writes=[];
const document={getElementById:id=>id==='phasesTimeline'?timeline:null,
 querySelectorAll:selector=>selector==='[data-phase-view]'?legacyButtons:radios};
const localStorage={setItem:(key,value)=>writes.push([key,value])};
SOURCE
setPhaseView(view,false);
const restored={classes:[...classes].sort(),compact:timelineClasses.has('is-compact'),
 radios:radios.map(r=>r.checked),writes:[...writes]};
setPhaseView(view);
setPhaseView('invalid');
console.log(JSON.stringify({restored,writes}));
""".replace("VIEW", json.dumps(view)).replace("SOURCE", source)
    result = subprocess.run(["node", "--input-type=module", "-"], input=script, text=True,
                            encoding="utf-8", capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "restored": {
            "classes": ["base-resource-list-row"] if view == "compact" else ["base-card"],
            "compact": view == "compact", "radios": [view == "compact", view == "timeline"],
            "writes": [],
        },
        "writes": [["phase-view-mode", view]],
    }


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("count", [1, 2, 8])
def test_editor_uses_the_shared_segmented_radio_group_and_preserves_permissions(admin, count):
    html = render_editor(admin, count)
    elements = shell.Elements(html).elements
    groups = [attrs for _, attrs in elements if attrs.get("aria-label") == "Отображение фаз"]
    radios = [attrs for tag, attrs in elements if tag == "input" and attrs.get("name") == "phase-view"]
    assert len(groups) == (1 if count > 1 else 0)
    assert len(radios) == (2 if count > 1 else 0)
    if count > 1:
        assert groups[0]["role"] == "radiogroup"
        assert groups[0]["class"] == "base-radio-group"
        assert groups[0]["data-appearance"] == "segmented"
        assert [item["value"] for item in radios] == ["compact", "timeline"]
        assert [item["value"] for item in radios if "checked" in item] == ["compact" if count >= 8 else "timeline"]
    assert controller_source("workflows", admin)[0].decode().count("function setPhaseView(") == 1
    assert controller_source("workflows", admin)[0].decode().count("function selectMode(") == 1
    assert controller_source("workflows", admin)[0].decode().count("function jumpToPhase(") == 1
    assert ('id="workflowForm"' in html) == admin
    assert any('phase-card-actions' in attrs.get('class', '').split() for _, attrs in elements) == admin
    headings = {attrs.get("id"): attrs for tag, attrs in elements if tag == "h2"}
    for heading_id in ["workflowSummaryName", "workflowPhasesTitle"]:
        assert "base-section-title" in headings[heading_id]["class"].split()
    nav_item = re.search(r'<button[^>]*data-workflow-id="3"[^>]*>([\s\S]*?)</button>', html)
    assert nav_item is not None
    assert 'class="base-card-title" data-workflow-name' in nav_item.group(1)
    assert "Delivery &lt;3&gt;" in nav_item.group(1)
    counts = [attrs for _, attrs in shell.Elements(nav_item.group(1)).elements
              if "base-badge" in attrs.get("class", "").split()]
    assert len(counts) == 2
    assert all(item["data-tone"] == "muted" for item in counts)
    assert ('id="workflowNavItemTemplate"' in html) == admin
    assert ('id="workflowNavEmptyTemplate"' in html) == admin


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("storage", ["compact", "timeline", "invalid", "unavailable"])
def test_phase_view_restores_without_a_write_and_changes_only_on_a_checked_selection(admin, storage):
    code = controller_source("workflows", admin)[0].decode()
    start = code.index("function setPhaseView(")
    end = code.index("const professionId =", start) if admin else code.index("function selectWorkflow(", start)
    source = code[start:end]
    script = """
const storage=STORAGE;const writes=[],ready=[];
const page={ready:callback=>ready.push(callback),on:(target,type,callback)=>target.addEventListener(type,callback)};
class HTMLInputElement{constructor(value){this.value=value;this.name='phase-view';this.checked=value==='compact';}}
const radios=['compact','timeline'].map(value=>new HTMLInputElement(value));
const classes=new Set(['base-resource-list-row']);
const toggles=values=>({toggle(name,on){on?values.add(name):values.delete(name);}});
const timelineClasses=new Set(['is-compact']);
const timeline={classList:toggles(timelineClasses),querySelectorAll:()=>[{classList:toggles(classes)}]};
let changed;
const group={addEventListener(type,callback){if(type==='change')changed=callback;}};
const document={getElementById:id=>id==='phasesTimeline'?timeline:id==='phaseView'?group:null,
 querySelectorAll:selector=>selector.includes('phase-card-actions')?[]:radios,
 addEventListener(type,callback){if(type==='DOMContentLoaded')ready.push(callback);if(type==='change')changed=callback;}};
const localStorage={getItem(){if(storage==='unavailable')throw Error('storage');return storage;},
 setItem(key,value){if(storage==='unavailable')throw Error('storage');writes.push([key,value]);}};
SOURCE
ready.forEach(callback=>callback());
const restored={writes:[...writes],selected:radios.filter(r=>r.checked).map(r=>r.value)};
radios[1].checked=false;changed({target:radios[1]});changed({target:{name:'phase-view',checked:true,value:'timeline'}});
const ignored=writes.length;
radios[1].checked=true;changed({target:radios[1]});
console.log(JSON.stringify({restored,ignored,selected:radios.filter(r=>r.checked).map(r=>r.value),writes}));
""".replace("STORAGE", json.dumps(storage)).replace("SOURCE", source)
    result = subprocess.run(["node", "--input-type=module", "-"], input=script, text=True,
                            encoding="utf-8", capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "restored": {"writes": [], "selected": [storage if storage in ["compact", "timeline"] else "compact"]},
        "ignored": 0, "selected": ["timeline"],
        "writes": [] if storage == "unavailable" else [["phase-view-mode", "timeline"]],
    }


@pytest.mark.parametrize("admin", [False, True])
def test_editor_script_is_valid_after_role_specific_rendering(admin):
    owner_script = controller_source("workflows", admin)[0].decode()
    result = subprocess.run(["node", "--check", "-"], input=owner_script, text=True,
                            encoding="utf-8", capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
