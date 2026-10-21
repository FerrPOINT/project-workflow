"""Submitted Workflow fields and identity cannot change before the write settles."""

import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.ui
TEMPLATE = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/workflows.html"


@pytest.mark.parametrize("mode", ["edit", "create"])
@pytest.mark.parametrize("outcome", ["saved", "failed", "network"])
def test_pending_workflow_write_locks_fields_identity_and_duplicate_submit(mode, outcome):
    template = TEMPLATE.read_text(encoding="utf-8")

    def between(start, end):
        return template[template.index(start):template.index(end)]

    source = "\n".join([
        between("function currentWorkflowPayload()", "function syncWorkflowNav()"),
        between("function startEditWorkflow()", "function setWorkflowFormMode("),
        between("function startCreateWorkflow()", "function renderWorkflowNav()"),
        between("function saveWorkflow()", "async function deleteWorkflow()"),
        between("function setWorkflowWritePending(", "renderWorkflowNav();\nif(selectedWorkflowId"),
    ])
    script = """
const mode=MODE,outcome=OUTCOME;
let selectedWorkflowId=mode==='edit'?1:null,workflowFormMode=mode,workflowWritePending=false;
let workflowEditorVisible=true;
const field=(value,kind='input')=>({value,disabled:false,setAttribute(){},
 matches:selector=>kind==='select'&&selector==='select[data-base-choice]'});
const name=field('Submitted name'),description=field('Submitted description');
const submit=field(''),cancel=field(''),remove=field('');
const picker=field('','select'),create=field(''),nav=field('');const choiceStates=[];
const form={setAttribute(){},querySelectorAll:()=>[name,description,submit,cancel,remove]};
const elements={workflowName:name,workflowDescription:description,workflowSubmitButton:submit,workflowForm:form};
const document={getElementById:id=>elements[id],querySelectorAll:()=>[picker,create,nav]};
const window={PdlcPlatformNavigation:{saved(){},navigate(){}},
 PdlcChoice:{refreshChoice:control=>{if(control===picker)choiceStates.push(control.disabled)}}};
const showToast=()=>{},showRequestError=()=>{},setWorkflowFormMode=()=>{};
const currentWorkflowId=selectedWorkflowId;
const workflowApiUrl=id=>'/api/workflows'+(id==null?'':'/'+id);
let writes=0,ack;const reloadWorkflows=async()=>true,setWorkflowEditorVisible=()=>{};
const fetch=()=>{writes++;return new Promise((resolve,reject)=>{ack=()=>{
 if(outcome==='network')reject(new Error('offline'));
 else resolve({json:async()=>({ok:outcome==='saved',workflow_id:2})});
};});};
SOURCE
submitWorkflow();submitWorkflow();
startCreateWorkflow();selectWorkflow(2);cancelWorkflowForm();
const pending={locked:[name,description,submit,cancel,remove,picker,create,nav].every(c=>c.disabled),
 identityUnchanged:selectedWorkflowId===currentWorkflowId,writes};
ack();await new Promise(setImmediate);await new Promise(setImmediate);
console.log(JSON.stringify({pending,choiceStates,unlocked:[name,description,submit,cancel,remove,picker,create,nav]
 .every(c=>!c.disabled),name:name.value,description:description.value}));
""".replace("MODE", json.dumps(mode)).replace("OUTCOME", json.dumps(outcome)).replace("SOURCE", source)
    completed = subprocess.run(
        ["node", "--input-type=module", "-"], input=script, text=True,
        encoding="utf-8", capture_output=True, timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "pending": {"locked": True, "identityUnchanged": True, "writes": 1},
        "choiceStates": [True, False], "unlocked": True,
        "name": "Submitted name", "description": "Submitted description",
    }
