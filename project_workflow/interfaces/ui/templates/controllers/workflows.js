// Request-independent controller; private view data is supplied by the owner HTML.
(function(){
window.WorkflowPageControllers["workflows"] = function(page, config){
const fetch=page.fetch,showToast=page.notify,showRequestError=()=>showToast("Не удалось связаться с сервером","error");

{% include "controllers/workflow-navigation.js" %}

function selectMode(modeId){
  const parsed=Number(modeId);
  if(!Number.isInteger(parsed)||parsed<=0){showToast('Не удалось определить режим воркфлоу','error');return;}
  const url=new URL(window.location.href);
  url.pathname='' + config.basePath + '/workflows';
  url.searchParams.set('mode_id',String(parsed));
  void loadWorkflowEditor(url.pathname+url.search,{keepForm:true});
}

function setPhaseView(view,persist=true){
  const timeline=document.getElementById('phasesTimeline');
  if(!timeline||!['compact','timeline'].includes(view))return;
  timeline.classList.toggle('is-compact',view==='compact');
  timeline.querySelectorAll('a.timeline-card').forEach(card=>{
    card.classList.toggle('base-card',view==='timeline');
    card.classList.toggle('base-card-content',view==='timeline');
    card.classList.toggle('base-resource-list-row',view==='compact');
  });
  document.querySelectorAll('#phaseView input[name="phase-view"]').forEach(input=>{
    input.checked=input.value===view;
  });
  if(persist){try{localStorage.setItem('phase-view-mode',view);}catch(_error){}}
}

function jumpToPhase(select){
  const phaseId=select.value;
  select.value='';
  const item=document.getElementById('phase-'+phaseId);
  if(!item)return;
  const headerHeight=document.querySelector('.header')?.getBoundingClientRect().height||0;
  window.scrollTo({top:window.scrollY+item.getBoundingClientRect().top-headerHeight-12,behavior:'auto'});
  item.querySelector('.timeline-card')?.focus({preventScroll:true});
}

page.ready(()=>{
  page.on(document,'change',event=>{
    const input=event.target;
    if(input instanceof HTMLInputElement&&input.name==='phase-view'&&input.checked)setPhaseView(input.value);
  });
  try{
    const savedView=localStorage.getItem('phase-view-mode');
    if(savedView==='compact'||savedView==='timeline')setPhaseView(savedView,false);
  }catch(_error){}
});

{% if can_administer %}
// The toolbar is outside the card link: actions never trigger phase navigation.
page.on(document,'click',event=>{
  const button=event.target.closest?.('.phase-card-actions button');
  if(!button||button.disabled)return;
  if(button.matches('.phase-add-btn'))void addPhaseAfter(button);
  else if(button.matches('.move-up-btn'))void movePhase(button,-1);
  else if(button.matches('.move-down-btn'))void movePhase(button,1);
  else if(button.matches('.execution-toggle'))void togglePhaseType(button);
  else if(button.matches('.phase-delete-btn'))void deletePhase(button);
});
const professionId = config.professionId;
const workflowStore = config.workflows;
let selectedWorkflowId = config.selectedId;
let initialWorkflowId = selectedWorkflowId;
const defaultWorkflowId = config.defaultId;
let previousWorkflowId = selectedWorkflowId;
let workflowFormMode = selectedWorkflowId == null ? 'create' : 'edit';
let workflowEditorVisible = selectedWorkflowId == null;
let workflowWritePending = false;
window.hasUnsavedWorkflowChanges=()=>workflowWritePending||phaseWritePending||workflowNeedsReadback;

function workflowApiUrl(workflowId){
  var url = new URL('' + config.basePath + '/api/workflows' + (workflowId == null ? '' : '/' + workflowId), window.location.origin);
  if(professionId != null){ url.searchParams.set('namespace_id', String(professionId)); }
  return url.pathname + url.search;
}
function workflowById(id){ return workflowStore.find(function(workflow){ return workflow.id === id; }); }
function workflowSelectionUrl(workflowId){
  var url = new URL(window.location.href);
  url.pathname = '' + config.basePath + '/workflows';
  if(Number(url.searchParams.get('workflow_id') || initialWorkflowId) !== workflowId){ url.searchParams.delete('mode_id'); }
  if(workflowId == null){ url.searchParams.delete('workflow_id'); }
  else { url.searchParams.set('workflow_id', String(workflowId)); }
  return url.pathname + url.search + url.hash;
}
function syncWorkflowUrl(workflowId, mode){
  var nextUrl = workflowSelectionUrl(workflowId);
  var currentUrl = window.location.pathname + window.location.search + window.location.hash;
  if(nextUrl === currentUrl)return;
  window.PdlcPlatformNavigation.syncRoute(nextUrl, mode === 'replace', {workflowId:workflowId});
}
function workflowIdFromUrl(){
  var raw = new URL(window.location.href).searchParams.get('workflow_id');
  if(raw == null){
    return workflowById(defaultWorkflowId) ? defaultWorkflowId : (workflowStore[0] ? workflowStore[0].id : null);
  }
  var parsed = Number(raw);
  return Number.isInteger(parsed) && parsed > 0 && workflowById(parsed) ? parsed : null;
}
function currentWorkflowPayload(){
  return {
    name: document.getElementById('workflowName').value.trim(),
    description: document.getElementById('workflowDescription').value.trim(),
  };
}
function syncWorkflowNav(){
  document.querySelectorAll('#workflowNav [data-workflow-id]').forEach(function(node){
    var active = Number(node.dataset.workflowId) === selectedWorkflowId;
    node.classList.toggle('active', active);
    node.setAttribute('aria-pressed', String(active));
  });
  var picker = document.getElementById('workflowSelect');
  picker.options[0].textContent = workflowFormMode === 'create' ? 'Новый воркфлоу' : 'Выберите воркфлоу';
  picker.value = selectedWorkflowId == null ? '' : String(selectedWorkflowId);
  window.PdlcChoice?.refreshChoice(picker);
}
function fillWorkflowForm(workflow){
  document.getElementById('workflowName').value = workflow ? workflow.name : '';
  document.getElementById('workflowDescription').value = workflow ? (workflow.description || '') : '';
  document.getElementById('workflowSummaryName').textContent = workflow ? workflow.name : '';
  var description = document.getElementById('workflowSummaryDescription');
  description.textContent = workflow ? (workflow.description || '') : '';
  description.hidden = !description.textContent;
}
function setWorkflowEditorVisible(visible){
  workflowEditorVisible = visible;
  var creating = workflowFormMode === 'create';
  document.getElementById('workflowForm').hidden = !visible && !creating;
  document.getElementById('workflowSummary').hidden = visible || creating || selectedWorkflowId == null;
  document.querySelectorAll('[data-workflow-edit]').forEach(function(button){
    button.disabled = workflowWritePending || creating || selectedWorkflowId == null;
    button.setAttribute('aria-expanded', String(visible && !creating));
  });
}
function startEditWorkflow(){
  if(workflowWritePending||phaseWritePending||workflowNeedsReadback||workflowReadController)return;
  if(selectedWorkflowId == null)return;
  if(!workflowEditorVisible){ fillWorkflowForm(workflowById(selectedWorkflowId)); }
  setWorkflowEditorVisible(true);
  document.getElementById('workflowName').focus();
}
function cancelWorkflowForm(){
  if(workflowWritePending||phaseWritePending||workflowNeedsReadback||workflowReadController)return;
  workflowEditorVisible = false;
  if(workflowFormMode === 'create'){ cancelCreateWorkflow(); }
  else{ fillWorkflowForm(workflowById(selectedWorkflowId)); setWorkflowFormMode('edit'); }
  window.PdlcPlatformNavigation.saved(document.getElementById('workflowForm'));
  var trigger = Array.from(document.querySelectorAll('[data-workflow-edit]')).find(function(button){ return button.getClientRects().length; });
  if(trigger){ trigger.focus(); }
}
function setWorkflowFormMode(mode){
  workflowFormMode = mode;
  var createMode = mode === 'create';
  document.getElementById('workflowPhases').hidden = createMode;
  var workflow = workflowById(selectedWorkflowId);
  var protectedDefault = !createMode && Boolean(workflow && workflow.is_default);
  var deleteButton = document.getElementById('deleteWorkflowButton');
  document.getElementById('workflowFormMode').textContent = createMode ? 'Новый воркфлоу' : 'Редактирование воркфлоу';
  document.getElementById('workflowSubmitButton').textContent = createMode ? 'Создать воркфлоу' : 'Сохранить';
  deleteButton.textContent = 'Удалить';
  deleteButton.style.display = createMode ? 'none' : '';
  deleteButton.disabled = workflowWritePending || protectedDefault;
  document.getElementById('workflowDeleteHint').hidden = !protectedDefault;
  document.getElementById('cancelCreateWorkflowButton').style.display = !createMode || workflowStore.length ? '' : 'none';
  setWorkflowEditorVisible(workflowEditorVisible);
}
function startCreateWorkflow(){
  if(workflowWritePending||phaseWritePending||workflowNeedsReadback||workflowReadController)return;
  if(selectedWorkflowId != null){
    previousWorkflowId = selectedWorkflowId;
  }
  selectedWorkflowId = null;
  fillWorkflowForm(null);
  setWorkflowFormMode('create');
  syncWorkflowNav();
  document.getElementById('workflowName').focus();
}
function cancelCreateWorkflow(){
  if(workflowWritePending||phaseWritePending||workflowNeedsReadback||workflowReadController)return;
  if(workflowStore.length === 0){
    startCreateWorkflow();
    return;
  }
  var fallbackId = previousWorkflowId || workflowStore[0].id;
  if(!workflowById(fallbackId)){
    fallbackId = workflowStore[0].id;
  }
  selectWorkflow(fallbackId);
}
function workflowFormDirty(){
  const form=document.getElementById('workflowForm');
  if(!form||form.hidden)return false;
  const original=workflowFormMode==='create'?null:workflowById(selectedWorkflowId);
  return document.getElementById('workflowName').value!==(original?.name||'')||document.getElementById('workflowDescription').value!==(original?.description||'');
}
function selectWorkflow(id,options={}){
  if(workflowWritePending||!workflowById(id))return;
  if(id===initialWorkflowId&&!workflowReadController){
    if(workflowFormMode==='edit')return;
    selectedWorkflowId=id;fillWorkflowForm(workflowById(id));setWorkflowFormMode('edit');syncWorkflowNav();return;
  }
  return loadWorkflowEditor(workflowSelectionUrl(id),{history:options.replaceUrl?'replace':'push'});
}
function renderWorkflowNav(){
  var nav = document.getElementById('workflowNav');
  var picker = document.getElementById('workflowSelect');
  document.getElementById('workflowCrud').classList.toggle('is-empty', workflowStore.length === 0);
  nav.replaceChildren();
  picker.replaceChildren();
  var placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.disabled = true;
  placeholder.textContent = 'Выберите воркфлоу';
  picker.appendChild(placeholder);
  if(workflowStore.length === 0){
    nav.appendChild(document.getElementById('workflowNavEmptyTemplate').content.cloneNode(true));
  }
  workflowStore.forEach(function(workflow){
    var option = document.createElement('option');
    option.value = String(workflow.id);
    option.textContent = workflow.name;
    picker.appendChild(option);
    var button = document.getElementById('workflowNavItemTemplate').content.firstElementChild.cloneNode(true);
    button.dataset.workflowId = String(workflow.id);
    button.onclick = function(){ selectWorkflow(workflow.id); };
    button.querySelector('[data-workflow-name]').textContent = workflow.name;
    button.querySelector('[data-workflow-namespace-count]').textContent = pluralizeRu(workflow.namespace_count, 'профессия', 'профессии', 'профессий');
    button.querySelector('[data-workflow-phase-count]').textContent = pluralizeRu(workflow.phase_count, 'фаза', 'фазы', 'фаз');
    nav.appendChild(button);
  });
}
function reloadWorkflows(nextId){
  return refreshAfterWorkflowWrite(workflowSelectionUrl(nextId),{history:'replace'});
}
function saveWorkflow(){
  if(selectedWorkflowId == null){ showToast('Воркфлоу не выбран','error'); return; }
  var payload = currentWorkflowPayload();
  return fetch(workflowApiUrl(selectedWorkflowId),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
    .then(function(r){return r.json()})
    .then(function(d){ if(d.ok){ window.PdlcPlatformNavigation.saved(document.getElementById('workflowForm')); showToast('Воркфлоу сохранён','success'); return reloadWorkflows(selectedWorkflowId).then(function(loaded){ if(loaded){setWorkflowEditorVisible(false);} }); } showToast(d.error || 'Ошибка','error'); })
    .catch(showRequestError);
}
function createWorkflow(){
  var payload = currentWorkflowPayload();
  return fetch(workflowApiUrl(null),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
    .then(function(r){return r.json()})
    .then(function(d){
      if(d.ok){
        showToast('Воркфлоу создан','success');
        window.PdlcPlatformNavigation.saved(document.getElementById('workflowForm'));
        return refreshAfterWorkflowWrite(workflowSelectionUrl(d.workflow_id));
      } else {
        showToast(d.error || 'Ошибка','error');
      }
    })
    .catch(showRequestError);
}
async function deleteWorkflow(){
  if(workflowWritePending||phaseWritePending||workflowNeedsReadback||workflowReadController)return;
  if(selectedWorkflowId == null){ showToast('Воркфлоу не выбран','error'); return; }
  var workflow = workflowById(selectedWorkflowId);
  var title = workflow ? 'Удалить воркфлоу «' + workflow.name + '»?' : 'Удалить воркфлоу?';
  var message = workflow
    ? '«' + workflow.name + '» будет удалён. Фазы этого воркфлоу тоже будут удалены.'
    : 'Воркфлоу будет удалён.';
  if(!await window.PdlcBaseUI.requestConfirmation({eyebrow:'Удаление воркфлоу',title:title,message:message,confirmLabel:'Удалить'})) return;
  if(workflowWritePending||phaseWritePending||workflowNeedsReadback||workflowReadController)return;
  setWorkflowWritePending(true);
  var workflowId = selectedWorkflowId;
  var button = document.getElementById('deleteWorkflowButton');
  button.disabled = true;
  button.textContent = 'Удаление…';
  return fetch(workflowApiUrl(workflowId),{method:'DELETE'})
    .then(function(r){return r.json()})
    .then(function(d){
      if(d.ok){
        showToast('Воркфлоу удалён','success');
        return refreshAfterWorkflowWrite(workflowSelectionUrl(null),{history:'replace'});
      } else {
        showToast(d.error || 'Ошибка','error');
      }
    })
    .catch(showRequestError)
    .finally(function(){ setWorkflowWritePending(false); });
}
function setWorkflowWritePending(pending){
  workflowWritePending = pending;
  var form = document.getElementById('workflowForm');
  form.setAttribute('aria-busy', String(pending));
  form.querySelectorAll('input,textarea,select,button').forEach(function(control){ control.disabled = pending; if (control.matches('select[data-base-choice]')) window.PdlcChoice?.refreshChoice(control); });
  document.querySelectorAll('#workflowSelect, #workflowNav button, #newWorkflowButton').forEach(function(control){ control.disabled = pending; if (control.matches('select[data-base-choice]')) window.PdlcChoice?.refreshChoice(control); });
  setWorkflowFormMode(workflowFormMode);
}
function submitWorkflow(){
  if(workflowWritePending||phaseWritePending)return;
  var nameInput = document.getElementById('workflowName');
  if(!nameInput.value.trim()){
    showToast('Введите название воркфлоу','error');
    nameInput.focus();
    return;
  }
  var button = document.getElementById('workflowSubmitButton');
  if(button.disabled)return;
  setWorkflowWritePending(true);
  button.textContent = workflowFormMode === 'create' ? 'Создание…' : 'Сохранение…';
  var operation = workflowFormMode === 'create' ? createWorkflow() : saveWorkflow();
  return Promise.resolve(operation).finally(function(){ setWorkflowWritePending(false); });
}
renderWorkflowNav();
if(selectedWorkflowId == null){
  fillWorkflowForm(null);
  setWorkflowFormMode('create');
} else {
  setWorkflowFormMode('edit');
}
syncWorkflowNav();


function getPhaseTimelineItems(){return Array.from(document.querySelectorAll('#phasesTimeline .timeline-item'));}

async function addPhaseAfter(button){
  if(phaseWritePending||workflowWritePending||workflowNeedsReadback||workflowReadController)return;
  const workflowId=document.getElementById('phasesTimeline')?.dataset.workflowId;
  const modeId=document.getElementById('phasesTimeline')?.dataset.modeId;
  const item=button.closest('.timeline-item');
  const currentOrder=parseInt(item?.dataset.phaseOrder??button.dataset.afterOrder??'0',10);
  if(!workflowId||!modeId||currentOrder<0){showToast('Не удалось определить позицию фазы','error');return;}
  if(phaseWritePending||workflowWritePending||workflowNeedsReadback||workflowReadController)return;
  setPhaseWritePending(true);
  try{
    const payload={workflow_id:parseInt(workflowId,10),mode_id:parseInt(modeId,10),phase_order:currentOrder+1};
    // A card insertion inside an existing parallel group must not split its
    // explicit edges or change the group's confirmed rollback target.
    if(item?.dataset.executionType==='parallel'){
      payload.execution_type='parallel';payload.parallel_with_phase_id=Number(item.dataset.phaseId);
      payload.rollback_target_phase_id=item.dataset.rollbackTargetPhaseId?Number(item.dataset.rollbackTargetPhaseId):null;
    }
    const resp=await fetch('' + config.basePath + '/api/phases',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data=await resp.json().catch(()=>({}));
    if(!resp.ok||!data.ok){if(resp.status>=500)requireWorkflowReadback();showToast(data.error||'Не удалось добавить фазу','error');return;}
    await refreshWorkflowPhases();
  }catch(_error){requireWorkflowReadback();showRequestError();
  }finally{setPhaseWritePending(false);}
}

async function deletePhase(button){
  if(phaseWritePending||workflowWritePending||workflowNeedsReadback||workflowReadController)return;
  const item=button.closest('.timeline-item');
  const items=getPhaseTimelineItems();
  if(!item)return;
  if(items.length<=1){showToast('Нельзя удалить единственную фазу воркфлоу','error');return;}
  const phaseName=item.querySelector('.timeline-name')?.textContent.trim()||'эту фазу';
  if(!await window.PdlcBaseUI.requestConfirmation({eyebrow:'Удаление фазы',title:'Удалить фазу «'+phaseName+'»?',message:'Фаза «'+phaseName+'» и её настройки будут удалены.',confirmLabel:'Удалить'}))return;
  if(phaseWritePending||workflowWritePending||workflowNeedsReadback||workflowReadController)return;
  setPhaseWritePending(true);
  try{
    const resp=await fetch('' + config.basePath + '/api/phases/'+item.dataset.phaseId,{method:'DELETE'});
    const data=await resp.json().catch(()=>({}));
    if(!resp.ok||!data.ok){if(resp.status>=500)requireWorkflowReadback();showToast(data.error||'Не удалось удалить фазу','error');return;}
    await refreshWorkflowPhases();
  }catch(_error){requireWorkflowReadback();showRequestError();
  }finally{setPhaseWritePending(false);}
}

async function togglePhaseType(button){
  if(phaseWritePending||workflowWritePending||workflowNeedsReadback||workflowReadController)return;
  const item=button.closest('.timeline-item');
  if(!item)return;
  const nextType=(item.dataset.executionType||'sync')==='sync'?'parallel':'sync';
  if(phaseWritePending||workflowWritePending||workflowNeedsReadback||workflowReadController)return;
  setPhaseWritePending(true);
  try{
    const resp=await fetch('' + config.basePath + '/api/phases/'+item.dataset.phaseId,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({execution_type:nextType})});
    const data=await resp.json().catch(()=>({}));
    if(!resp.ok||!data.ok){if(resp.status>=500)requireWorkflowReadback();showToast(data.error||'Не удалось сменить режим','error');return;}
    await refreshWorkflowPhases();
  }catch(_error){requireWorkflowReadback();showRequestError();
  }finally{setPhaseWritePending(false);}
}

async function movePhase(button,direction){
  if(phaseWritePending||workflowWritePending||workflowNeedsReadback||workflowReadController)return;
  const item=button.closest('.timeline-item');
  const items=getPhaseTimelineItems();
  const currentIndex=items.indexOf(item);
  const targetIndex=currentIndex+direction;
  if(!item||currentIndex<0||targetIndex<0||targetIndex>=items.length)return;
  const reordered=[...items];
  const moved=reordered.splice(currentIndex,1)[0];
  reordered.splice(targetIndex,0,moved);
  if(phaseWritePending||workflowWritePending||workflowNeedsReadback||workflowReadController)return;
  setPhaseWritePending(true);
  try{
    const orders=reordered.map((phase,index)=>({phase_id:Number(phase.dataset.phaseId),phase_order:index+1}));
    const resp=await fetch('' + config.basePath + '/api/phases/order',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({orders})});
    if(!resp.ok){if(resp.status>=500)requireWorkflowReadback();showToast('Не удалось сохранить порядок фаз','error');return;}
    await refreshWorkflowPhases();
  }catch(_error){requireWorkflowReadback();showRequestError();
  }finally{setPhaseWritePending(false);}
}


{% else %}
function selectWorkflow(id){
  if(!Number.isInteger(id)||id<=0)return;
  const url=new URL(window.location.href);
  url.searchParams.set('workflow_id',String(id));
  url.searchParams.delete('mode_id');
  return loadWorkflowEditor(url.pathname+url.search);
}

{% endif %}
page.ready(()=>initializeWorkflowPhases());

page.expose({
addPhaseAfter:typeof addPhaseAfter==='function'?addPhaseAfter:undefined,
cancelCreateWorkflow:typeof cancelCreateWorkflow==='function'?cancelCreateWorkflow:undefined,
cancelWorkflowForm:typeof cancelWorkflowForm==='function'?cancelWorkflowForm:undefined,
createWorkflow:typeof createWorkflow==='function'?createWorkflow:undefined,
currentWorkflowPayload:typeof currentWorkflowPayload==='function'?currentWorkflowPayload:undefined,
deletePhase:typeof deletePhase==='function'?deletePhase:undefined,
deleteWorkflow:typeof deleteWorkflow==='function'?deleteWorkflow:undefined,
fillWorkflowForm:typeof fillWorkflowForm==='function'?fillWorkflowForm:undefined,
getPhaseTimelineItems:typeof getPhaseTimelineItems==='function'?getPhaseTimelineItems:undefined,
initializeWorkflowPhases:typeof initializeWorkflowPhases==='function'?initializeWorkflowPhases:undefined,
jumpToPhase:typeof jumpToPhase==='function'?jumpToPhase:undefined,
loadWorkflowEditor:typeof loadWorkflowEditor==='function'?loadWorkflowEditor:undefined,
movePhase:typeof movePhase==='function'?movePhase:undefined,
refreshAfterWorkflowWrite:typeof refreshAfterWorkflowWrite==='function'?refreshAfterWorkflowWrite:undefined,
refreshWorkflowPhases:typeof refreshWorkflowPhases==='function'?refreshWorkflowPhases:undefined,
reloadWorkflows:typeof reloadWorkflows==='function'?reloadWorkflows:undefined,
renderWorkflowNav:typeof renderWorkflowNav==='function'?renderWorkflowNav:undefined,
requireWorkflowReadback:typeof requireWorkflowReadback==='function'?requireWorkflowReadback:undefined,
retireWorkflowEditor:typeof retireWorkflowEditor==='function'?retireWorkflowEditor:undefined,
retryWorkflowReadback:typeof retryWorkflowReadback==='function'?retryWorkflowReadback:undefined,
saveWorkflow:typeof saveWorkflow==='function'?saveWorkflow:undefined,
selectMode:typeof selectMode==='function'?selectMode:undefined,
selectWorkflow:typeof selectWorkflow==='function'?selectWorkflow:undefined,
setPhaseView:typeof setPhaseView==='function'?setPhaseView:undefined,
setPhaseWritePending:typeof setPhaseWritePending==='function'?setPhaseWritePending:undefined,
setWorkflowEditorVisible:typeof setWorkflowEditorVisible==='function'?setWorkflowEditorVisible:undefined,
setWorkflowFormMode:typeof setWorkflowFormMode==='function'?setWorkflowFormMode:undefined,
setWorkflowWritePending:typeof setWorkflowWritePending==='function'?setWorkflowWritePending:undefined,
startCreateWorkflow:typeof startCreateWorkflow==='function'?startCreateWorkflow:undefined,
startEditWorkflow:typeof startEditWorkflow==='function'?startEditWorkflow:undefined,
submitWorkflow:typeof submitWorkflow==='function'?submitWorkflow:undefined,
syncWorkflowNav:typeof syncWorkflowNav==='function'?syncWorkflowNav:undefined,
syncWorkflowUrl:typeof syncWorkflowUrl==='function'?syncWorkflowUrl:undefined,
togglePhaseType:typeof togglePhaseType==='function'?togglePhaseType:undefined,
workflowApiUrl:typeof workflowApiUrl==='function'?workflowApiUrl:undefined,
workflowById:typeof workflowById==='function'?workflowById:undefined,
workflowFormDirty:typeof workflowFormDirty==='function'?workflowFormDirty:undefined,
workflowIdFromUrl:typeof workflowIdFromUrl==='function'?workflowIdFromUrl:undefined,
workflowSelectionUrl:typeof workflowSelectionUrl==='function'?workflowSelectionUrl:undefined,
});
page.handlesHistory=true;
page.busy=()=>typeof workflowWritePending!=='undefined'&&(workflowWritePending||phaseWritePending);
};
})();
