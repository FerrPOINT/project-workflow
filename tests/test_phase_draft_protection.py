"""Execute the actual editor script at its input/save boundary using the existing Node test pattern."""
import json
import os
import subprocess
from pathlib import Path

from project_workflow.interfaces.ui.controller_assets import controller_source

ROOT = Path(__file__).parents[1]
TEMPLATES = ROOT / "project_workflow/interfaces/ui/templates"


def editor_script():
    baseline = os.environ.get("WORKFLOW_DRAFT_BASELINE")
    if baseline:
        template = subprocess.check_output(
            ["git", "show", f"{baseline}:project_workflow/interfaces/ui/templates/phase_detail.html"],
            cwd=ROOT, text=True, encoding="utf-8",
        )
    else:
        template = controller_source("phase_detail", True)[0].decode()
    tracker = (TEMPLATES / "base/draft-state.js").read_text(encoding="utf-8").replace("export function", "function")
    prefix = template[template.index("const phaseId ="):template.index("const selectedNamespaceId =")]
    prefix = prefix.replace("{{ phase.id }}", "7").replace("config.phaseId", "7")
    # Autosize now belongs to Base; keep this boundary tied to the input listener.
    listener_marker = (
        "page.on(document,'input'" if "page.on(document,'input'" in template
        else "document.addEventListener('input'"
    )
    listener_start = template.index(listener_marker)
    listener = template[listener_start:template.index("\n});", listener_start) + len("\n});")]
    ready_marker = "page.ready(" if "page.ready(" in template else "document.addEventListener('DOMContentLoaded'"
    save = template[template.index("let _saveTimer"):template.index(ready_marker, template.index("let _saveTimer"))]
    controls_start = template.index("function updateInstructionControls()")
    controls = "\n".join([
        template[
            template.index("function getInstructionItems()"):template.index("function renderInstructionTimeline(")
        ],
        template[
            controls_start:template.index("async function persistInstructionOrder(")
        ],
    ])
    return "\n".join([
        tracker,
        "const listeners=new Map();const fields=[{dataset:{field:'name'},value:'Original'},"
        "{dataset:{field:'description'},value:''}];",
        "const window={PdlcPlatformNavigation:{createDraftTracker}};const selectedNamespaceId=null;",
        "const document={addEventListener:(type,fn)=>listeners.set(type,fn),getElementById:()=>null,",
        "querySelector:s=>s==='.wiki-header'?{querySelectorAll:()=>fields}:null,",
        "querySelectorAll:s=>s.startsWith('.wiki-header')?fields:[]};",
        "const showToast=()=>{};const phaseApiUrl=u=>u;const resizeInlineTextarea=()=>{};",
        "const config={basePath:''};const page={on:(target,type,fn)=>target.addEventListener(type,fn)};",
        prefix, controls, listener, save,
        "if(typeof phaseDraft!=='undefined'){phaseDraft=createDraftTracker();phaseSignature=currentPhaseSignature();",
        "confirmedPhase={name:'Original',description:'',execution_type:'sync',parallel_with_phase_id:null,checks:[],evidence:[]};}",
        "const edit=value=>{fields[0].value=value;"
        "listeners.get('input')({target:{matches:()=>false,closest:()=>({})}});};",
        "const dirty=()=>window.hasUnsavedWorkflowChanges?.()??false;",
    ])


def run_editor(scenario):
    result = subprocess.run(
        ["node", "--input-type=module", "-"], input=editor_script() + "\n" + scenario,
        text=True, encoding="utf-8", capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_input_is_protected_before_blur_or_debounce():
    assert run_editor("const clean=dirty();edit('Edited');console.log(JSON.stringify({clean,edited:dirty()}));") == {
        "clean": False, "edited": True,
    }


def test_old_save_acknowledgement_does_not_clean_newer_input():
    result = run_editor("""
const payloads=[];let ack;globalThis.fetch=async(u,o)=>{
  payloads.push(JSON.parse(o.body));return new Promise(resolve=>{
    ack=()=>resolve({ok:true,json:async()=>({ok:true,ids:{checks:[],evidence:[]}})});
  });
};
edit('First');const first=savePhase();await new Promise(setImmediate);const pending=dirty();
edit('Second');ack();await first;const older=dirty();
const second=savePhase();await new Promise(setImmediate);ack();await second;
console.log(JSON.stringify({pending,older,current:dirty(),names:payloads.map(p=>p.name)}));
""")
    assert result == {"pending": True, "older": True, "current": False, "names": ["First", "Second"]}


def test_unknown_save_is_not_replayed_until_readback():
    result = run_editor("""
let writes=0,reads=0;globalThis.fetch=async(u,o)=>{
  if(o){writes++;throw new Error('connection lost');}reads++;
  return {ok:true,json:async()=>({ok:true,phase:{name:'Edited',description:'',execution_type:'sync',
    parallel_with_phase_id:null,checks:[],evidence:[],instructions:[]}})};
};
edit('Edited');await savePhase();await savePhase();const before=dirty();await reconcilePhaseSave();
console.log(JSON.stringify({writes,reads,before,after:dirty()}));
""")
    assert result == {"writes": 1, "reads": 1, "before": True, "after": False}


def test_failed_save_retains_the_draft_and_allows_a_deliberate_retry():
    result = run_editor("""
let writes=0;globalThis.fetch=async()=>++writes===1?{ok:false,status:422}:
  {ok:true,json:async()=>({ok:true,ids:{checks:[],evidence:[]}})};
edit('Edited');await savePhase();const failed=dirty();await savePhase();
console.log(JSON.stringify({writes,failed,after:dirty()}));
""")
    assert result == {"writes": 2, "failed": True, "after": False}


def test_readback_of_older_version_keeps_newer_input_dirty():
    result = run_editor("""
let writes=0;globalThis.fetch=async(u,o)=>{
  if(o){writes++;throw new Error('lost');}
  return {ok:true,json:async()=>({ok:true,phase:{name:'First',description:'',execution_type:'sync',
    parallel_with_phase_id:null,checks:[],evidence:[],instructions:[]}})};
};
edit('First');await savePhase();edit('Second');await reconcilePhaseSave();
console.log(JSON.stringify({writes,dirty:dirty(),value:fields[0].value,uncertain:phaseDraft.uncertain}));
""")
    assert result == {"writes": 1, "dirty": True, "value": "Second", "uncertain": False}


def test_unrelated_readback_does_not_unlock_an_uncertain_save():
    result = run_editor("""
let writes=0;globalThis.fetch=async(u,o)=>{
  if(o){writes++;throw new Error('lost');}
  return {ok:true,json:async()=>({ok:true,phase:{name:'Other writer',description:'',execution_type:'sync',
    parallel_with_phase_id:null,checks:[],evidence:[],instructions:[]}})};
};
edit('Edited');await savePhase();await reconcilePhaseSave();await savePhase();
console.log(JSON.stringify({writes,dirty:dirty(),value:fields[0].value,uncertain:phaseDraft.uncertain}));
""")
    assert result == {"writes": 1, "dirty": True, "value": "Edited", "uncertain": True}


def test_discard_stops_a_queued_save_before_network_submission():
    result = run_editor("""
let writes=0;globalThis.fetch=async()=>{writes++;throw new Error('unexpected');};
edit('Edited');const queued=savePhase();savingStopped=true;await queued;
console.log(JSON.stringify({writes,dirty:dirty()}));
""")
    assert result == {"writes": 0, "dirty": True}


def test_phase_mode_failure_keeps_the_chosen_value_as_a_draft():
    template = controller_source("phase_detail", True)[0].decode()
    start = template.index("async function togglePhaseMode(el)")
    end = template.index("/* ---------- Instructions list", start)
    result = subprocess.run(
        ["node", "--input-type=module", "-"], input="\n".join([
            "let edits=0,mode='sync';const setPhaseMode=(el,next)=>{mode=next;el.dataset.mode=next};",
            "const notePhaseEdit=()=>{edits++};const savePhase=async()=>false;",
            template[start:end],
            "const el={dataset:{mode:'sync'},setAttribute:()=>{},removeAttribute:()=>{}};",
            "await togglePhaseMode(el);console.log(JSON.stringify({mode,edits,pending:el.dataset.saving??null}));",
        ]), text=True, encoding="utf-8", capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"mode": "parallel", "edits": 1, "pending": None}
