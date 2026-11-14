// Edit a complete publication snapshot. No raw phase mutation or per-field POST.
const backgroundCatalogForms=new WeakMap();
const catalogStable=value=>JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);
function backgroundCatalogState(){
  const editor=document.getElementById('backgroundCatalogEditor');
  if(!editor)return null;
  if(!backgroundCatalogForms.has(editor)){
    const source=JSON.parse(editor.querySelector('#backgroundCatalogState').textContent);
    const state={editor,active:source.active,draft:source.draft,busy:false,unknown:null,key:null};
    state.storage=`workflow.catalog-publication.v1:${config.basePath}:${source.operator}:${source.active.workflow_id}`;
    try{const raw=sessionStorage.getItem(state.storage);if(raw){state.unknown={kind:'publication',...JSON.parse(raw)};}}
    catch{state.unknown={kind:'invalid'};}
    backgroundCatalogForms.set(editor,state);
  }
  return backgroundCatalogForms.get(editor);
}
function backgroundCatalogModes(state){
  const modes=structuredClone((state.draft||state.active).modes);
  for(const field of state.editor.querySelectorAll('[data-catalog-path]')){
    const path=JSON.parse(field.dataset.catalogPath);let parent=modes;
    for(const key of path.slice(0,-1))parent=parent[key];
    parent[path.at(-1)]=field.value;
  }
  return modes;
}
function backgroundCatalogDirty(){
  const state=backgroundCatalogState();
  return Boolean(state&&(state.busy||state.unknown||catalogStable(backgroundCatalogModes(state))!==catalogStable((state.draft||state.active).modes)));
}
function backgroundCatalogControls(state,message){
  const dirty=catalogStable(backgroundCatalogModes(state))!==catalogStable((state.draft||state.active).modes);
  state.editor.setAttribute('aria-busy',String(state.busy));
  state.editor.querySelectorAll('[data-catalog-path]').forEach(field=>{field.disabled=state.busy||Boolean(state.unknown);});
  state.editor.querySelector('[data-catalog-action="save"]').disabled=state.busy||Boolean(state.unknown);
  state.editor.querySelector('[data-catalog-action="publish"]').disabled=state.busy||Boolean(state.unknown)||!state.draft||dirty;
  const readback=state.editor.querySelector('[data-catalog-action="readback"]');
  readback.hidden=!state.unknown;readback.disabled=state.busy;
  if(message)state.editor.querySelector('[data-catalog-status]').textContent=message;
}
async function catalogRequest(state,path,options={}){
  const response=await fetch(`${config.basePath}/api/workflows/${state.active.workflow_id}/catalog${path}`,{cache:'no-store',redirect:'error',...options});
  const value=await response.json();
  if(!response.ok||value.ok!==true){const error=Error(value.error||'Не удалось сохранить редакцию');error.status=response.status;throw error;}
  return value.revision;
}
function catalogRevision(state,revision){
  if(!revision||revision.workflow_id!==state.active.workflow_id||!Number.isSafeInteger(revision.catalog_version)||revision.catalog_version<1||!/^[a-f0-9]{64}$/.test(revision.content_sha256)||!Array.isArray(revision.modes))throw Error('Получена неподтверждённая редакция');
  return revision;
}
function catalogPost(body){return {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};}
async function backgroundCatalogAction(action){
  const state=backgroundCatalogState();if(!state||state.busy)return;
  if(action!=='readback'&&state.unknown)return;
  state.busy=true;backgroundCatalogControls(state);
  try{
    if(action==='save'){
      const body={expected_version:state.active.catalog_version,expected_sha256:state.active.content_sha256,modes:backgroundCatalogModes(state)};
      state.unknown={kind:'draft',body};
      const saved=catalogRevision(state,await catalogRequest(state,'/drafts',catalogPost(body)));
      if(catalogStable(saved.modes)!==catalogStable(body.modes))throw Error('Сохранён другой черновик');
      state.draft=saved;state.key=null;state.unknown=null;
      window.PdlcPlatformNavigation.saved(state.editor.querySelector('form'));
      backgroundCatalogControls(state,`Черновик ${saved.catalog_version} сохранён. Для следующих запусков его нужно опубликовать.`);
    }else if(action==='publish'){
      if(!state.draft||catalogStable(backgroundCatalogModes(state))!==catalogStable(state.draft.modes))throw Error('Сначала сохраните изменения');
      state.key=state.key||crypto.randomUUID();
      const command={expected_version:state.active.catalog_version,expected_sha256:state.active.content_sha256,draft_sha256:state.draft.content_sha256,operation_key:state.key};
      state.unknown={kind:'publication',version:state.draft.catalog_version,command};
      // Only receipt selectors survive reload; private instruction text stays in the form.
      sessionStorage.setItem(state.storage,JSON.stringify({version:state.draft.catalog_version,command}));
      const published=catalogRevision(state,await catalogRequest(state,`/drafts/${state.draft.catalog_version}/publication`,catalogPost(command)));
      if(published.content_sha256!==command.draft_sha256||published.published!==true)throw Error('Публикация не подтверждена');
      sessionStorage.removeItem(state.storage);state.unknown=null;state.active=published;state.draft=null;
      backgroundCatalogControls(state,`Редакция ${published.catalog_version} опубликована. Обновите страницу, чтобы увидеть новые фазы.`);
      await refreshWorkflowPhases();
      showToast(`Редакция ${published.catalog_version} опубликована`,'success');
    }else if(action==='readback'){
      const original=state.unknown;
      if(original?.kind==='publication'){
        const command=original.command;
        if(!command||typeof command.operation_key!=='string'||!/^[a-f0-9-]{36}$/.test(command.operation_key)||!/^[a-f0-9]{64}$/.test(command.draft_sha256))throw Error('Некорректные сведения исходной операции');
        try{
          const published=catalogRevision(state,await catalogRequest(state,`/publications/operations/${encodeURIComponent(command.operation_key)}`));
          if(published.published!==true||published.catalog_version!==original.version||published.content_sha256!==command.draft_sha256)throw Error('Квитанция относится к другой редакции');
          sessionStorage.removeItem(state.storage);state.unknown=null;
          backgroundCatalogControls(state,'Исходная публикация подтверждена. Обновляется действующая редакция.');
          await refreshWorkflowPhases();
          showToast(`Публикация редакции ${published.catalog_version} подтверждена`,'success');
        }catch(error){
          if(error.status!==404)throw error;
          sessionStorage.removeItem(state.storage);state.unknown=null;
          backgroundCatalogControls(state,'Исходная публикация не зарегистрирована. Проверьте черновик перед повторной публикацией.');
        }
      }else if(original?.kind==='draft'){
        const pending=await catalogRequest(state,'/drafts');
        // A read under the same catalog lock precedes an exact idempotent save.
        const saved=catalogRevision(state,pending&&catalogStable(pending.modes)===catalogStable(original.body.modes)?pending:await catalogRequest(state,'/drafts',catalogPost(original.body)));
        if(catalogStable(saved.modes)!==catalogStable(original.body.modes))throw Error('Исходный черновик не подтверждён');
        state.draft=saved;state.unknown=null;
        backgroundCatalogControls(state,`Сохранение черновика ${saved.catalog_version} подтверждено.`);
      }else throw Error('Сведения операции повреждены. Проверьте историю публикаций перед обновлением страницы.');
    }
  }catch(error){
    if(action!=='readback'&&error.status&&error.status<500){
      // A closed refusal proves no new write. A transport/5xx failure remains unknown.
      if(state.unknown?.kind==='publication')sessionStorage.removeItem(state.storage);
      state.unknown=null;
    }
    backgroundCatalogControls(state,error.message||'Ответ потерян. Сверьте результат исходной операции.');
  }finally{state.busy=false;backgroundCatalogControls(state);}
}
page.on(document,'submit',event=>{if(event.target.matches('[data-catalog-form]'))event.preventDefault();});
page.on(document,'input',event=>{const state=backgroundCatalogState();if(state?.editor.contains(event.target)){state.key=null;backgroundCatalogControls(state);}});
page.on(document,'click',event=>{const action=event.target.closest?.('[data-catalog-action]');if(action&&!action.disabled)void backgroundCatalogAction(action.dataset.catalogAction);});
page.ready(()=>{const state=backgroundCatalogState();if(state)backgroundCatalogControls(state,state.unknown?'Есть публикация с неизвестным результатом. Сверьте исходную операцию.':null);});
