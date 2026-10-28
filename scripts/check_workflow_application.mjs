// Manual integration gate against the real owner in a disposable loopback fixture.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {resolve} from 'node:path';
import {readFileSync} from 'node:fs';
const args=process.argv.slice(2),option=name=>args[args.indexOf(name)+1];
assert.ok(args.includes('--tooling-from')&&args.includes('--fixture-url'));
const require=createRequire(resolve(option('--tooling-from'),'package.json'));
const {JSDOM,VirtualConsole}=require('jsdom');
const base=new URL(option('--fixture-url'));assert.ok(['localhost','127.0.0.1'].includes(base.hostname));
const metadata=await(await fetch(new URL('/__fixture',base))).json();assert.equal(metadata.fixture,'workflow-incremental-owned');
const errors=[],messages=[],console=new VirtualConsole();console.on('jsdomError',error=>errors.push(error.message));console.on('error',(...args)=>errors.push(args.map(value=>value?.stack||value).join(' ')));
const url=new URL('/workflow/',base);
const dom=new JSDOM((await(await fetch(url)).text()).replace(/<style[\s\S]*?<\/style>/g,match=>match.replace(/[\s\S]+/, '<style data-workflow-page-style></style>')),{url:url.href,runScripts:'dangerously',pretendToBeVisual:true,virtualConsole:console,beforeParse(w){
 w.fetch=(value,options={})=>{const abort=new AbortController();if(options.signal){if(options.signal.aborted)abort.abort();else options.signal.addEventListener('abort',()=>abort.abort(),{once:true});}return fetch(new URL(value,w.location.href),{...options,signal:abort.signal});};
 w.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}});
 w.scrollTo=()=>{};w.HTMLElement.prototype.scrollIntoView=()=>{};
 w.ResizeObserver=class{observe(){}disconnect(){}};
 w.IntersectionObserver=class{observe(){}disconnect(){}};
 w.PdlcChoice={initChoice(){},refreshChoice(){},destroyChoice(){}};
 w.PdlcTextarea={initTextareaAutosize(){},refreshTextareaAutosize(){},destroyTextareaAutosize(){}};
 w.PdlcClipboard={initCopyButton(){},destroyCopyButton(){}};
}});
const w=dom.window,d=w.document;await new Promise(resolve=>w.addEventListener('load',resolve,{once:true}));
const realNotify=w.PdlcBaseUI.notify;
w.PdlcBaseUI.notify=(message,options={})=>{if(options.duration===Infinity)return realNotify(message,options);messages.push(message);};
for(const asset of d.querySelectorAll('script[src*="/ui-assets/controllers/"]')){
 const response=await fetch(new URL(asset.src,base));assert.equal(response.status,200);assert.match(response.headers.get('cache-control'),/immutable/);w.eval(await response.text());
}
const vendor=await(await fetch(new URL('/workflow/ui-assets/htmx-2.0.11.min.js',base))).text();
// jsdom requires the XPath result type, unlike browser XPathExpression.evaluate.
const evaluate=w.XPathExpression.prototype.evaluate;w.XPathExpression.prototype.evaluate=function(node,type,result){return evaluate.call(this,node,type??0,result);};
w.eval(vendor);
w.eval(readFileSync(new URL('../project_workflow/interfaces/ui/templates/base/draft-state.js',import.meta.url),'utf8').replaceAll('export ','')+';window.PdlcPlatformNavigation.createDraftTracker=createDraftTracker;');
w.localStorage.setItem('phase-view-mode','timeline');
let current=true,confirmation=true,native=0;
let fail=false,delay=null,skillFailure=false,skillWrites=0;const realFetch=w.fetch;w.fetch=async(value,options)=>{if(options?.method==='PUT'&&String(value).includes('/api/instructions/')&&Array.isArray(JSON.parse(options.body||'{}').skills)){skillWrites++;if(skillFailure)return new Response(JSON.stringify({ok:false,error:'Skill rejected'}),{status:422,headers:{'Content-Type':'application/json'}});}if(options?.headers?.['X-Workflow-View']==='page-v1'){if(fail)return new Response('Unavailable',{status:503});if(delay){const pending=delay;delay=null;await pending;}}return realFetch(value,options);};
w.PdlcPlatformNavigation.navigate=()=>{native++;};w.PdlcPlatformNavigation.reload=()=>{native++;};
w.WorkflowApplication.start({isCurrent:()=>current,canLeave:async()=>confirmation,trackForms(){},retire(){current=false;}});
await new Promise(resolve=>setImmediate(resolve));
const shell=d.querySelector('#sidebar'),header=d.querySelector('[data-platform-header]');
const page=()=>JSON.parse(d.querySelector('[data-workflow-page]').textContent);
const assertShell=()=>{assert.equal(d.querySelector('#sidebar'),shell);assert.equal(d.querySelector('[data-platform-header]'),header);assert.equal(native,0);};
const go=async path=>{assert.equal(await w.WorkflowApplication.navigate('/workflow'+path),true,JSON.stringify({path,messages,errors,current,url:w.location.href}));assertShell();assert.equal(d.querySelector('main').getAttribute('aria-busy'),'false');const radios=[...d.querySelectorAll('input[name="phase-view"]')];if(radios.length)assert.deepEqual(radios.filter(radio=>radio.checked).map(radio=>radio.value),['timeline'],'new page phase-view must initialize after old main is removed');};
for(let round=0;round<3;round++)for(const path of ['/namespaces?profession_id=1','/namespaces/new','/workflows?profession_id=1','/tasks?profession_id=1','/settings','/'])await go(path);
await go('/workflows?profession_id=1&workflow_id='+metadata.workflows[0].id);
// Exercise the browser's synchronous inline-script timing explicitly: incoming
// main is inserted before outgoing main removal. jsdom normally defers scripts.
const realSwap=w.htmx.swap;
w.htmx.swap=(old,html,options,context)=>{
 const template=d.createElement('template');template.innerHTML=html;
 const main=template.content.querySelector('main.main');old.before(main);
 w.eval(main.querySelector('[data-workflow-controller]').textContent);
 old.remove();context.afterSettleCallback();
};
try{await go('/workflows?profession_id=1&workflow_id='+metadata.workflows[1].id);}finally{w.htmx.swap=realSwap;}
await go('/workflows?profession_id=1&workflow_id='+metadata.workflows[0].id);
assert.equal(typeof w.selectWorkflow,'function');w.startEditWorkflow();
const input=d.querySelector('#workflowName');input.value='Сохранить черновик';confirmation=false;
assert.equal(await w.WorkflowApplication.navigate('/workflow/settings'),false);assert.equal(d.querySelector('#workflowName'),input);assert.equal(input.value,'Сохранить черновик');
confirmation=true;await go('/settings');assert.equal(w.startEditWorkflow,undefined);
await go('/workflows?profession_id=1&workflow_id='+metadata.workflows[0].id);
const phaseLink=d.querySelector('a[href*="/phase/"]');assert.ok(phaseLink);const phaseUrl=new URL(phaseLink.href);await go(phaseUrl.pathname.slice('/workflow'.length)+phaseUrl.search);
assert.equal(typeof w.scheduleSave,'function');
// Shared instruction actions exercise the real owner API and page readback.
const instructionRows=()=>[...d.querySelectorAll('#instructionsTimeline .timeline-item')];
async function instructionReadback(predicate){
 for(let attempt=0;attempt<200;attempt++){
  if(d.querySelector('main')?.dataset.workflowReadState==='ready'&&!d.querySelector('#phaseSaveEditor')?.matches('[aria-busy="true"]')&&!d.querySelector('.instruction-card-actions .phase-add-btn')?.disabled&&predicate())return;
  await new Promise(resolve=>setTimeout(resolve,10));
 }
 assert.fail('Instruction readback did not settle: '+messages.join('; '));
}
await w.addInstructionLast();await instructionReadback(()=>instructionRows().length===1);
let instructionFirst=instructionRows()[0].dataset.instructionId;
assert.equal(d.querySelector('.instruction-card-actions').querySelectorAll('button').length,5);
assert.equal(d.querySelector('.phase-order-controls'),null);
assert.equal(skillPlacement(),true);
function skillPlacement(){const list=d.querySelector('.instruction-skill-labels');return list.lastElementChild.classList.contains('skill-add-item')&&!!list.querySelector('.skill-add-trigger.base-badge-button');}

// Skill edits patch only confirmed chips; they do not replace the editor or its draft.
const skillCard=instructionRows()[0].querySelector('.timeline-card');
const skillInput=skillCard.querySelector('.skill-candidate'),skillForm=skillCard.querySelector('.skill-add-form');
const skillNames=()=>[...skillCard.querySelectorAll('[data-instruction-skill]')].map(x=>x.dataset.instructionSkill);
const skillName='инструмент × <skill> "тест"';
assert.equal(skillCard.querySelector('details'),null);assert.equal(skillForm.hidden,true);
const skillsGroup=skillCard.querySelector('.instruction-skills');
assert.equal(d.getElementById(skillsGroup.getAttribute('aria-labelledby')).textContent,'Навыки');

skillCard.querySelector('.skill-add-trigger').click();assert.equal(d.activeElement,skillInput);
skillInput.value=skillName;skillFailure=true;await w.addSkillToInstruction(skillInput);
assert.equal(messages.pop(),'Skill rejected');assert.equal(skillInput.value,skillName);assert.deepEqual(skillNames(),[]);assert.equal(skillInput.disabled,false);
skillFailure=false;const pendingDescription=skillCard.querySelector('.timeline-name-input');
pendingDescription.value='Несохранённое описание рядом с навыками';pendingDescription.dispatchEvent(new w.Event('input',{bubbles:true}));
const beforeSkillWrites=skillWrites;await Promise.all([w.addSkillToInstruction(skillInput),w.addSkillToInstruction(skillInput)]);
assert.equal(skillWrites-beforeSkillWrites,1,'one in-flight write per instruction');
assert.deepEqual(skillNames(),[skillName]);assert.equal(skillCard.isConnected,true);assert.equal(skillPlacement(),true);
const chipRemove=skillCard.querySelector('.skill-remove-btn');
assert.ok(chipRemove.closest('.base-badge'),'remove belongs to the same visible pill');
assert.ok(chipRemove.querySelector('svg[aria-hidden="true"]'));
assert.equal(chipRemove.getAttribute('aria-label'),'Убрать навык '+skillName+' из инструкции 1');
assert.equal(chipRemove.title,'Убрать навык '+skillName);

assert.equal(pendingDescription.value,'Несохранённое описание рядом с навыками');assert.equal(w.hasUnsavedWorkflowChanges(),true);
assert.equal(skillCard.querySelector('skill'),null);assert.equal(skillForm.hidden,true);assert.equal(d.activeElement,skillCard.querySelector('.skill-add-trigger'));
await w.saveInstructionDescription(pendingDescription);
skillCard.querySelector('.skill-add-trigger').click();skillInput.value=skillName;
skillForm.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await instructionReadback(()=>skillForm.hidden&&!skillInput.disabled);assert.deepEqual(skillNames(),[skillName],'duplicate skill is normalized');assert.equal(skillCard.isConnected,true);
skillCard.querySelector('.skill-add-trigger').click();skillInput.value='Отменённый ввод';const beforeCancel=skillWrites;
skillInput.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
assert.equal(skillForm.hidden,true);assert.equal(skillInput.value,'');assert.equal(skillWrites,beforeCancel);
// The compact field is a tag input, and each existing name opens its own editor.
assert.ok(skillInput.classList.contains('base-badge-input'));
assert.equal(skillForm.querySelectorAll('button').length,0,'Enter/Escape own the compact field without a large action row');
function renameEditor(){skillCard.querySelector('.skill-rename-btn').click();const input=skillCard.querySelector('.skill-rename-input:not([hidden])');assert.equal(d.activeElement,input);return input;}
const renameKey=(input,key)=>input.dispatchEvent(new w.KeyboardEvent('keydown',{key,bubbles:true,cancelable:true}));
let editor=renameEditor();editor.value='Отмена переименования';let renameWrites=skillWrites;renameKey(editor,'Escape');
assert.equal(editor.hidden,true);assert.deepEqual(skillNames(),[skillName]);assert.equal(skillWrites,renameWrites);
editor=renameEditor();const renamed='переименованный <safe> "навык"';editor.value=renamed;skillFailure=true;renameKey(editor,'Enter');
await instructionReadback(()=>!skillsGroup.hasAttribute('aria-busy'));
assert.equal(messages.pop(),'Skill rejected');assert.equal(editor.hidden,false);assert.equal(editor.value,renamed);assert.deepEqual(skillNames(),[skillName]);
skillFailure=false;renameWrites=skillWrites;renameKey(editor,'Enter');renameKey(editor,'Enter');
await instructionReadback(()=>!skillsGroup.hasAttribute('aria-busy')&&skillNames()[0]===renamed);
assert.equal(skillWrites-renameWrites,1);assert.equal(skillCard.querySelector('.skill-rename-btn').textContent,renamed);assert.equal(skillCard.querySelector('safe'),null);assert.equal(skillPlacement(),true);assertShell();
// A duplicate/empty rename never silently merges or deletes a different tag.
skillCard.querySelector('.skill-add-trigger').click();skillInput.value='Другой навык';await w.addSkillToInstruction(skillInput);
editor=renameEditor();renameWrites=skillWrites;editor.value='Другой навык';renameKey(editor,'Enter');
assert.equal(messages.pop(),'Такой навык уже добавлен');assert.equal(skillWrites,renameWrites);assert.deepEqual(skillNames(),[renamed,'Другой навык']);
editor.value='   ';renameKey(editor,'Enter');assert.equal(editor.hidden,true);assert.equal(skillWrites,renameWrites);assert.deepEqual(skillNames(),[renamed,'Другой навык']);
// Blur commits at the same boundary; a remove click does not commit the text draft.
editor=renameEditor();editor.value='Сохранено при уходе';skillCard.querySelector('.skill-add-trigger').focus();
await instructionReadback(()=>!skillsGroup.hasAttribute('aria-busy')&&skillNames()[0]==='Сохранено при уходе');
editor=renameEditor();editor.value='Не сохранять перед удалением';renameWrites=skillWrites;const removeDuringRename=skillCard.querySelector('.skill-remove-btn');removeDuringRename.focus();removeDuringRename.click();
await instructionReadback(()=>!skillsGroup.hasAttribute('aria-busy')&&skillNames().length===1);
assert.equal(skillWrites-renameWrites,1,'cross deletes without a competing rename');assert.deepEqual(skillNames(),['Другой навык']);assertShell();
await w.removeSkillFromInstruction(skillCard.querySelector('.skill-remove-btn'));
assert.deepEqual(skillNames(),[]);assert.equal(skillCard.isConnected,true);assert.equal(skillCard.querySelector('.skill-add-trigger').hidden,false);assertShell();

d.querySelector('.instruction-card-actions .phase-add-btn').click();await instructionReadback(()=>instructionRows().length===2);
instructionRows()[1].querySelector('.execution-toggle').click();
await instructionReadback(()=>instructionRows()[1]?.dataset.type==='parallel');
let instructionGroup=d.querySelector('#instructionsTimeline .workflow-parallel-group');assert.ok(instructionGroup);
assert.equal(instructionGroup.querySelectorAll('.timeline-item').length,2);
instructionRows()[1].querySelector('.phase-add-btn').click();await instructionReadback(()=>instructionRows().length===3);
assert.equal(instructionRows()[2].dataset.type,'parallel','in-group add preserves parallel execution');
const instructionThird=instructionRows()[2].dataset.instructionId;
instructionRows()[2].querySelector('.move-up-btn').click();
await instructionReadback(()=>instructionRows()[1]?.dataset.instructionId===instructionThird);
assert.equal(messages.pop(),'Порядок инструкций сохранён');
instructionGroup=d.querySelector('#instructionsTimeline .workflow-parallel-group');assert.equal(instructionGroup.querySelectorAll('.timeline-item').length,3,'reorder keeps the visible shared frame');
instructionRows()[1].querySelector('.phase-delete-btn').click();
assert.equal(d.querySelector('#confirmDialog').hidden,false);d.querySelector('#confirmDialogAccept').click();
await instructionReadback(()=>instructionRows().length===2);
assert.equal(instructionRows()[0].dataset.instructionId,instructionFirst);
assert.equal(instructionRows()[0].querySelector('.move-up-btn').disabled,true);
assert.equal(instructionRows()[1].querySelector('.move-down-btn').disabled,true);
assertShell();await go('/settings');assert.equal(w.scheduleSave,undefined);
// An accepted route commits before the owner data is available. Errors belong
// to the target route and retry does not resurrect data from the outgoing page.
const outgoing=d.querySelector('main');fail=true;
assert.equal(await w.WorkflowApplication.navigate('/workflow/tasks'),true);
assert.equal(outgoing.isConnected,false);assert.equal(w.location.pathname,'/workflow/tasks');
assert.equal(d.querySelector('main').dataset.workflowReadState,'error');
assert.ok(d.querySelector('main [data-page-state="error"]'));
assert.equal(d.querySelector('[data-workflow-route="tasks"]').getAttribute('aria-current'),'page');
const retry=d.querySelector('[data-workflow-retry]');assert.equal(new URL(retry.href).pathname,'/workflow/tasks');
fail=false;retry.click();
for(let attempt=0;attempt<100&&d.querySelector('main').dataset.workflowReadState!=='ready';attempt++)await new Promise(resolve=>setTimeout(resolve,10));
assert.equal(d.querySelector('main').dataset.workflowReadState,'ready');
let release;delay=new Promise(resolve=>{release=resolve;});
const stale=w.WorkflowApplication.navigate('/workflow/settings');await new Promise(resolve=>setImmediate(resolve));
assert.equal(w.location.pathname,'/workflow/settings');
await go('/');release();assert.equal(await stale,false);assert.equal(page().page,'dashboard');
let pendingRelease;delay=new Promise(resolve=>{pendingRelease=resolve;});
const previous=d.querySelector('main');
const pending=w.WorkflowApplication.navigate('/workflow/tasks');await new Promise(resolve=>setImmediate(resolve));
assert.equal(previous.isConnected,false);assert.equal(w.location.pathname,'/workflow/tasks');
assert.equal(d.querySelector('h1').textContent.trim(),'Задачи воркфлоу');
assert.equal(d.querySelector('main').getAttribute('aria-busy'),'true');
assert.equal(d.querySelector('main').dataset.workflowReadState,'loading');
assert.ok(d.querySelector('main [data-page-state="loading"]'));
assert.equal(d.querySelector('[data-workflow-route="tasks"]').getAttribute('aria-current'),'page');
assert.equal(d.querySelector('[data-base-toast-status]').textContent,'');
pendingRelease();assert.equal(await pending,true);assert.equal(d.querySelector('main').dataset.workflowReadState,'ready');
// Once departure is confirmed, the old form/callbacks cannot accept late edits.
await go('/namespaces?profession_id=1');const form=d.querySelector('#namespaceName');
let lateRelease;delay=new Promise(resolve=>{lateRelease=resolve;});
const late=w.WorkflowApplication.navigate('/workflow/settings');await new Promise(resolve=>setImmediate(resolve));
assert.equal(form.isConnected,false);assert.equal(w.submitNamespace,undefined);
form.value='Detached late edit';lateRelease();assert.equal(await late,true);assert.equal(page().page,'settings');
// A successful create schedules its transition after the write is acknowledged.
await go('/namespaces/new');assert.notEqual(d.querySelector('[data-namespace-selector]').selectedOptions[0].textContent,'Поздняя правка');d.querySelector('#namespaceName').value='Изолированная профессия';d.querySelector('#namespaceCliCommand').value='isolated-'+Date.now();
await w.submitNamespace();
for(let attempt=0;attempt<100&&(w.location.pathname.endsWith('/new')||d.querySelector('main').dataset.workflowReadState!=='ready');attempt++)await new Promise(resolve=>setTimeout(resolve,10));
assert.equal(w.location.pathname,'/workflow/namespaces',messages.join('; '));
assert.equal(d.querySelector('#namespaceName').value,'Изолированная профессия');assert.equal(messages.pop(),'Профессия создан');
// Back and forward render their authoritative work areas, preserving the shell.
await go('/settings');await go('/tasks');w.history.back();
for(let attempt=0;attempt<100&&(page().page!=='settings'||d.querySelector('main').dataset.workflowReadState!=='ready');attempt++)await new Promise(resolve=>setTimeout(resolve,10));
assert.equal(page().page,'settings');assert.equal(w.location.pathname,'/workflow/settings');w.history.forward();
for(let attempt=0;attempt<100&&(page().page!=='tasks'||d.querySelector('main').dataset.workflowReadState!=='ready');attempt++)await new Promise(resolve=>setTimeout(resolve,10));
assert.equal(page().page,'tasks');assert.equal(w.location.pathname,'/workflow/tasks');
// A response after admission retirement never resurrects protected content.
let retireRelease;delay=new Promise(resolve=>{retireRelease=resolve;});const retired=w.WorkflowApplication.navigate('/workflow/settings');await new Promise(resolve=>setImmediate(resolve));current=false;d.body.replaceChildren();retireRelease();assert.equal(await retired,false);assert.equal(d.body.childElementCount,0);
assert.equal(native,0);assert.deepEqual(errors,[]);assert.equal(messages.length,0,messages.join('; '));
globalThis.console.log('PASS: all sidebar pages, repeated controllers, create form, phase detail, draft cancellation, no document navigation');w.close();
