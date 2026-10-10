"""A failed save must retain the author's text for correction or retry."""

import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("result", [None, {"resp": {"ok": False}, "data": {"ok": False, "error": "Conflict"}}])
@pytest.mark.parametrize("page,fn,next_fn", [
    ("phase_detail", "saveInstructionDescription", "addSkillToInstruction"),
    ("instructions", "updateInstruction", "toggleType"),
])
def test_instruction_save_failure_retains_entered_text(result, page, fn, next_fn):
    path = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates" / f"{page}.html"
    template = path.read_text(encoding="utf-8")
    start = template.index(f"async function {fn}(")
    end = template.index(f"async function {next_fn}(", start)
    source = template[start:end]
    script = "\n".join([
        "const messages=[];",
        "const input={value:'Edited instruction',disabled:false,",
        "dataset:{originalDescription:'Original instruction'},closest:()=>({dataset:{instructionId:'23'}})};",
        "const resizeInlineTextarea=()=>{}; const showToast=(text)=>messages.push(text); const phaseApiUrl=(url)=>url;",
        "const requestPhaseDetail=async()=>(" + json.dumps(result) + ");",
        "const requestInstruction=requestPhaseDetail;const instructionApiUrl=phaseApiUrl;",
        "const resizeInstructionTextarea=resizeInlineTextarea;",
        source,
        f"await {fn}(input);",
        "console.log(JSON.stringify({value:input.value,saved:input.dataset.originalDescription,disabled:input.disabled}));",
    ])
    completed = subprocess.run(
        ["node", "--input-type=module", "-"], input=script, text=True, capture_output=True, check=True, timeout=10,
    )
    assert json.loads(completed.stdout) == {
        "value": "Edited instruction", "saved": "Original instruction", "disabled": False,
    }


@pytest.mark.parametrize("change", ["blank_draft", "removed_row", "empty_existing"])
@pytest.mark.parametrize("field", ["checks", "evidence"])
def test_phase_save_keeps_response_ids_attached_to_submitted_rows(change, field):
    template = (Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/phase_detail.html").read_text(
        encoding="utf-8",
    )
    start = template.index("async function persistPhase()")
    end = template.index("document.addEventListener('DOMContentLoaded'", start)
    script = "\n".join([
        "const messages=[];let payload=null;",
        "const row=(text,id)=>({dataset:id?{id:String(id)}:{},classList:{contains:()=>false},",
        "querySelector:()=>({value:text}),setAttribute(k,v){this.dataset.id=v;}});",
        "const first=row('First');const second=row('Second');const blank=row('');",
        "const existing=row('',17);let rows;",
        "const change=" + json.dumps(change) + ";",
        "const field=" + json.dumps(field) + ";",
        "rows=change==='blank_draft'?[blank,first]:change==='empty_existing'?[existing]:[first,second];",
        "const document={querySelector(s){return s==='.wiki-header'?",
        "{querySelectorAll:()=>[{dataset:{field:'name'},value:'Phase'}]}:null;},",
        "querySelectorAll(s){return s.startsWith('#'+field+'-list')?rows:[];},getElementById:()=>null};",
        "const showToast=(text)=>messages.push(text);const phaseId=7;const phaseApiUrl=(url)=>url;",
        "const fetch=async(url,options)=>{payload=JSON.parse(options.body);",
        "if(change==='removed_row') rows=[second,blank];",
        "return {ok:true,json:async()=>({ok:true,ids:{checks:[],evidence:[],",
        "[field]:change==='removed_row'?[31,32]:[31]}})};};",
        template[start:end],
        "const saved=await persistPhase();",
        "console.log(JSON.stringify({saved,payload,first:first.dataset.id,second:second.dataset.id,",
        "blank:blank.dataset.id,existing:existing.dataset.id}));",
    ])
    completed = subprocess.run(
        ["node", "--input-type=module", "-"], input=script, text=True, capture_output=True, check=True, timeout=10,
    )
    result = json.loads(completed.stdout)
    if change == "empty_existing":
        assert result["saved"] is False
        assert result["payload"] is None
        assert result["existing"] == "17"
    else:
        assert result["saved"] is True
        assert result["first"] == "31"
        assert "blank" not in result
        if change == "removed_row":
            assert result["second"] == "32"
