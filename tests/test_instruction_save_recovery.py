"""Unconfirmed instruction writes require readback before another submission."""

import json
import subprocess
from pathlib import Path

import pytest

from project_workflow.interfaces.ui.controller_assets import controller_source
from tests.test_phase_draft_protection import run_editor

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("response", ["truncated", "missing_verdict", "null", "rejected"])
def test_instruction_response_recovery_preserves_newer_draft(response):
    source = controller_source("phase_detail", True)[0].decode()
    tracker = (
        Path(__file__).parents[1]
        / "project_workflow/interfaces/ui/templates/base/draft-state.js"
    ).read_text(encoding="utf-8").replace("export function", "function")
    prefix = source[source.index("const phaseId ="):source.index("const selectedNamespaceId =")]
    request = source[
        source.index("async function requestPhaseDetail("):source.index("async function addInstructionAfter(")
    ]
    save = source[
        source.index("async function saveInstructionDescription("):source.index("function openInstructionSkillEditor(")
    ]
    reconcile_start = source.index("function phaseMatches(")
    reconcile = source[reconcile_start:source.index("page.ready(", reconcile_start)]
    save_editor = source[source.index("async function saveEditorChanges("):reconcile_start]
    script = "\n".join([
        tracker,
        "const config={basePath:'',phaseId:7};const phaseApiUrl=u=>u;",
        "const window={PdlcPlatformNavigation:{createDraftTracker},PdlcTextarea:{refreshTextareaAutosize(){}}};",
        "const controls=Object.fromEntries(['phaseSaveEditor','phaseSaveReadback','phaseSaveRecovery']"
        ".map(id=>[id,{hidden:true,setAttribute(){}}]));",
        "const document={getElementById:id=>controls[id],"
        "querySelectorAll:s=>s==='.timeline-name-input'?[input]:[]};",
        "const showToast=()=>{};const showRequestError=()=>{};const updateInstructionControls=()=>{};",
        "const input={value:'Sent B',disabled:false,dataset:{originalDescription:'Original'},"
        "closest:()=>({dataset:{instructionId:'23'}})};",
        prefix, request, save, reconcile, save_editor,
        "phaseDraft=createDraftTracker();let phaseWrites=0;const savePhase=async()=>{phaseWrites++;};",
        "const response=" + json.dumps(response) + ";",
        "const payloads=[];let reads=0;const fetch=async(url,options)=>{",
        "if(!options){reads++;return {ok:true,json:async()=>({ok:true,"
        "phase:{instructions:[{id:23,description:'Sent B'}]}})};}",
        "payloads.push(JSON.parse(options.body));",
        "if(payloads.length>1)return {ok:true,status:200,json:async()=>({ok:true,instruction:{description:'New C'}})};",
        "return {ok:response!=='rejected',status:response==='rejected'?422:200,json:async()=>{",
        "if(response==='truncated')throw new TypeError('Response body terminated');",
        "return response==='null'?null:response==='missing_verdict'?{}:{ok:false,error:'Rejected'};}};};",
        "const draft=instructionDraft(input);draft.edit();await saveInstructionDescription(input);",
        "const first={uncertain:draft.uncertain,readback:!controls.phaseSaveReadback.hidden,"
        "retry:!controls.phaseSaveEditor.hidden,dirty:draft.dirty,disabled:input.disabled};",
        "input.value='New C';draft.edit();",
        "if(response!=='rejected'){await saveInstructionDescription(input);}",
        "const writesBeforeReadback=payloads.length;await reconcilePhaseSave();",
        "const recovered={value:input.value,dirty:draft.dirty,uncertain:draft.uncertain};",
        "await saveEditorChanges();",
        "console.log(JSON.stringify({first,writesBeforeReadback,reads,recovered,payloads,phaseWrites,"
        "final:{value:input.value,dirty:draft.dirty,uncertain:draft.uncertain,disabled:input.disabled}}));",
    ])
    completed = subprocess.run(
        ["node", "--input-type=module", "-"], input=script,
        text=True, encoding="utf-8", capture_output=True, timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    uncertain = response != "rejected"
    assert result["first"] == {
        "uncertain": uncertain, "readback": uncertain, "retry": not uncertain,
        "dirty": True, "disabled": False,
    }
    assert result["writesBeforeReadback"] == 1
    assert result["reads"] == int(uncertain)
    assert result["recovered"] == {"value": "New C", "dirty": True, "uncertain": False}
    assert result["payloads"] == [{"description": "Sent B"}, {"description": "New C"}]
    assert result["phaseWrites"] == 0
    assert result["final"] == {"value": "New C", "dirty": False, "uncertain": False, "disabled": False}


@pytest.mark.parametrize("state", ["clean", "dirty", "pending", "uncertain"])
def test_editor_retry_only_submits_a_dirty_idle_phase(state):
    result = run_editor("""
const state=""" + json.dumps(state) + """;
let writes=0;globalThis.fetch=async()=>{
  writes++;return {ok:true,json:async()=>({ok:true,ids:{checks:[],evidence:[]}})};
};
if(state!=='clean')edit('Edited');
if(state==='pending'||state==='uncertain'){
  const ticket=phaseDraft.beginSave();
  if(state==='uncertain')phaseDraft.finishSave(ticket,'unknown');
}
await saveEditorChanges();
console.log(JSON.stringify({writes,dirty:phaseDraft.dirty,pending:phaseDraft.pending,uncertain:phaseDraft.uncertain}));
""")
    assert result == {
        "writes": int(state == "dirty"), "dirty": state in {"pending", "uncertain"},
        "pending": state == "pending", "uncertain": state == "uncertain",
    }
