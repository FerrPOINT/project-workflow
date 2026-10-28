// Request-independent controller; private view data is supplied by the owner HTML.
(function(){
window.WorkflowPageControllers["namespaces"] = function(page, config){
const fetch=page.fetch,showToast=page.notify,showRequestError=()=>showToast("Не удалось связаться с сервером","error");

{% if can_administer %}
const namespaceStore = config.namespaces;
const namespaceIconPaths = {{ icon_paths|tojson }};
const defaultNamespaceThemeIcon = {{ default_icon|tojson }};
const defaultNamespaceThemeColor = '#5E6AD2';
let selectedNamespaceId = config.selectedId;
let previousNamespaceId = config.previousId;
let namespaceFormMode = selectedNamespaceId == null ? 'create' : 'edit';

function namespaceById(id){ return namespaceStore.find(function(namespace){ return namespace.id === id; }); }
function namespaceContextLabel(namespace){ return namespace.name; }
function namespaceScopedPath(path, id){
  var url = new URL(path, window.location.href);
  if(id != null){ url.searchParams.set('profession_id', String(id)); }
  return window.WorkflowNavigation.withProjectContext(url.toString());
}
function updateNamespaceHeaderLinks(id){
  var createLink = document.getElementById('namespaceCreateLink');
  var editLink = document.getElementById('namespaceEditLink');
  if(createLink){ createLink.href = namespaceScopedPath('' + config.basePath + '/namespaces/new', id); }
  if(editLink){ editLink.href = namespaceScopedPath('' + config.basePath + '/namespaces', id); }
}
function namespaceIconSvg(icon){
  var path = namespaceIconPaths[icon || defaultNamespaceThemeIcon] || namespaceIconPaths[defaultNamespaceThemeIcon];
  return '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="' + path + '"></path></svg>';
}
function applyNamespaceIdentity(name, icon, color){
  document.querySelectorAll('[data-namespace-selector]').forEach(function(selector){
    var option = selector.selectedOptions[0];
    if (!option) return;
    option.textContent = name; option.dataset.icon = icon; option.dataset.color = color || defaultNamespaceThemeColor;
    window.PdlcChoice?.refreshChoice(selector);
  });
}
function updateNamespaceThemePreview(){
  var icon = document.getElementById('namespaceThemeIcon').value || defaultNamespaceThemeIcon;
  var color = document.getElementById('namespaceThemeColor').value || defaultNamespaceThemeColor;
  var command = document.getElementById('namespaceCliCommand').value.trim() || 'engine';
  var name = document.getElementById('namespaceName').value.trim() || (command === 'engine' ? '' : command) || 'Без названия';
  document.getElementById('namespaceThemeControls').style.setProperty('--namespace-color', color);
  window.PdlcChoice?.refreshChoice(document.getElementById('namespaceThemeIcon'));
  if(namespaceFormMode === 'create'){ return; }
  applyNamespaceIdentity(name, icon, color);
}
function renderNamespaceIconChoice(option){
  var visual = document.createElement('span');
  visual.innerHTML = namespaceIconSvg(option.value);
  var svg = visual.querySelector('svg');
  svg.setAttribute('width', '20');
  svg.setAttribute('height', '20');
  svg.style.color = document.getElementById('namespaceThemeColor').value || defaultNamespaceThemeColor;
  var name = document.createElement('span');
  name.className = 'base-visually-hidden';
  name.textContent = option.label;
  visual.appendChild(name);
  return visual;
}
function currentPayload(){
  var payload = {
    name: document.getElementById('namespaceName').value.trim(),
    cli_command: document.getElementById('namespaceCliCommand').value.trim(),
    description: document.getElementById('namespaceDescription').value.trim(),
    theme_icon: document.getElementById('namespaceThemeIcon').value || defaultNamespaceThemeIcon,
    theme_color: document.getElementById('namespaceThemeColor').value || defaultNamespaceThemeColor,
  };
  return payload;
}
function syncNav(){
  document.querySelectorAll('#namespaceNav [data-namespace-id]').forEach(function(node){
    var active = Number(node.dataset.namespaceId) === selectedNamespaceId;
    node.setAttribute('aria-pressed', String(active));
  });
  var picker = document.getElementById('namespaceSelect');
  picker.options[0].textContent = namespaceFormMode === 'create' ? 'Новая профессия' : 'Выберите профессию';
  picker.value = selectedNamespaceId == null ? '' : String(selectedNamespaceId);
  window.PdlcChoice?.refreshChoice(picker);
}
function namespaceIdFromUrl(url){
  var rawId = url.searchParams.get('profession_id');
  if(!rawId || !/^[1-9]\d*$/.test(rawId)){ return null; }
  var id = Number(rawId);
  return namespaceById(id) ? id : null;
}
function syncNamespaceUrl(id, historyMode){
  if(id == null || historyMode === 'none'){ return; }
  var url = new URL(window.location.href);
  if(url.pathname !== '' + config.basePath + '/namespaces' && url.pathname !== '' + config.basePath + '/namespaces/new'){ return; }
  url.pathname = '' + config.basePath + '/namespaces';
  url.searchParams.set('profession_id', id);
  if(url.toString() === window.location.href){ return; }
  var method = historyMode === 'push' ? 'pushState' : 'replaceState';
  window.PdlcPlatformNavigation.syncRoute(url.toString(), method === 'replaceState');
}
function rememberNamespaceSelection(id, historyMode){
  if(id == null){ return; }
  if(!window.PdlcPlatformNavigation.embedded || window.PdlcPlatformNavigation.active) document.cookie=config.cookieName+'='+encodeURIComponent(id)+'; path=/; SameSite=Lax'+(config.cookieSecure?'; Secure':'');
  document.querySelectorAll('[data-namespace-selector]').forEach(function(selector){ selector.value = String(id); window.PdlcChoice?.refreshChoice(selector); });
  refreshNamespaceSelectors();
  updateNamespaceHeaderLinks(id);
  syncNamespaceUrl(id, historyMode || 'replace');
}
function fillNamespaceForm(namespace){
  document.getElementById('namespaceName').value = namespace ? namespace.name : '';
  document.getElementById('namespaceCliCommand').value = namespace ? (namespace.cli_command || '') : '';
  document.getElementById('namespaceDescription').value = namespace ? (namespace.description || '') : '';
  var icon = namespace ? (namespace.theme_icon || defaultNamespaceThemeIcon) : defaultNamespaceThemeIcon;
  document.getElementById('namespaceThemeIcon').value = icon;
  document.getElementById('namespaceThemeColor').value = namespace ? (namespace.theme_color || defaultNamespaceThemeColor) : defaultNamespaceThemeColor;
  updateNamespaceThemePreview();
  window.PdlcPlatformNavigation.saved(document.getElementById('namespaceForm'));
}
function setNamespaceFormMode(mode){
  namespaceFormMode = mode;
  var createMode = mode === 'create';
  var namespace = namespaceById(selectedNamespaceId);
  var protectedByTasks = !createMode && Boolean(namespace && Number(namespace.task_count) > 0);
  var deleteButton = document.getElementById('deleteNamespaceButton');
  document.getElementById('namespaceFormMode').textContent = createMode ? 'Новая профессия' : 'Редактирование профессии';
  document.getElementById('namespaceSubmitButton').textContent = createMode ? 'Создать профессию' : 'Сохранить';
  deleteButton.textContent = 'Удалить';
  deleteButton.style.display = createMode ? 'none' : '';
  deleteButton.disabled = protectedByTasks;
  deleteButton.title = protectedByTasks ? 'Сначала удалите или перенесите задачи' : '';
  document.getElementById('namespaceDeleteHint').hidden = !protectedByTasks;
  document.getElementById('cancelCreateButton').style.display = createMode && namespaceStore.length ? '' : 'none';
}
function startCreateNamespace(){
  if(selectedNamespaceId != null){
    previousNamespaceId = selectedNamespaceId;
  }
  selectedNamespaceId = null;
  setNamespaceFormMode('create');
  fillNamespaceForm(null);
  syncNav();
  document.getElementById('namespaceName').focus();
}
function cancelCreateNamespace(){
  if(namespaceStore.length === 0){
    startCreateNamespace();
    return;
  }
  var fallbackId = previousNamespaceId || namespaceStore[0].id;
  if(!namespaceById(fallbackId)){
    fallbackId = namespaceStore[0].id;
  }
  selectNamespace(fallbackId);
  document.getElementById('namespaceName').focus();
}
function selectNamespace(id, historyMode){
  var namespace = namespaceById(Number(id));
  if(!namespace){ return; }
  selectedNamespaceId = namespace.id;
  previousNamespaceId = namespace.id;
  setNamespaceFormMode('edit');
  fillNamespaceForm(namespace);
  syncNav();
  rememberNamespaceSelection(namespace.id, historyMode || 'push');
}
function restoreNamespaceLocation(){
  var url = new URL(window.location.href);
  if(url.pathname === '' + config.basePath + '/namespaces/new'){
    var contextId = namespaceIdFromUrl(url);
    if(contextId == null && namespaceById(previousNamespaceId)){ contextId = previousNamespaceId; }
    if(contextId == null && namespaceStore[0]){ contextId = namespaceStore[0].id; }
    selectedNamespaceId = null;
    previousNamespaceId = contextId;
    setNamespaceFormMode('create');
    fillNamespaceForm(null);
    syncNav();
    renderNamespaceSelector();
    var contextNamespace = namespaceById(contextId);
    if(contextNamespace){
      applyNamespaceIdentity(
        contextNamespace.name,
        contextNamespace.theme_icon,
        contextNamespace.theme_color
      );
    }
    return;
  }
  var namespaceId = namespaceIdFromUrl(url);
  if(namespaceId == null && namespaceById(previousNamespaceId)){ namespaceId = previousNamespaceId; }
  if(namespaceId == null && namespaceStore[0]){ namespaceId = namespaceStore[0].id; }
  if(namespaceId != null){ selectNamespace(namespaceId, 'none'); }
}
function reloadNamespaces(nextId){
  return fetch('' + config.basePath + '/api/namespaces')
    .then(function(r){return r.json()})
    .then(function(d){
      if(!d.ok){showToast(d.error || 'Ошибка загрузки','error');return;}
      namespaceStore.length = 0;
      d.namespaces.forEach(function(namespace){ namespaceStore.push(namespace); });
      if(namespaceStore.length === 0){
        selectedNamespaceId = null;
        previousNamespaceId = null;
        setNamespaceFormMode('create');
        fillNamespaceForm(null);
        renderNamespaceNav();
        renderNamespacePagePicker();
        renderNamespaceSelector();
        syncNav();
        return;
      }
      selectedNamespaceId = nextId || selectedNamespaceId || previousNamespaceId || namespaceStore[0].id;
      if(!namespaceById(selectedNamespaceId)){ selectedNamespaceId = namespaceStore[0].id; }
      previousNamespaceId = selectedNamespaceId;
      renderNamespaceNav();
      renderNamespacePagePicker();
      renderNamespaceSelector();
      setNamespaceFormMode('edit');
      fillNamespaceForm(namespaceById(selectedNamespaceId));
      syncNav();
      rememberNamespaceSelection(selectedNamespaceId, 'replace');
    })
    .catch(showRequestError);
}
function renderNamespaceNav(){
  document.getElementById('namespaceCrud').classList.toggle('is-empty', namespaceStore.length === 0);
  var nav = document.getElementById('namespaceNav');
  nav.replaceChildren();
  namespaceStore.forEach(function(namespace){
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'namespace-nav-item base-card base-card-content';
    button.dataset.interactive = 'true';
    button.dataset.namespaceId = String(namespace.id);
    button.setAttribute('aria-controls', 'namespaceForm');
    button.setAttribute('aria-pressed', 'false');
    button.style.setProperty('--namespace-color', namespace.theme_color || defaultNamespaceThemeColor);
    button.onclick = function(){ selectNamespace(namespace.id); };

    var mark = document.createElement('span');
    mark.className = 'namespace-mark';
    mark.setAttribute('aria-hidden', 'true');
    mark.innerHTML = namespaceIconSvg(namespace.theme_icon);

    var body = document.createElement('span');
    body.className = 'namespace-card-body';

    var name = document.createElement('span');
    name.className = 'namespace-name base-card-title';
    name.textContent = namespace.name;

    var meta = document.createElement('span');
    meta.className = 'namespace-meta';

    var tasks = document.createElement('span');
    tasks.className = 'base-badge';
    tasks.dataset.tone = 'muted';
    tasks.dataset.appearance = 'inline';
    tasks.textContent = pluralizeRu(namespace.task_count, 'задача', 'задачи', 'задач');

    meta.appendChild(tasks);
    body.appendChild(name);
    body.appendChild(meta);
    button.appendChild(mark);
    button.appendChild(body);
    nav.appendChild(button);
  });
}
function renderNamespacePagePicker(){
  var picker = document.getElementById('namespaceSelect');
  picker.replaceChildren();
  var placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.disabled = true;
  placeholder.textContent = 'Выберите профессию';
  picker.appendChild(placeholder);
  namespaceStore.forEach(function(namespace){
    var option = document.createElement('option');
    option.value = String(namespace.id);
    option.textContent = namespaceContextLabel(namespace);
    picker.appendChild(option);
  });
}
function renderNamespaceSelector(){
  var selectorNamespaceId = selectedNamespaceId == null ? previousNamespaceId : selectedNamespaceId;
  updateNamespaceHeaderLinks(selectorNamespaceId);
  document.querySelectorAll('[data-namespace-selector]').forEach(function(selector){
    selector.replaceChildren();
    namespaceStore.forEach(function(namespace){
      var option = document.createElement('option');
      option.value = String(namespace.id);
      option.textContent = namespaceContextLabel(namespace);
      option.dataset.icon = namespace.theme_icon || defaultNamespaceThemeIcon;
      option.dataset.color = namespace.theme_color || defaultNamespaceThemeColor;
      option.selected = namespace.id === selectorNamespaceId;
      selector.appendChild(option);
    });
  });
  refreshNamespaceSelectors();
}
function saveNamespace(){
  if(selectedNamespaceId == null){ showToast('Сначала выберите профессию','error'); return; }
  var namespaceId = selectedNamespaceId;
  var payload = currentPayload();
  return fetch('' + config.basePath + '/api/namespaces/' + namespaceId,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
    .then(function(r){return r.json()})
    .then(function(d){ if(d.ok){ window.PdlcPlatformNavigation.saved(document.getElementById('namespaceForm')); showToast('Профессия сохранён','success'); return reloadNamespaces(namespaceId); } showToast(d.error || 'Ошибка','error'); })
    .catch(showRequestError);
}
async function deleteNamespace(){
  if(selectedNamespaceId == null){ showToast('Сначала выберите профессию','error'); return; }
  var namespace = namespaceById(selectedNamespaceId);
  if(namespace && Number(namespace.task_count) > 0){ showToast('Сначала удалите или перенесите задачи','error'); return; }
  var title = namespace ? 'Удалить профессию «' + namespace.name + '»?' : 'Удалить профессию?';
  var message = namespace ? '«' + namespace.name + '» будет удалён без возможности восстановления.' : 'Профессия будет удалена без возможности восстановления.';
  if(!await window.PdlcBaseUI.requestConfirmation({eyebrow:'Удаление профессии',title:title,message:message,confirmLabel:'Удалить'})) return;
  var namespaceId = selectedNamespaceId;
  var button = document.getElementById('deleteNamespaceButton');
  button.disabled = true;
  button.textContent = 'Удаление…';
  return fetch('' + config.basePath + '/api/namespaces/' + namespaceId,{method:'DELETE'})
    .then(function(r){return r.json()})
    .then(function(d){ if(d.ok){ showToast('Профессия удалена','success'); return reloadNamespaces(null); } showToast(d.error || 'Ошибка','error'); })
    .catch(showRequestError)
    .finally(function(){ setNamespaceFormMode(namespaceFormMode); });
}
function createNamespace(){
  var payload = currentPayload();
  return fetch('' + config.basePath + '/api/namespaces',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
    .then(function(r){return r.json()})
    .then(function(d){
      if(d.ok){
        showToast('Профессия создан','success');
        window.PdlcPlatformNavigation.saved(document.getElementById('namespaceForm'));
        page.navigateAfterWrite(namespaceScopedPath('' + config.basePath + '/namespaces', d.namespace_id));
      } else {
        showToast(d.error || 'Ошибка','error');
      }
    })
    .catch(showRequestError);
}
function submitNamespace(){
  var nameInput = document.getElementById('namespaceName');
  if(!nameInput.value.trim()){
    showToast('Введите название профессии','error');
    nameInput.focus();
    return;
  }
  var commandInput = document.getElementById('namespaceCliCommand');
  if(!/^[a-z][a-z0-9_-]{1,63}$/.test(commandInput.value.trim())){
    showToast('Проверьте формат CLI-команды','error');
    commandInput.focus();
    return;
  }
  var button = document.getElementById('namespaceSubmitButton');
  if(button.disabled){ return; }
  button.disabled = true;
  button.textContent = namespaceFormMode === 'create' ? 'Создание…' : 'Сохранение…';
  var operation = namespaceFormMode === 'create' ? createNamespace() : saveNamespace();
  return Promise.resolve(operation).finally(function(){ button.disabled = false; setNamespaceFormMode(namespaceFormMode); });
}
document.getElementById('namespaceThemeIcon').addEventListener('change', updateNamespaceThemePreview);
updateNamespaceThemePreview();
renderNamespaceNav();
renderNamespacePagePicker();
renderNamespaceSelector();
if(selectedNamespaceId == null){
  setNamespaceFormMode('create');
  fillNamespaceForm(null);
  document.getElementById('namespaceName').focus();
} else {
  setNamespaceFormMode('edit');
  rememberNamespaceSelection(selectedNamespaceId, 'replace');
}
syncNav();
page.on(window,'popstate', restoreNamespaceLocation);
document.getElementById('namespaceName').addEventListener('input', updateNamespaceThemePreview);
document.getElementById('namespaceCliCommand').addEventListener('input', updateNamespaceThemePreview);
{% else %}
function selectNamespace(id){
  if(!Number.isInteger(id)||id<=0)return;
  const url=new URL(window.location.href);
  url.searchParams.set('profession_id',String(id));
  window.PdlcPlatformNavigation.navigate(window.WorkflowNavigation.withProjectContext(url.toString()));
}
{% endif %}

page.expose({
applyNamespaceIdentity:typeof applyNamespaceIdentity==='function'?applyNamespaceIdentity:undefined,
cancelCreateNamespace:typeof cancelCreateNamespace==='function'?cancelCreateNamespace:undefined,
createNamespace:typeof createNamespace==='function'?createNamespace:undefined,
currentPayload:typeof currentPayload==='function'?currentPayload:undefined,
deleteNamespace:typeof deleteNamespace==='function'?deleteNamespace:undefined,
fillNamespaceForm:typeof fillNamespaceForm==='function'?fillNamespaceForm:undefined,
namespaceById:typeof namespaceById==='function'?namespaceById:undefined,
namespaceContextLabel:typeof namespaceContextLabel==='function'?namespaceContextLabel:undefined,
namespaceIconSvg:typeof namespaceIconSvg==='function'?namespaceIconSvg:undefined,
namespaceIdFromUrl:typeof namespaceIdFromUrl==='function'?namespaceIdFromUrl:undefined,
namespaceScopedPath:typeof namespaceScopedPath==='function'?namespaceScopedPath:undefined,
reloadNamespaces:typeof reloadNamespaces==='function'?reloadNamespaces:undefined,
rememberNamespaceSelection:typeof rememberNamespaceSelection==='function'?rememberNamespaceSelection:undefined,
renderNamespaceIconChoice:typeof renderNamespaceIconChoice==='function'?renderNamespaceIconChoice:undefined,
renderNamespaceNav:typeof renderNamespaceNav==='function'?renderNamespaceNav:undefined,
renderNamespacePagePicker:typeof renderNamespacePagePicker==='function'?renderNamespacePagePicker:undefined,
renderNamespaceSelector:typeof renderNamespaceSelector==='function'?renderNamespaceSelector:undefined,
restoreNamespaceLocation:typeof restoreNamespaceLocation==='function'?restoreNamespaceLocation:undefined,
saveNamespace:typeof saveNamespace==='function'?saveNamespace:undefined,
selectNamespace:typeof selectNamespace==='function'?selectNamespace:undefined,
setNamespaceFormMode:typeof setNamespaceFormMode==='function'?setNamespaceFormMode:undefined,
startCreateNamespace:typeof startCreateNamespace==='function'?startCreateNamespace:undefined,
submitNamespace:typeof submitNamespace==='function'?submitNamespace:undefined,
syncNamespaceUrl:typeof syncNamespaceUrl==='function'?syncNamespaceUrl:undefined,
syncNav:typeof syncNav==='function'?syncNav:undefined,
updateNamespaceHeaderLinks:typeof updateNamespaceHeaderLinks==='function'?updateNamespaceHeaderLinks:undefined,
updateNamespaceThemePreview:typeof updateNamespaceThemePreview==='function'?updateNamespaceThemePreview:undefined,
});
page.handlesHistory=true;
page.busy=()=>false;
};
})();
