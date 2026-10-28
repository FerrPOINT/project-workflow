// Manual DOM/API integration gate. Requires an isolated, explicitly marked fixture.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {resolve} from 'node:path';
const args=process.argv.slice(2),option=name=>args[args.indexOf(name)+1];
assert.ok(args.includes('--tooling-from')&&args.includes('--fixture-url'));
const require=createRequire(resolve(option('--tooling-from'),'package.json'));
const {JSDOM}=require('jsdom');
const base=new URL(option('--fixture-url'));
assert.ok(['127.0.0.1','localhost'].includes(base.hostname));
const metadata=await (await fetch(new URL('/__fixture',base))).json();
assert.equal(metadata.fixture,'workflow-incremental-owned');
const [a,b]=metadata.workflows;
const url=id=>new URL(`/workflow/workflows?profession_id=${metadata.profession_id}&workflow_id=${id}`,base);
const dom=new JSDOM((await (await fetch(url(a.id))).text()).replace(/<style[\s\S]*?<\/style>/g,''),{url:url(a.id).href,runScripts:'outside-only'});
const w=dom.window,d=w.document,shell=d.querySelector('#sidebar');
let confirmation=true,networkFailure=false,deferred=null,retireAttempts=0;
const notifications=[];w.AbortController=globalThis.AbortController;
w.PdlcChoice={initChoice(){},refreshChoice(){},destroyChoice(){}};
w.PdlcTextarea={initTextareaAutosize(){},destroyTextareaAutosize(){}};
w.PdlcBaseUI={initMenus(){},destroyMenus(){},notify(message){notifications.push(message);},requestConfirmation:async()=>confirmation};
w.WorkflowNavigation={preserveProjectContext(){}};
w.PdlcPlatformNavigation={saved(){},syncRoute(value,replace,state){w.history[replace?'replaceState':'pushState'](state??null,'',value);},navigate(){retireAttempts++;throw Error('Unexpected full navigation');},reload(){retireAttempts++;throw Error('Unexpected document reload');}};
w.fetch=async(value,options)=>{
 if(options?.headers?.['X-Workflow-View']){
  if(networkFailure)return new Response('Unavailable',{status:503});
  if(deferred){const wait=deferred;deferred=null;await wait;}
 }
 return fetch(new URL(value,w.location.href),options);
};
const controller=d.querySelector('script[data-workflow-controller]');
assert.ok(controller);
const pageReady=[];
w.WorkflowApplication={mount(factory){factory({
 on(target,type,callback,options){target.addEventListener(type,callback,options);},
 ready(callback){pageReady.push(callback);},cleanup(){},
 fetch:(...args)=>w.fetch(...args),notify:message=>notifications.push(message),
 expose:functions=>Object.assign(w,functions),
});}};
w.eval([...d.scripts].find(script=>script.textContent.includes('function pluralizeRu(')).textContent);
w.WorkflowPageControllers=Object.create(null);
for(const asset of d.querySelectorAll('script[src*="/ui-assets/controllers/"]')){
 const response=await fetch(new URL(asset.src,base));assert.equal(response.status,200);w.eval(await response.text());
}
w.eval(controller.textContent);pageReady.forEach(callback=>callback());
d.dispatchEvent(new w.Event('DOMContentLoaded'));
const state=()=>JSON.parse(d.querySelector('#workflowEditorState').textContent);
assert.equal(state().selected_workflow_id,a.id);
await w.selectWorkflow(b.id);
assert.equal(state().selected_workflow_id,b.id,notifications.join("; "));assert.equal(d.querySelector('#sidebar'),shell);
assert.equal(new URL(w.location.href).searchParams.get('workflow_id'),String(b.id));
// Modes update only phases and preserve a draft in the workflow form.
w.startEditWorkflow();const form=d.querySelector('#workflowForm'),input=d.querySelector('#workflowName');input.value='Не терять этот ввод';
const modeUrl=url(b.id);modeUrl.searchParams.set('mode_id',b.modes[1]);
assert.equal(await w.loadWorkflowEditor(modeUrl.href,{keepForm:true}),true);
assert.equal(d.querySelector('#workflowForm'),form);assert.equal(input.value,'Не терять этот ввод');
assert.equal(d.querySelector('#phasesTimeline').dataset.modeId,String(b.modes[1]));
confirmation=false;assert.equal(await w.selectWorkflow(a.id),false);assert.equal(input.value,'Не терять этот ввод');
confirmation=true;await w.selectWorkflow(a.id);assert.equal(state().selected_workflow_id,a.id);
// A slow old response cannot overwrite the more recent selection.
let release;deferred=new Promise(resolve=>{release=resolve;});const slow=w.selectWorkflow(b.id);
await new Promise(resolve=>setImmediate(resolve));await w.selectWorkflow(a.id);
release();await slow;assert.equal(state().selected_workflow_id,a.id);
// Failed reads leave both the visible state and the committed URL intact.
networkFailure=true;const before=d.querySelector('#workflowCrud'),beforeUrl=w.location.href;
assert.equal(await w.selectWorkflow(b.id),false);assert.equal(d.querySelector('#workflowCrud'),before);assert.equal(w.location.href,beforeUrl);networkFailure=false;
// An edit made after requesting a new view must not be silently discarded.
w.startEditWorkflow();let releaseEdit;deferred=new Promise(resolve=>{releaseEdit=resolve;});const late=w.selectWorkflow(b.id);
await new Promise(resolve=>setImmediate(resolve));d.querySelector('#workflowName').value='Правка во время запроса';releaseEdit();assert.equal(await late,false);
assert.equal(d.querySelector('#workflowName').value,'Правка во время запроса');w.cancelWorkflowForm();
// The four real owner mutations refresh the phase block without remounting the shell.
const count=()=>d.querySelectorAll('#phasesTimeline .timeline-item').length;
const initial=count();await w.addPhaseAfter(d.querySelector('.phase-add-btn'));assert.equal(count(),initial+1);
let phase=d.querySelector('.timeline-item');const phaseId=phase.dataset.phaseId;
await w.togglePhaseType(phase.querySelector('button'));assert.equal(d.querySelector(`#phase-${phaseId}`).dataset.executionType,'parallel');
phase=d.querySelector(`#phase-${phaseId}`);await w.movePhase(phase.querySelector('button'),1);
assert.notEqual(d.querySelector('.timeline-item').dataset.phaseId,phaseId);
await w.deletePhase(d.querySelector(`#phase-${phaseId} button`));assert.equal(count(),initial);
const beforeUncertain=count();networkFailure=true;
await w.addPhaseAfter(d.querySelector('.phase-add-btn'));
assert.equal(d.querySelector('#workflowReadbackError').hidden,false);
await w.addPhaseAfter(d.querySelector('.phase-add-btn'));
networkFailure=false;await w.retryWorkflowReadback();assert.equal(count(),beforeUncertain+1);
assert.equal(d.querySelector('#workflowReadbackError').hidden,true);
// Workflow CRUD also keeps the shell and uses authoritative readback.
w.startEditWorkflow();d.querySelector('#workflowName').value='Переименованный процесс';await w.saveWorkflow();
assert.equal(d.querySelector('#workflowSummaryName').textContent,'Переименованный процесс');
w.startCreateWorkflow();d.querySelector('#workflowName').value='Созданный процесс';networkFailure=true;await w.createWorkflow();
assert.equal(d.querySelector('#workflowReadbackError').hidden,false);networkFailure=false;await w.retryWorkflowReadback();
assert.equal(d.querySelector('#workflowSummaryName').textContent,'Созданный процесс');
const createdId=state().selected_workflow_id;await w.deleteWorkflow();assert.notEqual(state().selected_workflow_id,createdId);
assert.equal(d.querySelector('#sidebar'),shell);assert.equal(retireAttempts,0);
// A response arriving after access retirement must not recreate removed content.
let retireRelease;deferred=new Promise(resolve=>{retireRelease=resolve;});
const afterRetirement=w.loadWorkflowEditor(url(b.id).href);await new Promise(resolve=>setImmediate(resolve));
d.body.replaceChildren();retireRelease();assert.equal(await afterRetirement,false);assert.equal(d.body.childElementCount,0);
console.log('PASS: workflow/mode selection, draft continuity, cancellation, stale reads, HTTP failure, late edits, four API mutations; no document navigation');
w.close();
