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
 w.PdlcTextarea={initTextareaAutosize(){},destroyTextareaAutosize(){}};
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
let fail=false,delay=null;const realFetch=w.fetch;w.fetch=async(value,options)=>{if(options?.headers?.['X-Workflow-View']==='page-v1'){if(fail)return new Response('Unavailable',{status:503});if(delay){const pending=delay;delay=null;await pending;}}return realFetch(value,options);};
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
assert.equal(typeof w.scheduleSave,'function');await go('/settings');assert.equal(w.scheduleSave,undefined);
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
