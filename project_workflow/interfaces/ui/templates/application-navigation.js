// One persistent shell; page-local code owns only its current work area.
window.WorkflowPageControllers = Object.create(null);
window.WorkflowApplication = (() => {
  const basePath={{ ui_base_path()|tojson }};
  let controller,active,pendingFactory,metadata,epoch=0,request=null,swapping=false;
  let committed=location.pathname+location.search+location.hash;
  let position=history.state?.workflowAppPosition??0;
  let originalNavigate,originalSync;
  function route(url){
    const local=url.pathname.slice(basePath.length).replace(/\/$/,'')||'/';
    if(local==='/')return {page:'dashboard',title:'Дашборд',layout:'wide'};
    if(/^\/namespaces(?:\/new)?$/.test(local))return {page:'namespace',title:'Профессии',layout:'wide'};
    if(local==='/workflows'||local==='/phases')return {page:'workflows',title:'Воркфлоу',layout:'wide'};
    if(local==='/instructions')return {page:'phases',title:'Инструкции фазы',layout:'reading'};
    if(/^\/phase\/[^/]+$/.test(local))return {page:'phases',title:'Детали фазы',layout:'detail-with-aside'};
    if(local==='/tasks')return {page:'tasks',title:'Задачи воркфлоу',layout:'wide'};
    if(/^\/task\/[^/]+$/.test(local))return {page:'tasks',title:'Задача воркфлоу',layout:'detail-with-aside'};
    if(local==='/settings')return {page:'settings',title:'Команды CLI',layout:'wide'};
    return {page:'',title:'Workflow',layout:'wide'};
  }
  function selectRoute(next){
    document.querySelectorAll('[data-workflow-route]').forEach(link=>{
      const selected=link.dataset.workflowRoute===next.page||(link.dataset.workflowRoute==='workflows'&&next.page==='phases');
      link.classList.toggle('active',selected);if(selected)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
    });
    const title=document.querySelector('title');title.dataset.baseBrandTitle=next.title;document.title=next.title;
  }
  function readState(next,kind,url){
    const main=document.querySelector('template[data-workflow-read-template="'+kind+'-'+next.layout+'"]').content.firstElementChild.cloneNode(true);
    main.dataset.workflowReadState=kind;main.setAttribute('aria-busy',String(kind==='loading'));
    main.querySelector('[data-workflow-route-heading]').textContent=next.title;
    main.querySelector('[data-workflow-page]').textContent=JSON.stringify({schema_version:1,page:next.page,title:next.title,read_state:kind});
    const retry=main.querySelector('a[href]');if(retry){retry.href=path(url);retry.dataset.workflowRetry='';}
    return main;
  }
  const path=url=>url.pathname+url.search+url.hash;
  const eligible=url=>url.origin===location.origin&&(basePath===''||url.pathname===basePath||url.pathname.startsWith(basePath+'/'))&&!new RegExp('^'+basePath+'/(api|internal|base-assets|ui-assets|login|logout|sso)(/|$)').test(url.pathname);
  const notify=(message,type='error')=>window.PdlcBaseUI.notify(message,{type});
  const state=()=>JSON.parse(document.querySelector('[data-workflow-page]')?.textContent||'null');
  function controls(root){
    window.PdlcBaseUI.initMenus(root);
    root.querySelectorAll('select[data-base-choice]').forEach(select=>window.PdlcChoice.initChoice(select,select.hasAttribute('data-namespace-selector')?{renderOption:renderNamespaceChoice}:select.id==='namespaceThemeIcon'?{appearance:'icons',renderOption:renderNamespaceIconChoice}:{}));
    root.querySelectorAll('textarea[data-base-autosize]').forEach(control=>window.PdlcTextarea.initTextareaAutosize(control));
    root.querySelectorAll('[data-base-copy-target]').forEach(control=>window.PdlcClipboard.initCopyButton(control));
  }
  function destroyControls(root){
    window.PdlcBaseUI.destroyMenus(root);
    root.querySelectorAll('select[data-base-choice]').forEach(control=>window.PdlcChoice.destroyChoice(control));
    root.querySelectorAll('textarea[data-base-autosize]').forEach(control=>window.PdlcTextarea.destroyTextareaAutosize(control));
    root.querySelectorAll('[data-base-copy-target]').forEach(control=>window.PdlcClipboard.destroyCopyButton(control));
  }
  function mount(factory){
    if(!controller||swapping){pendingFactory=factory;return;}
    const abort=new AbortController(),cleanups=[],exports=new Map(),ready=[];
    const scope={alive:true,writes:0,busy:()=>false,handlesHistory:false,
      on(target,type,callback,options={}){
        if(type==='pagehide'&&target===window)cleanups.push(()=>callback({persisted:false}));
        target.addEventListener(type,callback,{...(typeof options==='boolean'?{capture:options}:options),signal:abort.signal});
      },
      ready(callback){ready.push(callback);},cleanup(callback){cleanups.push(callback);},
      navigateAfterWrite(url){setTimeout(()=>{if(scope.alive)void navigate(url);},0);},
      notify(message,type){if(scope.alive)notify(message,type);},
      fetch(url,options={}){return window.fetch(url,{...options,signal:options.signal?AbortSignal.any([abort.signal,options.signal]):abort.signal});},
      expose(functions){for(const [name,fn] of Object.entries(functions)){
        if(typeof fn!=='function')continue;
        const callback=(...args)=>{
          if(!scope.alive)return;
          const result=fn(...args);
          if(!result?.then||!/^(save|persist|submit|create|add|remove|delete|move|toggle|update|reconcile)/.test(name))return result;
          scope.writes++;return Promise.resolve(result).finally(()=>{scope.writes--;});
        };
        window[name]=callback;exports.set(name,callback);
      }},
      dispose(){
        if(!scope.alive)return;
        scope.alive=false;
        scope.discard?.();abort.abort();cleanups.forEach(callback=>callback());
        for(const [name,fn] of exports)if(window[name]===fn)delete window[name];
        for(const name of ['hasUnsavedWorkflowChanges','discardWorkflowDraft'])if(window[name]===scope.hooks[name])delete window[name];
      },hooks:{},
    };
    active=scope;
    try{
      factory(scope);
      for(const name of ['hasUnsavedWorkflowChanges','discardWorkflowDraft'])scope.hooks[name]=window[name];
      scope.discard=scope.hooks.discardWorkflowDraft;
      ready.forEach(callback=>callback());
      controls(document.querySelector('main.main'));controller.trackForms(document.querySelector('main.main'));window.WorkflowNavigation.preserveProjectContext();
    }catch(error){console.error('Workflow page initialization failed',error);notify('Не удалось запустить раздел. Выберите другой раздел или обновите страницу.');}
  }
  function sync(url,replace=false,value=null){
    if(!replace)position++;
    committed=path(new URL(url,location.href));
    return originalSync(url,replace,{...(value||history.state),workflowAppPosition:position});
  }
  function rememberScroll(){originalSync(committed,true,{...history.state,workflowAppPosition:position,workflowScroll:{x:scrollX,y:scrollY}});}
  function updateShell(next){
    const context=document.querySelector('[data-base-responsive-context]');
    const template=document.createElement('template');template.innerHTML=next.context_html;
    const identity=root=>JSON.stringify([...root.querySelectorAll('select[data-namespace-selector]')].map(select=>[...select.options].map(option=>[option.value,option.textContent,option.selected,option.dataset.icon,option.dataset.color])));
    // An abandoned profession preview may have changed the persistent selector.
    if(context&&(metadata.context_html!==next.context_html||identity(context)!==identity(template.content))){
      destroyControls(context);context.replaceChildren(template.content);controls(context);refreshNamespaceSelectors();
    }
    selectRoute(next);
    metadata=next;window.WorkflowNavigation.preserveProjectContext();
  }
  async function navigate(value,options={}){
    const url=new URL(value,location.href);
    if(!eligible(url)){originalNavigate(url.href,options);return false;}
    const revision=++epoch;request?.abort();request=null;
    if(active?.writes||active?.busy()){notify('Дождитесь завершения сохранения.');return false;}
    if(!controller.isCurrent())return false;
    if(!await controller.canLeave()||revision!==epoch)return false;
    window.PdlcBaseUI.closeNavigation?.();
    const old=document.querySelector('main.main'),target=route(url);
    const restoreScroll=options.scroll||(options.refresh?{x:scrollX,y:scrollY}:null);
    if(options.history!=='none')rememberScroll();
    active?.dispose();active=null;destroyControls(old);
    if(options.history!=='none')sync(path(url),!!options.replace);
    else{committed=path(url);position=options.position??position;originalSync(committed,true,{...history.state,workflowAppPosition:position});}
    selectRoute(target);
    const loading=readState(target,'loading',url);old.replaceWith(loading);
    document.querySelector('[data-workflow-page-style]').textContent='';
    controller.trackForms(loading);window.WorkflowNavigation.preserveProjectContext();
    window.scrollTo(0,0);loading.focus({preventScroll:true});
    const abort=new AbortController();request=abort;
    try{
      const response=await fetch(path(url),{signal:abort.signal,cache:'no-store',headers:{'X-Workflow-View':'page-v1','Accept':'text/html'}});
      const final=new URL(response.url||url.href);
      if(revision!==epoch||!controller.isCurrent()||!loading.isConnected)return false;
      if(response.headers.get('X-Workflow-View')!=='page-v1'){
        if(response.status===401||response.status===403||response.redirected&&!eligible(final)){originalNavigate(url.href,{replace:true});return true;}
        throw Error('Не удалось открыть раздел');
      }
      const html=await response.text();const parsed=new DOMParser().parseFromString(html,'text/html');
      if(revision!==epoch||!controller.isCurrent()||!loading.isConnected)return false;
      const next=JSON.parse(parsed.querySelector('[data-workflow-page]')?.textContent||'null');
      if(!next||next.schema_version!==1||typeof next.context_html!=='string'||!parsed.querySelector('main.main')||!eligible(final))throw Error('Некорректный ответ раздела');
      if(next.access_revision!==metadata.access_revision||next.access_enforced!==metadata.access_enforced||next.can_administer!==metadata.can_administer){controller.retire();return true;}
      if(JSON.stringify(next.controller_assets)!==JSON.stringify(metadata.controller_assets)){originalNavigate(url.href,{replace:true});return true;}
      const scripts=[...parsed.querySelector('main.main').querySelectorAll('script')];
      if(scripts.filter(script=>script.hasAttribute('data-workflow-controller')).length!==1||scripts.some(script=>script.type!=='application/json'&&(!script.hasAttribute('data-workflow-controller')||script.src)))throw Error('Некорректный код раздела');
      const style=parsed.querySelector('[data-workflow-page-style]');style?.remove();
      if(path(final)!==committed)sync(path(final),true);
      document.querySelector('[data-workflow-page-style]').textContent=style?.textContent||'';
      const incoming=parsed.querySelector('main.main');incoming.dataset.workflowReadState=response.ok?'ready':'error';incoming.setAttribute('aria-busy','false');
      updateShell(next);
      // htmx inserts the new main before removing the old one. Mount after settle.
      const focusWorkArea=loading.contains(document.activeElement)||document.activeElement===document.body;
      swapping=true;
      try{
        await new Promise(resolve=>htmx.swap(loading,parsed.body.innerHTML,{swapStyle:'outerHTML',settleDelay:0,swapDelay:0},{select:'main.main',afterSettleCallback:()=>{
          swapping=false;const factory=pendingFactory;pendingFactory=null;if(factory)mount(factory);resolve();
        }}));
      }finally{swapping=false;pendingFactory=null;}
      if(revision!==epoch||!controller.isCurrent())return false;
      if(restoreScroll)window.scrollTo(restoreScroll.x,restoreScroll.y);
      else if(final.hash)document.getElementById(decodeURIComponent(final.hash.slice(1)))?.scrollIntoView();
      if(focusWorkArea)document.querySelector('main.main')?.focus({preventScroll:true});
      return true;
    }catch(error){
      if(revision!==epoch||!controller.isCurrent()||!loading.isConnected)return false;
      if(error.name==='AbortError')return false;
      const failed=readState(target,'error',url),focused=loading.contains(document.activeElement);
      loading.replaceWith(failed);controller.trackForms(failed);if(focused)failed.focus({preventScroll:true});
      return true;
    }finally{if(revision===epoch)request=null;}
  }
  function start(value){
    const initialize=()=>{
      controller=value;if(!controller.isCurrent())return;
      document.querySelector('main.main').dataset.workflowReadState='ready';
      metadata=state();originalNavigate=window.PdlcPlatformNavigation.navigate;originalSync=window.PdlcPlatformNavigation.syncRoute;
      htmx.config.historyEnabled=false;htmx.config.historyCacheSize=0;htmx.config.selfRequestsOnly=true;htmx.config.allowEval=false;
      window.PdlcPlatformNavigation.syncRoute=sync;
      window.PdlcPlatformNavigation.navigate=(url,options={})=>eligible(new URL(url,location.href))?navigate(url,options):originalNavigate(url,options);
      window.PdlcPlatformNavigation.reload=()=>{const owner=active,url=committed;return setTimeout(()=>{if(active===owner)void navigate(url,{replace:true,refresh:true});},0);};
      originalSync(committed,true,{...history.state,workflowAppPosition:position});
      if(pendingFactory){const factory=pendingFactory;pendingFactory=null;mount(factory);}
      document.addEventListener('click',event=>{
        const link=event.target.closest?.('a[href]');
        if(!link||event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey||link.hasAttribute('download')||link.target&&link.target!=='_self'||link.closest('[data-workflow-local-navigation]'))return;
        const url=new URL(link.href);if(!eligible(url))return;
        if(url.pathname===location.pathname&&url.search===location.search&&url.hash)return;
        event.preventDefault();event.stopImmediatePropagation();void navigate(url.href,{replace:link.hasAttribute('data-workflow-retry')});
      },true);
      window.addEventListener('popstate',event=>{
        const target=path(new URL(location.href));
        if(target===committed)return;
        const old=new URL(committed,location.origin),next=new URL(location.href);
        const sameContext=['profession_id','namespace_id','registry_instance_id','project_scope'].every(key=>old.searchParams.getAll(key).join(',')===next.searchParams.getAll(key).join(','));
        if(active?.handlesHistory&&old.pathname===next.pathname&&sameContext){position=event.state?.workflowAppPosition??position;committed=target;return;}
        event.stopImmediatePropagation();const targetPosition=event.state?.workflowAppPosition;
        const operation=navigate(target,{history:'none',position:targetPosition,scroll:event.state?.workflowScroll});const revision=epoch;
        void operation.then(ok=>{
          if(ok||revision!==epoch)return;
          if(Number.isInteger(targetPosition)&&targetPosition!==position)history.go(position-targetPosition);
          else originalSync(committed,true,{...history.state,workflowAppPosition:position});
        });
      },true);
      document.addEventListener('submit',event=>{
        const form=event.target;if(!(form instanceof HTMLFormElement)||form.hasAttribute('onsubmit')||form.method.toLowerCase()!=='get')return;
        const url=new URL(form.action||location.href);if(!eligible(url))return;
        event.preventDefault();url.search=new URLSearchParams(new FormData(form));void navigate(url.href);
      });
    };
    if(document.readyState==='complete')initialize();else document.addEventListener('DOMContentLoaded',initialize,{once:true});
  }
  return {mount,start,navigate};
})();
