"""Shared presentation preserves the phase editor's owner identities and permissions."""

import json
import re
import subprocess

import pytest

from project_workflow.interfaces.ui.controller_assets import controller_source
from tests import test_ui_shell_template as shell

pytestmark = pytest.mark.ui


def render_editor(admin, populated):
    phase = dict(
        id=4, code="PHASE", name="Phase <name>", description="Description <safe>",
        workflow_id=3, mode_id=9, execution_type="sync", parallel_with_phase_id=None,
        instructions=[dict(id=31, step_num=1, description="Instruction <safe>", execution_type="sync", skills=[])]
        if populated else [],
        checks=[dict(id=51, description="Check <safe>")] if populated else [],
        evidence=[dict(id=61, description="Evidence <safe>")] if populated else [],
    )
    return shell.SharedShellTemplateTests().render_shell(
        [dict(id=7, name="Profession", task_count=0)], template="phase_detail.html",
        can_administer=admin, phase=phase, selected_namespace=dict(id=7),
        rollback_target_phase=dict(name="Rollback <safe>", code="ROLLBACK"), parallel_candidates=[],
    )


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("populated", [False, True])
def test_phase_editor_uses_shared_presentation_with_native_list_and_role_semantics(admin, populated):
    html = render_editor(admin, populated)
    elements = shell.Elements(html).elements
    assert sum(tag == "h1" for tag, _ in elements) == 1
    headings = {attrs.get("id"): attrs for tag, attrs in elements if tag == "h2"}
    for name in ["instructions-title", "checks-title", "evidence-title"]:
        assert "base-section-title" in headings[name]["class"].split()
    for list_id in ["checks-list", "evidence-list"]:
        attrs = next(attrs for tag, attrs in elements if tag == "ul" and attrs.get("id") == list_id)
        assert attrs["class"] == "base-resource-list"
    rows = [attrs for tag, attrs in elements if tag == "li" and attrs.get("data-id") in ["51", "61"]]
    assert len(rows) == (2 if populated else 0)
    assert ('id="checks-list-item-template"' in html) == admin
    assert ('id="evidence-list-item-template"' in html) == admin
    assert ('id="phaseSaveEditor"' in html) == admin
    back = next(attrs for tag, attrs in elements if tag == "a" and
                attrs.get("href") == "/workflow/phases?workflow_id=3&mode_id=9&profession_id=7")
    assert "base-button" in back["class"].split()
    assert "Rollback &lt;safe&gt;" not in html
    assert 'id="parallelPartnerSelect"' not in html
    assert 'onclick="togglePhaseMode(this)"' not in html
    if admin:
        retry = next(attrs for _, attrs in elements if attrs.get("id") == "phaseSaveEditor")
        assert "hidden" in retry
    for source in [".wiki-header h1{", ".catalog-card{", ".check-list>li{", ".evidence-list>li{",
                   ".wiki-section-title{", ".empty-state{"]:
        assert source not in html
    active_markup = re.sub(r"<template\b[^>]*>[\s\S]*?</template>", "", html)
    assert active_markup.count('data-page-state="empty"') == (0 if populated else 3)
    if populated:
        for text in ["Instruction &lt;safe&gt;", "Check &lt;safe&gt;", "Evidence &lt;safe&gt;"]:
            assert text in html
    owner = controller_source("phase_detail", admin)[0].decode()
    marker = "const phaseId =" if admin else "const select=document.getElementById('phaseSectionSelect');"
    assert marker in owner
    checked = subprocess.run(["node", "--check", "-"], input=owner, text=True,
                             encoding="utf-8", capture_output=True, timeout=10)
    assert checked.returncode == 0, checked.stderr


@pytest.mark.parametrize("kind", ["checks", "evidence"])
@pytest.mark.parametrize("saved", [False, True])
def test_dynamic_text_rows_use_the_rendered_template_without_saving_on_add_and_restore_failed_delete(kind, saved):
    html = render_editor(True, False)
    fragment = re.search(r'<template id="' + kind + r'-list-item-template">([\s\S]*?)</template>', html)
    assert fragment is not None
    elements = shell.Elements(fragment.group(1)).elements
    assert elements[0][0] == "li" and "data-id" not in elements[0][1]
    field = next(attrs for tag, attrs in elements if tag == "textarea")
    assert field["data-field"] == "description"
    assert field["onblur"] == "saveNewTextItem(this)"
    assert "base-textarea" in field["class"].split()
    assert 'data-page-state="empty"' not in fragment.group(1)
    code = controller_source("phase_detail", True)[0].decode()
    source = "\n".join([
        code[code.index("function syncTextItemList("):code.index("async function saveNewTextItem(")],
        code[code.index("async function deleteItem("):code.index("function appendTextItem(")],
        code[code.index("function appendTextItem("):
             code.index("/* ---------- Debounced phase meta save ---------- */")],
    ])
    script = """
const kind=KIND,saved=SAVED;
let writes=0,focus=0,initialized=0,destroyed=0,clones=0;
const count={textContent:'0'};let hasEmpty=true;
const empty={remove(){hasEmpty=false;}};
const list={id:kind+'-list',rows:[],
 querySelector:()=>hasEmpty?empty:null,querySelectorAll:()=>list.rows,
 closest:()=>({querySelector:()=>count}),
 appendChild(node){if(node.isEmpty)hasEmpty=true;else list.rows.push(node);}};
const makeRow=()=>{const row={nextSibling:null,
 closest:()=>list,querySelector:()=>input,querySelectorAll:()=>[input],
 remove(){list.rows=list.rows.filter(item=>item!==row);}};
 const input={value:'',focus(){focus++;},closest:()=>row};return row;};
const document={getElementById(id){if(id===list.id)return list;
 if(id===list.id+'-item-template')return{content:{firstElementChild:{cloneNode(){clones++;return makeRow();}}}};
 if(id===list.id+'-empty-template')return{content:{cloneNode:()=>({isEmpty:true})}};
 throw Error('unexpected element '+id);},createElement:()=>({appendChild(){},isEmpty:true})};
const window={PdlcTextarea:{initTextareaAutosize(){initialized++;},destroyTextareaAutosize(){destroyed++;}}};
const savePhase=async()=>{writes++;return saved;};
SOURCE
const add=kind==='checks'?addCheck:addEvidence;
add();const first=list.rows[0];
const afterAdd={writes,rows:list.rows.length,focus,initialized,clones,count:count.textContent,hasEmpty};
await deleteItem({closest:()=>first});
const afterDelete={writes,rows:list.rows.length,count:count.textContent,hasEmpty,
 restored:list.rows[0]===first,destroyed,initialized};
console.log(JSON.stringify({afterAdd,afterDelete}));
""".replace("KIND", json.dumps(kind)).replace("SAVED", json.dumps(saved)).replace("SOURCE", source)
    result = subprocess.run(["node", "--input-type=module", "-"], input=script, text=True,
                            encoding="utf-8", capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "afterAdd": {"writes": 0, "rows": 1, "focus": 1, "initialized": 1, "clones": 1,
                     "count": "1", "hasEmpty": False},
        "afterDelete": {"writes": 1, "rows": 0 if saved else 1, "count": "0" if saved else "1",
                        "hasEmpty": saved, "restored": not saved, "destroyed": 1,
                        "initialized": 1 if saved else 2},
    }
