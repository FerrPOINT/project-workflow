// Only the editor is replaced. The shell, admission clock and draft guard stay mounted.
let workflowReadController = null;
let phaseWritePending = false;
let workflowNeedsReadback = false;
let workflowReadbackRequest = null;
let workflowHistoryPosition = history.state?.workflowPosition ?? 0;
let workflowReadRevision = 0;
let workflowCommittedUrl = location.pathname + location.search + location.hash;
const workflowInitialRole = {{ can_administer|tojson }};
function initializeWorkflowPhases(root=document){
  root.querySelectorAll('select[data-base-choice]').forEach(control=>window.PdlcChoice?.initChoice(control));
  root.querySelectorAll('textarea[data-base-autosize]').forEach(control=>window.PdlcTextarea?.initTextareaAutosize(control));
  const items=Array.from(document.querySelectorAll('#phasesTimeline .timeline-item'));
  items.forEach((item,index)=>{
    const up=item.querySelector('.move-up-btn'),down=item.querySelector('.move-down-btn');
    if(up)up.disabled=index===0;
    if(down)down.disabled=index===items.length-1;
  });
  try{const view=localStorage.getItem('phase-view-mode');if(view)setPhaseView(view,false);}catch{}
  window.WorkflowNavigation?.preserveProjectContext();
}
function retireWorkflowEditor(){
  // Never keep protected content visible after an explicit owner denial.
  const editor=document.getElementById('workflowCrud');
  editor.replaceChildren();
  editor.textContent='Доступ изменился. Откройте раздел заново после проверки полномочий.';
  document.querySelectorAll('.workflow-header-action').forEach(button=>{button.disabled=true;});
}
async function loadWorkflowEditor(value,options={}){
  const url=new URL(value,location.href);
  if(url.origin!==location.origin||url.pathname!=='{{ ui_base_path() }}/workflows')return false;
  if(workflowNeedsReadback&&!options.afterWrite){showToast('Сначала обновите состояние сохранённого изменения','error');return false;}
  if(phaseWritePending&&!options.afterWrite)return false;
{% if can_administer %}
  if(workflowWritePending&&!options.afterWrite)return false;
{% endif %}
  const revision=++workflowReadRevision;
  workflowReadController?.abort();
  workflowReadController=null;
  document.getElementById('workflowCrud')?.setAttribute('aria-busy','false');
{% if can_administer %}
  if(!options.keepForm&&!options.afterWrite&&workflowFormDirty()){
    const allowed=await window.PdlcBaseUI.requestConfirmation({title:'Сменить воркфлоу?',message:'Есть несохранённые изменения.',confirmLabel:'Продолжить'});
    if(revision!==workflowReadRevision||!allowed)return false;
  }
{% endif %}
  const controller=new AbortController();workflowReadController=controller;
  const editor=document.getElementById('workflowCrud');
  if(!editor)return false;
  editor.setAttribute('aria-busy','true');
  // A user may edit while a read is in flight. Do not overwrite those later edits.
  const form=document.getElementById('workflowForm');
  const formVersion=form ? JSON.stringify(Array.from(form.querySelectorAll('input,textarea')).map(field=>field.value)) : null;
  try{
    const response=await fetch(url.pathname+url.search,{signal:controller.signal,cache:'no-store',redirect:'error',headers:{'X-Workflow-View':'editor-v1'}});
    if(revision!==workflowReadRevision||!editor.isConnected)return false;
    if(response.status===401||response.status===403){retireWorkflowEditor();throw Error('Нет доступа к выбранному воркфлоу');}
    if(!response.ok||response.headers.get('X-Workflow-View')!=='editor-v1')throw Error('Не удалось обновить воркфлоу');
    const parsed=new DOMParser().parseFromString(await response.text(),'text/html');
    if(revision!==workflowReadRevision||!editor.isConnected)return false;
    const next=parsed.getElementById('workflowCrud');
    const state=JSON.parse(next?.querySelector('#workflowEditorState')?.textContent||'null');
    if(!next||!state||!Array.isArray(state.workflows)||state.can_administer!==workflowInitialRole){retireWorkflowEditor();throw Error('Полномочия изменились');}
    if(next.querySelector('script:not([type="application/json"])'))throw Error('Некорректный ответ редактора');
    if(!options.keepForm&&formVersion!==null&&formVersion!==JSON.stringify(Array.from(form.querySelectorAll('input,textarea')).map(field=>field.value)))throw Error('Форма изменилась во время загрузки. Повторите выбор.');
    const imported=document.importNode(next,true);
    const keepForm=options.keepForm&&state.selected_workflow_id===Number(document.getElementById('phasesTimeline')?.dataset.workflowId);
    const target=keepForm?document.getElementById('workflowPhases'):editor;
    const restorePhaseFocus=keepForm&&target.contains(document.activeElement);
    const focusedPhase=document.activeElement.closest?.('.timeline-item')?.id;
    target.querySelectorAll('select[data-base-choice]').forEach(control=>window.PdlcChoice?.destroyChoice(control));
    target.querySelectorAll('textarea[data-base-autosize]').forEach(control=>window.PdlcTextarea?.destroyTextareaAutosize(control));
    if(keepForm){
      target.replaceWith(imported.querySelector('#workflowPhases'));
      document.getElementById('workflowEditorState').textContent=JSON.stringify(state);
    }else{
      window.PdlcPlatformNavigation.saved(form);
      editor.replaceWith(imported);
    }
{% if can_administer %}
    workflowStore.splice(0,workflowStore.length,...state.workflows);
    selectedWorkflowId=state.selected_workflow_id;initialWorkflowId=selectedWorkflowId;
    previousWorkflowId=selectedWorkflowId;
    if(!keepForm){workflowEditorVisible=false;setWorkflowFormMode(selectedWorkflowId==null?'create':'edit');}
    renderWorkflowNav();syncWorkflowNav();
    if(!keepForm)window.PdlcPlatformNavigation.saved(document.getElementById('workflowForm'));
{% endif %}
    initializeWorkflowPhases(keepForm?document.getElementById('workflowPhases'):document.getElementById('workflowCrud'));
    if(options.history!=='none'){
      if(options.history!=='replace')workflowHistoryPosition++;
      window.PdlcPlatformNavigation.syncRoute(url.pathname+url.search+url.hash,options.history==='replace',{...history.state,workflowPosition:workflowHistoryPosition});
    }
    workflowCommittedUrl=url.pathname+url.search+url.hash;
    if(restorePhaseFocus){const phase=focusedPhase&&document.getElementById(focusedPhase);const focus=phase?.querySelector('.timeline-card')||document.getElementById('workflowPhasesTitle');focus?.setAttribute('tabindex','-1');focus?.focus({preventScroll:true});}
    if(!keepForm){const heading=document.getElementById('workflowPhasesTitle')||document.getElementById('workflowFormMode');heading?.setAttribute('tabindex','-1');heading?.focus({preventScroll:true});}
    return true;
  }catch(error){
    if(revision===workflowReadRevision&&error.name!=='AbortError')showToast(error.message||'Не удалось обновить воркфлоу','error');
    return false;
  }finally{
    if(revision===workflowReadRevision){document.getElementById('workflowCrud')?.setAttribute('aria-busy','false');workflowReadController=null;}
  }
}
function setPhaseWritePending(pending){
  phaseWritePending=pending;
  const phases=document.getElementById('workflowPhases');
  phases?.setAttribute('aria-busy',String(pending));
  phases?.querySelectorAll('button').forEach(button=>{button.disabled=pending;});
  if(!pending)initializeWorkflowPhases(phases||document);
}
function requireWorkflowReadback(){
  workflowNeedsReadback=true;
  const notice=document.getElementById('workflowReadbackError');if(notice)notice.hidden=false;
}
async function refreshAfterWorkflowWrite(url,options={}){
  workflowReadbackRequest={url,options};
  const ok=await loadWorkflowEditor(url,{...options,afterWrite:true});
  workflowNeedsReadback=!ok;
  const notice=document.getElementById('workflowReadbackError');if(notice)notice.hidden=ok;
  if(ok)workflowReadbackRequest=null;
  return ok;
}
function refreshWorkflowPhases(){return refreshAfterWorkflowWrite(workflowCommittedUrl,{keepForm:true,history:'none'});}
async function retryWorkflowReadback(){
  if(phaseWritePending)return;
  setPhaseWritePending(true);
  try{
    if(workflowReadbackRequest)await refreshAfterWorkflowWrite(workflowReadbackRequest.url,workflowReadbackRequest.options);
    else await refreshWorkflowPhases();
  }finally{setPhaseWritePending(false);}
}
document.addEventListener('click',event=>{
  const link=event.target.closest?.('.mode-tab[href]');
  if(!link||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  event.preventDefault();event.stopImmediatePropagation();
  void loadWorkflowEditor(link.href,{keepForm:true});
},true);
document.addEventListener('DOMContentLoaded',()=>{
  window.PdlcPlatformNavigation.syncRoute(workflowCommittedUrl,true,{...history.state,workflowPosition:workflowHistoryPosition});
});
window.addEventListener('popstate',event=>{
  const target=location.pathname+location.search+location.hash;
  if(target===workflowCommittedUrl)return;
  const position=event.state?.workflowPosition;
  const state=JSON.parse(document.getElementById('workflowEditorState').textContent);
  const workflowId=Number(new URL(target,location.href).searchParams.get('workflow_id')||state.workflows[0]?.id);
  const operation=loadWorkflowEditor(target,{history:'none',keepForm:workflowId===state.selected_workflow_id});
  const revision=workflowReadRevision;
  void operation.then(ok=>{
    if(revision!==workflowReadRevision)return;
    if(ok){workflowHistoryPosition=position??workflowHistoryPosition;return;}
    // Undo the traversal rather than overwriting an older history entry.
    if(Number.isInteger(position)&&position!==workflowHistoryPosition)history.go(workflowHistoryPosition-position);
    else window.PdlcPlatformNavigation.syncRoute(workflowCommittedUrl,true,{...history.state,workflowPosition:workflowHistoryPosition});
  });
});
window.addEventListener('pagehide',()=>{workflowReadRevision++;workflowReadController?.abort();});
