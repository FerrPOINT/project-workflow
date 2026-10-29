// Request-independent controller; private view data is supplied by the owner HTML.
(function(){
window.WorkflowPageControllers["phase_detail"] = function(page, config){
const fetch=page.fetch,showToast=page.notify,showRequestError=()=>showToast("Не удалось связаться с сервером","error");

{% if can_administer %}
const phaseId = config.phaseId;
let phaseDraft = null;
let phaseSignature = '';
let confirmedPhase = null;
let unknownPhaseSave = null;
let mutationPending = 0;
let instructionOrderSaving = false;
let mutationNeedsReadback = false;
let mutationRequiresReload = false;
let savingStopped = false;
const instructionDrafts = new Map();
const unknownInstructionSaves = new Map();
window.hasUnsavedWorkflowChanges = () => mutationPending > 0 || instructionOrderSaving || mutationNeedsReadback || [...document.querySelectorAll('.skill-candidate')].some(input => input.value.trim()) || !!phaseDraft?.dirty || [...instructionDrafts.values()].some(draft => draft.dirty);

function instructionDraft(input) {
  const id = input.closest('.timeline-card').dataset.instructionId;
  if (!instructionDrafts.has(id)) instructionDrafts.set(id, window.PdlcPlatformNavigation.createDraftTracker());
  return instructionDrafts.get(id);
}

function currentPhaseSignature() {
  const fields = [...document.querySelectorAll('.wiki-header [data-field], #checks-list [data-field], #evidence-list [data-field]')].map(input => input.value);
  return JSON.stringify(fields);
}
function notePhaseEdit() {
  const current = currentPhaseSignature();
  if (phaseDraft && current !== phaseSignature) { savingStopped = false; phaseDraft.edit(); phaseSignature = current; }
}
function updatePhaseSaveStatus() {
  const button = document.getElementById('phaseSaveReadback');
  if (button) button.hidden = !unknownPhaseSave && !unknownInstructionSaves.size && !mutationNeedsReadback && !mutationRequiresReload;
  const save = document.getElementById('phaseSaveEditor');
  if (save) { save.hidden = ![phaseDraft, ...instructionDrafts.values()].some(draft => draft?.dirty && !draft.pending && !draft.uncertain); save.disabled = mutationPending > 0 || !!phaseDraft?.pending || [...instructionDrafts.values()].some(draft => draft.pending); save.setAttribute('aria-busy', String(save.disabled)); }
  const recovery = document.getElementById('phaseSaveRecovery');
  if (recovery) recovery.hidden = !!button?.hidden && !!save?.hidden;
  updateInstructionControls();
}
const selectedNamespaceId = config.professionId;
const phaseSectionIds = ['phase-overview', 'phase-instructions', 'phase-checks', 'phase-evidence'];
let phaseSectionNavigationLock = null;

function setActivePhaseSection(sectionId) {
  if (!phaseSectionIds.includes(sectionId)) return;
  document.querySelectorAll('.phase-outline .base-section-navigation-item').forEach((link) => {
    if (link.hash.slice(1) === sectionId) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  });
  const select = document.getElementById('phaseSectionSelect');
  if (select && select.value !== sectionId) { select.value = sectionId; window.PdlcChoice?.refreshChoice(select); }
}

function syncPhaseSectionUrl(sectionId, historyMode) {
  if (historyMode === 'none') return;
  const url = new URL(window.location.href);
  url.hash = sectionId;
  const nextUrl = url.pathname + url.search + url.hash;
  const currentUrl = window.location.pathname + window.location.search + window.location.hash;
  if (nextUrl === currentUrl) return;
  const method = historyMode === 'replace' ? 'replaceState' : 'pushState';
  window.PdlcPlatformNavigation.syncRoute(nextUrl, method === 'replaceState');
}

function jumpToPhaseSection(sectionId, historyMode = 'push') {
  if (!phaseSectionIds.includes(sectionId)) return;
  const section = document.getElementById(sectionId);
  if (!section) return;
  phaseSectionNavigationLock = sectionId;
  section.scrollIntoView({behavior: 'auto', block: 'start'});
  setActivePhaseSection(sectionId);
  syncPhaseSectionUrl(sectionId, historyMode);
}

function releasePhaseSectionNavigationLock() {
  phaseSectionNavigationLock = null;
}

function restorePhaseSectionFromLocation() {
  const requestedSection = window.location.hash.slice(1);
  const sectionId = phaseSectionIds.includes(requestedSection)
    ? requestedSection
    : 'phase-overview';
  jumpToPhaseSection(sectionId, 'none');
}

function initializePhaseOutline() {
  document.querySelectorAll('.phase-outline .base-section-navigation-item').forEach((link) => {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      jumpToPhaseSection(link.hash.slice(1));
    });
  });
  document.getElementById('phaseSectionSelect')?.addEventListener('change', (event) => {
    jumpToPhaseSection(event.target.value);
  });
  const sections = phaseSectionIds.map((id) => document.getElementById(id)).filter(Boolean);
  const observer = new IntersectionObserver(() => {
    if (phaseSectionNavigationLock) {
      setActivePhaseSection(phaseSectionNavigationLock);
      return;
    }
    const anchor = 96;
    const atPageEnd = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2;
    const activeSection = atPageEnd
      ? sections[sections.length - 1]
      : sections.reduce((current, section) => (
          section.getBoundingClientRect().top <= anchor ? section : current
        ), sections[0]);
    if (activeSection) setActivePhaseSection(activeSection.id);
  }, {rootMargin: '-84px 0px -58% 0px', threshold: [0, .1, .5]});
  page.cleanup(()=>observer.disconnect());
  sections.forEach((section) => observer.observe(section));
  const requestedSection = window.location.hash.slice(1);
  if (phaseSectionIds.includes(requestedSection)) {
    const frame=requestAnimationFrame(() => jumpToPhaseSection(requestedSection, 'replace'));
    page.cleanup(()=>cancelAnimationFrame(frame));
  }
  page.on(window,'popstate', restorePhaseSectionFromLocation);
  page.on(window,'wheel', releasePhaseSectionNavigationLock, {passive: true});
  page.on(window,'touchstart', releasePhaseSectionNavigationLock, {passive: true});
  page.on(window,'pointerdown', releasePhaseSectionNavigationLock, {passive: true});
  page.on(window,'keydown', releasePhaseSectionNavigationLock);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function normalizeSkillNames(raw = []) {
  const seen = new Set();
  const normalized = [];
  for (const item of raw || []) {
    const name = String(item || '').trim();
    if (!name || seen.has(name)) continue;
    seen.add(name);
    normalized.push(name);
  }
  return normalized;
}

function phaseApiUrl(path) {
  const url = new URL(path, window.location.origin);
  if (selectedNamespaceId !== null) {
    url.searchParams.set('namespace_id', String(selectedNamespaceId));
  }
  return url.pathname + url.search;
}

/* ---------- Instructions list (like phases) ---------- */
function getInstructionItems() {
  return Array.from(document.querySelectorAll('#instructionsTimeline .timeline-item'));
}

function renderInstructionTimeline(items) {
  const timeline = document.getElementById('instructionsTimeline');
  if (!timeline) return;
  if (items.length === 0) {
    timeline.replaceChildren(document.getElementById('instructions-empty-template').content.cloneNode(true));
    return;
  }
  timeline.innerHTML = '';
  let idx = 0;
  while (idx < items.length) {
    const group = [items[idx]];
    idx++;
    while (idx < items.length && (items[idx].dataset.type || 'sync') === 'parallel') {
      group.push(items[idx]);
      idx++;
    }
    const isParallelGroup = group.length > 1;
    const block = isParallelGroup
      ? document.getElementById('instruction-parallel-group-template').content.firstElementChild.cloneNode(true)
      : document.createElement('div');
    if (!isParallelGroup) block.className = 'timeline-block';
    group.forEach(item => block.appendChild(item));
    timeline.appendChild(block);
  }
  timeline.querySelectorAll('textarea[data-base-autosize]').forEach(field => window.PdlcTextarea?.initTextareaAutosize(field));
}


function updateInstructionControls() {
  const items = getInstructionItems();
  items.forEach((item, idx) => {
    const up = item.querySelector('.move-up-btn');
    const down = item.querySelector('.move-down-btn');
    const pending = instructionOrderSaving || mutationPending > 0;
    item.querySelectorAll('.instruction-card-actions button').forEach(button => { button.disabled = pending; });
    if (up) up.disabled = pending || idx === 0;
    if (down) down.disabled = pending || idx === items.length - 1;
  });
}

async function persistInstructionOrder() {
  const ids = getInstructionItems().map((item) => parseInt(item.dataset.instructionId, 10));
  try {
    const result = await requestPhaseDetail(phaseApiUrl(`${config.basePath}/api/phases/${phaseId}/instructions/reorder`), {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({instruction_ids: ids}),
    });
    if (!result || !result.resp.ok || !result.data.ok) {
      showToast('Не удалось сохранить порядок инструкций', 'error');
      return false;
    }
    showToast('Порядок инструкций сохранён', 'success');
    return true;
  } catch (_error) {
    showToast('Не удалось сохранить порядок инструкций', 'error');
    return false;
  }
}

async function moveInstruction(button, direction) {
  if (instructionOrderSaving) return;
  const item = button.closest('.timeline-item');
  if (!item) return;
  const items = getInstructionItems();
  const currentIndex = items.indexOf(item);
  const targetIndex = currentIndex + direction;
  if (currentIndex < 0 || targetIndex < 0 || targetIndex >= items.length) return;
  const reordered = [...items];
  const [moved] = reordered.splice(currentIndex, 1);
  reordered.splice(targetIndex, 0, moved);
  instructionOrderSaving = true;
  try {
    renderInstructionTimeline(reordered);
    updateInstructionControls();
    if (!await persistInstructionOrder()) {
      renderInstructionTimeline(items);
    }
  } finally {
    instructionOrderSaving = false;
    updateInstructionControls();
  }
}

async function requestPhaseDetail(url, options, trackedDraft = false) {
  if (mutationNeedsReadback || mutationRequiresReload) { showToast('Сначала проверьте результат изменения и обновите страницу', 'error'); return null; }
  mutationPending++;
  updatePhaseSaveStatus();
  try {
    const resp = await fetch(url, options);
    const data = await resp.json().catch(() => ({}));
    if (!trackedDraft && (resp.status >= 500 || (resp.ok && typeof data.ok !== 'boolean'))) { mutationNeedsReadback = true; mutationRequiresReload = true; }
    return {resp, data};
  } catch (_error) {
    if (!trackedDraft) { mutationNeedsReadback = true; mutationRequiresReload = true; }
    showRequestError();
    return null;
  } finally {
    mutationPending--;
    updatePhaseSaveStatus();
    window.PdlcPlatformNavigation.refreshDrafts?.();
  }
}

async function addInstructionAfter(button) {
  const item = button.closest('.timeline-item');
  if (!item) return;
  const stepNum = getInstructionItems().indexOf(item) + 2;
  button.disabled = true;
  try {
    const result = await requestPhaseDetail(phaseApiUrl('' + config.basePath + '/api/instructions'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({phase_id: phaseId, description: 'Новая инструкция', step_num: stepNum, execution_type: item.closest('.workflow-parallel-group') ? 'parallel' : 'sync'}),
    });
    if (!result) return;
    const {resp, data} = result;
    if (!resp.ok || !data.ok) {
      showToast(data.error || 'Не удалось добавить инструкцию', 'error');
      return;
    }
    window.PdlcPlatformNavigation.reload();
  } finally {
    button.disabled = false;
  }
}

async function addInstructionLast() {
  const timeline = document.getElementById('instructionsTimeline');
  const items = getInstructionItems();
  const stepNum = items.length > 0 ? items.length + 1 : 1;
  const btn = timeline?.nextElementSibling;
  if (btn) btn.disabled = true;
  try {
    const result = await requestPhaseDetail(phaseApiUrl('' + config.basePath + '/api/instructions'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({phase_id: phaseId, description: 'Новая инструкция', step_num: stepNum}),
    });
    if (!result) return;
    const {resp, data} = result;
    if (!resp.ok || !data.ok) {
      showToast(data.error || 'Не удалось добавить инструкцию', 'error');
      return;
    }
    window.PdlcPlatformNavigation.reload();
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function deleteInstruction(button) {
  const item = button.closest('.timeline-item');
  if (!item) return;
  if (!await window.PdlcBaseUI.requestConfirmation({eyebrow:'Удаление инструкции',title:'Удалить инструкцию?',message:'Инструкция будет удалена без возможности восстановления.',confirmLabel:'Удалить'})) return;
  button.disabled = true;
  try {
    const id = item.dataset.instructionId;
    const result = await requestPhaseDetail(phaseApiUrl('' + config.basePath + '/api/instructions/' + id), {method: 'DELETE'});
    if (!result) return;
    const {resp, data} = result;
    if (!resp.ok || !data.ok) {
      showToast(data.error || 'Не удалось удалить инструкцию', 'error');
      return;
    }
    window.PdlcPlatformNavigation.reload();
  } finally {
    button.disabled = false;
  }
}

async function toggleInstructionType(badge) {
  const card = badge.closest('.timeline-card');
  const id = card.dataset.instructionId;
  const isSync = (card.dataset.type || 'sync') === 'sync';
  const nextType = isSync ? 'parallel' : 'sync';
  badge.disabled = true;
  try {
    const result = await requestPhaseDetail(phaseApiUrl('' + config.basePath + '/api/instructions/' + id), {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({execution_type: nextType}),
    });
    if (!result) return;
    const {resp} = result;
    if (!resp.ok) {
      showToast('Не удалось сменить режим', 'error');
      return;
    }
    window.PdlcPlatformNavigation.reload();
  } finally {
    badge.disabled = false;
  }
}

async function saveInstructionDescription(input) {
  const card = input.closest('.timeline-card');
  const id = card.dataset.instructionId;
  const description = input.value.trim();
  if (!description) {
    window.PdlcTextarea.refreshTextareaAutosize(input);
    showToast('Описание инструкции обязательно', 'error');
    return;
  }
  const draft = window.PdlcPlatformNavigation.createDraftTracker ? instructionDraft(input) : null;
  if (draft?.uncertain) { showToast('Проверьте состояние инструкции перед повтором сохранения', 'error'); return; }
  const ticket = draft?.beginSave();
  let outcome = 'unknown';
  input.disabled = true;
  try {
    const result = await requestPhaseDetail(phaseApiUrl('' + config.basePath + '/api/instructions/' + id), {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({description: description}),
    }, true);
    if (!result) {
      return;
    }
    const {resp, data} = result;
    if (!resp.ok || !data.ok) {
      if (resp.status < 500) outcome = 'failed';
      showToast(data.error || 'Не удалось сохранить описание', 'error');
      return;
    }
    outcome = 'saved';
    const savedDescription = data.instruction?.description || description;
    input.value = savedDescription;
    input.dataset.originalDescription = savedDescription;
  } finally {
    if (ticket) {
      draft.finishSave(ticket, outcome);
      if (outcome === 'unknown') unknownInstructionSaves.set(id, {ticket, draft, input, description, previous: input.dataset.originalDescription});
      updatePhaseSaveStatus();
    }
    input.disabled = false;
    window.PdlcTextarea.refreshTextareaAutosize(input);
  }
}

function openInstructionSkillEditor(button) {
  const form = button.closest('.timeline-card').querySelector('.skill-add-form');
  if (form.closest('.timeline-card').dataset.skillSaving === 'true') return;
  button.hidden = true;
  form.hidden = false;
  form.querySelector('.skill-candidate').focus();
}

function closeInstructionSkillEditor(form) {
  const card = form.closest('.timeline-card');
  if (card.dataset.skillSaving === 'true') return;
  form.querySelector('.skill-candidate').value = '';
  form.hidden = true;
  const trigger = card.querySelector('.skill-add-trigger');
  trigger.hidden = false;
  trigger.focus();
}

function renderInstructionSkills(card, skills) {
  const template = document.getElementById('instruction-skill-chip-template');
  const chips = skills.map(skill => {
    const chip = template.content.firstElementChild.cloneNode(true);
    const label = chip.querySelector('.instruction-skill-name');
    label.dataset.instructionSkill = skill;
    const rename = label.querySelector('.skill-rename-btn');
    rename.textContent = skill;
    rename.value = skill;
    rename.setAttribute('aria-label', 'Переименовать навык ' + skill + ' в инструкции ' + card.dataset.stepNum);
    const editor = chip.querySelector('.skill-rename-input');
    editor.value = editor.defaultValue = skill;
    editor.setAttribute('aria-label', 'Новое название навыка ' + skill + ' в инструкции ' + card.dataset.stepNum);
    editor.size = Math.max(3, Math.min(32, Array.from(skill).length + 1));
    const remove = chip.querySelector('.skill-remove-btn');
    remove.value = skill;
    remove.setAttribute('aria-label', 'Убрать навык ' + skill + ' из инструкции ' + card.dataset.stepNum);
    remove.setAttribute('title', 'Убрать навык ' + skill);
    return chip;
  });
  const list = card.querySelector('.instruction-skill-labels');
  const addItem = list.querySelector('.skill-add-item');
  list.replaceChildren(...chips, addItem);
}

async function saveInstructionSkills(card, skills) {
  if (card.dataset.skillSaving === 'true') return false;
  card.dataset.skillSaving = 'true';
  const widget = card.querySelector('.instruction-skills');
  widget.setAttribute('aria-busy', 'true');
  widget.querySelectorAll('button,input').forEach(control => { control.disabled = true; });
  try {
    const result = await requestPhaseDetail(phaseApiUrl(config.basePath + '/api/instructions/' + card.dataset.instructionId), {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({skills}),
    });
    if (!result) return false;
    const {resp, data} = result;
    if (!resp.ok || !data.ok) { showToast(data.error || 'Не удалось сохранить навыки', 'error'); return false; }
    if (String(data.instruction?.id) !== card.dataset.instructionId || !Array.isArray(data.instruction?.skills)
        || data.instruction.skills.some(skill => typeof skill !== 'string')) {
      mutationNeedsReadback = true;
      mutationRequiresReload = true;
      updatePhaseSaveStatus();
      showToast('Не удалось подтвердить сохранённые навыки. Проверьте состояние.', 'error');
      return false;
    }
    renderInstructionSkills(card, normalizeSkillNames(data.instruction.skills));
    return true;
  } finally {
    delete card.dataset.skillSaving;
    widget.removeAttribute('aria-busy');
    widget.querySelectorAll('button,input').forEach(control => { control.disabled = false; });
  }
}

async function addSkillToInstruction(input) {
  const card = input.closest('.timeline-card');
  const skill = String(input.value || '').trim();
  if (!skill || card.dataset.skillSaving === 'true') return;
  const existing = Array.from(card.querySelectorAll('[data-instruction-skill]'), item => item.dataset.instructionSkill);
  if (await saveInstructionSkills(card, normalizeSkillNames([...existing, skill]))) {
    closeInstructionSkillEditor(input.closest('.skill-add-form'));
    window.PdlcPlatformNavigation.refreshDrafts?.();
  }
}

function openInstructionSkillRename(button) {
  const chip = button.closest('.instruction-skill-chip');
  if (chip.closest('.timeline-card').dataset.skillSaving === 'true') return;
  const input = chip.querySelector('.skill-rename-input');
  input.value = button.value;
  input.dataset.originalSkill = button.value;
  chip.querySelector('.instruction-skill-name').hidden = true;
  input.hidden = false;
  input.focus();
  input.select();
}

function cancelInstructionSkillRename(input) {
  const chip = input.closest('.instruction-skill-chip');
  input.value = input.dataset.originalSkill;
  input.hidden = true;
  chip.querySelector('.instruction-skill-name').hidden = false;
}

async function saveInstructionSkillRename(input, focusAfter = false) {
  const card = input.closest('.timeline-card');
  if (input.hidden || card.dataset.skillSaving === 'true') return;
  const previous = input.dataset.originalSkill, value = input.value.trim();
  if (!value || value === previous) {
    cancelInstructionSkillRename(input);
    if (focusAfter) input.closest('.instruction-skill-chip').querySelector('.skill-rename-btn').focus();
    return;
  }
  const skills = Array.from(card.querySelectorAll('[data-instruction-skill]'), item => item.dataset.instructionSkill);
  if (skills.includes(value)) { showToast('Такой навык уже добавлен', 'error'); return; }
  if (await saveInstructionSkills(card, skills.map(skill => skill === previous ? value : skill))) {
    if (focusAfter) Array.from(card.querySelectorAll('.skill-rename-btn')).find(button => button.value === value)?.focus();
    window.PdlcPlatformNavigation.refreshDrafts?.();
  }
}

async function removeSkillFromInstruction(button) {
  const card = button.closest('.timeline-card');
  const skill = button.value;
  const existing = Array.from(card.querySelectorAll('[data-instruction-skill]'), item => item.dataset.instructionSkill);
  if (await saveInstructionSkills(card, existing.filter(name => name !== skill))) {
    const form = card.querySelector('.skill-add-form');
    (form.hidden ? card.querySelector('.skill-add-trigger') : form.querySelector('.skill-candidate')).focus();
  }
}

/* ---------- Checks & Evidence ---------- */
function syncTextItemList(list) {
  const count = list.closest('.wiki-section')?.querySelector('.count');
  const itemCount = list.querySelectorAll('li:not(.empty-state)').length;
  if (count) count.textContent = String(itemCount);
  if (itemCount === 0 && !list.querySelector('.empty-state')) {
    const empty = document.createElement('li');
    empty.className = 'empty-state';
    empty.appendChild(document.getElementById(list.id + '-empty-template').content.cloneNode(true));
    list.appendChild(empty);
  }
}

async function saveNewTextItem(input) {
  if (!input.value.trim()) {
    await deleteItem(input);
    return;
  }
  scheduleSave();
}

async function deleteItem(btn) {
  const li = btn.closest('li');
  const list = li?.closest('ul');
  if (!li || !list) return;
  const nextSibling = li.nextSibling;
  li.querySelectorAll('textarea[data-base-autosize]').forEach(window.PdlcTextarea.destroyTextareaAutosize);
  li.remove();
  syncTextItemList(list);
  if (!await savePhase()) {
    const empty = list.querySelector('.empty-state');
    if (empty) empty.remove();
    if (nextSibling && nextSibling.parentNode === list) list.insertBefore(li, nextSibling);
    else list.appendChild(li);
    li.querySelectorAll('textarea[data-base-autosize]').forEach(window.PdlcTextarea.initTextareaAutosize);
    syncTextItemList(list);
  }
}

function appendTextItem(listId) {
  const list = document.getElementById(listId);
  const empty = list.querySelector('.empty-state');
  if (empty) empty.remove();
  const li = document.getElementById(listId + '-item-template').content.firstElementChild.cloneNode(true);
  list.appendChild(li);
  syncTextItemList(list);
  window.PdlcTextarea.initTextareaAutosize(li.querySelector('textarea'));
  li.querySelector('textarea')?.focus();
}

function addCheck() { appendTextItem('checks-list'); }
function addEvidence() { appendTextItem('evidence-list'); }

/* ---------- Debounced phase meta save ---------- */
let _saveTimer = null;
let _phaseSaveQueue = Promise.resolve(true);
function scheduleSave() {
  if (savingStopped) return;
  notePhaseEdit();
  if (_saveTimer) clearTimeout(_saveTimer);
  _saveTimer = setTimeout(() => { _saveTimer = null; void savePhase(); }, 400);
}

function savePhase() {
  notePhaseEdit();
  if (phaseDraft?.uncertain) { showToast('Сначала проверьте результат предыдущего сохранения', 'error'); return Promise.resolve(false); }
  const queued = _phaseSaveQueue.then(() => savingStopped ? false : persistPhase());
  _phaseSaveQueue = queued.catch(() => false);
  return queued;
}

async function persistPhase() {
  if (phaseDraft?.uncertain) return false;
  const header = document.querySelector('.wiki-header');
  const meta = {};
  header.querySelectorAll('[data-field]').forEach((inp) => {
    meta[inp.dataset.field] = inp.value;
  });

  const data = {
    name: meta.name,
    description: meta.description || '',
    checks: [],
    evidence: [],
  };

  const submittedRows = {checks: [], evidence: []};
  for (const field of ['checks', 'evidence']) {
    for (const li of document.querySelectorAll('#' + field + '-list li:not(.empty-state)')) {
      const description = li.querySelector('[data-field="description"]')?.value.trim();
      if (!description) {
        if (li.dataset.id) {
          showToast('Заполните описание или удалите строку кнопкой ×', 'error');
          return false;
        }
        continue;
      }
      data[field].push({id: li.dataset.id ? Number(li.dataset.id) : null, description});
      submittedRows[field].push(li);
    }
  }

  const ticket = phaseDraft?.beginSave();
  updatePhaseSaveStatus();
  let outcome = 'unknown';
  try {
    const resp = await fetch(phaseApiUrl('' + config.basePath + '/api/phases/' + phaseId), {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data),
    });
    if (!resp.ok) { if (resp.status < 500) outcome = 'failed'; showToast('Ошибка сохранения', 'error'); return false; }
    const result = await resp.json();
    if (!result.ok) { outcome = 'failed'; showToast(result.error || 'Ошибка сохранения', 'error'); return false; }
    for (const field of ['checks', 'evidence']) {
      const ids = result.ids?.[field];
      if (!Array.isArray(ids) || ids.length !== submittedRows[field].length) {
        showToast('Не удалось подтвердить сохранённые строки', 'error');
        return false;
      }
    }
    for (const field of ['checks', 'evidence']) {
      result.ids[field].forEach((id, i) => {
        submittedRows[field][i].setAttribute('data-id', String(id));
      });
    }
    outcome = 'saved';
    confirmedPhase = {...data};
    for (const field of ['checks', 'evidence']) confirmedPhase[field] = data[field].map((row, index) => ({...row, id: result.ids[field][index]}));
    showToast('Сохранено', 'success');
    return true;
  } catch (_error) {
    showToast('Результат сохранения неизвестен. Проверьте состояние перед повтором.', 'error');
    return false;
  } finally {
    if (ticket) {
      phaseDraft.finishSave(ticket, outcome);
      if (outcome === 'unknown') unknownPhaseSave = {ticket, payload: data, rows: submittedRows};
      updatePhaseSaveStatus();
    }
  }
}

async function saveEditorChanges() {
  savingStopped = false;
  await savePhase();
  for (const input of document.querySelectorAll('.timeline-name-input')) {
    const draft = instructionDraft(input);
    if (draft.dirty && !draft.pending && !draft.uncertain) await saveInstructionDescription(input);
  }
}

function phaseMatches(actual, expected) {
  return actual.name === expected.name && (actual.description || '') === (expected.description || '')
    && ['checks', 'evidence'].every(field => actual[field].length === expected[field].length
      && expected[field].every((row, index) => actual[field][index].description === row.description && (row.id == null || Number(actual[field][index].id) === Number(row.id))));
}
async function reconcilePhaseSave() {
  const unknown = unknownPhaseSave;
  if (!unknown && !unknownInstructionSaves.size && !mutationNeedsReadback && !mutationRequiresReload) return;
  try {
    const response = await fetch(phaseApiUrl('' + config.basePath + '/api/phases/' + phaseId));
    if (!response.ok) throw new Error('Readback unavailable');
    const result = await response.json();
    if (!result.ok) throw new Error('Readback failed');
    for (const [id, saved] of unknownInstructionSaves) {
      const instruction = result.phase.instructions?.find(item => String(item.id) === id);
      if (!instruction || (instruction.description !== saved.description && instruction.description !== saved.previous)) continue;
      const matches = instruction.description === saved.description;
      saved.draft.reconcile(saved.ticket, matches);
      saved.input.dataset.originalDescription = instruction.description;
      unknownInstructionSaves.delete(id);
    }
    updatePhaseSaveStatus();
    if (!unknown && !unknownInstructionSaves.size && (mutationNeedsReadback || mutationRequiresReload)) {
      mutationNeedsReadback = false;
      // Readback precedes a fresh server view. No uncertain mutation is replayed.
      window.PdlcPlatformNavigation.reload();
      return;
    }
    if (!unknown) {
      showToast(unknownInstructionSaves.size ? 'Состояние инструкции отличается. Черновик сохранён.' : 'Состояние инструкций проверено. Несохранённые правки можно отправить повторно.', unknownInstructionSaves.size ? 'error' : 'success');
      return;
    }
    const matches = phaseMatches(result.phase, unknown.payload);
    if (!matches && (!confirmedPhase || !phaseMatches(result.phase, confirmedPhase))) {
      showToast('Серверное состояние отличается. Черновик сохранён; проверьте изменения перед повтором.', 'error');
      return;
    }
    if (matches) {
      for (const field of ['checks', 'evidence']) result.phase[field].forEach((row, index) => unknown.rows[field][index].setAttribute('data-id', String(row.id)));
    }
    phaseDraft.reconcile(unknown.ticket, matches);
    confirmedPhase = result.phase;
    unknownPhaseSave = null;
    updatePhaseSaveStatus();
    showToast(matches ? 'Сохранение подтверждено' : 'Изменения не записаны. Черновик сохранён; повторите сохранение.', matches ? 'success' : 'error');
  } catch (_error) { showToast('Не удалось проверить сохранение. Черновик сохранён.', 'error'); }
}

page.ready(() => {
  phaseDraft = window.PdlcPlatformNavigation.createDraftTracker();
  phaseSignature = currentPhaseSignature();
  confirmedPhase = {name: document.querySelector('.wiki-header [data-field="name"]').value, description: document.querySelector('.wiki-header [data-field="description"]').value,
    checks: [...document.querySelectorAll('#checks-list [data-field]')].map(input => ({id: Number(input.closest('li').dataset.id) || null, description: input.value.trim()})),
    evidence: [...document.querySelectorAll('#evidence-list [data-field]')].map(input => ({id: Number(input.closest('li').dataset.id) || null, description: input.value.trim()}))};
  initializePhaseOutline();
  renderInstructionTimeline(getInstructionItems());
  updateInstructionControls();
});
page.on(document,'submit',event=>{
  const form = event.target.closest?.('.skill-add-form');
  if (!form) return;
  event.preventDefault();
  void addSkillToInstruction(form.querySelector('.skill-candidate'));
});
page.on(document,'keydown',event=>{
  if(event.target.matches?.('.skill-rename-input')) {
    if(event.key==='Enter') { event.preventDefault(); void saveInstructionSkillRename(event.target, true); }
    else if(event.key==='Escape') {
      event.preventDefault(); event.stopPropagation();
      const chip=event.target.closest('.instruction-skill-chip');
      cancelInstructionSkillRename(event.target); chip.querySelector('.skill-rename-btn').focus();
    }
    return;
  }
  if (event.key !== 'Escape' || !event.target.matches?.('.skill-candidate')) return;
  event.preventDefault(); event.stopPropagation();
  closeInstructionSkillEditor(event.target.closest('.skill-add-form'));
});
page.on(document,'focusout',event=>{
  if(!event.target.matches?.('.skill-rename-input') || event.target.hidden) return;
  const remove=event.relatedTarget?.closest?.('.skill-remove-btn');
  if(remove?.closest('.instruction-skill-chip')===event.target.closest('.instruction-skill-chip')) return;
  void saveInstructionSkillRename(event.target);
});
page.on(document,'click',event=>{
  const skillButton=event.target.closest?.('.skill-add-trigger,.skill-rename-btn,.skill-remove-btn');
  if(skillButton){
    if(skillButton.disabled)return;
    if(skillButton.matches('.skill-remove-btn'))void removeSkillFromInstruction(skillButton);
    else if(skillButton.matches('.skill-add-trigger'))openInstructionSkillEditor(skillButton);
    else openInstructionSkillRename(skillButton);
    return;
  }
  const button=event.target.closest?.('.instruction-card-actions button');
  if(!button||button.disabled)return;
  if(button.matches('.phase-add-btn'))void addInstructionAfter(button);
  else if(button.matches('.move-up-btn'))void moveInstruction(button,-1);
  else if(button.matches('.move-down-btn'))void moveInstruction(button,1);
  else if(button.matches('.execution-toggle'))void toggleInstructionType(button);
  else if(button.matches('.phase-delete-btn'))void deleteInstruction(button);
});
page.on(document,'input', (event) => {
  if (event.target.matches('.timeline-name-input')) instructionDraft(event.target).edit();
  else if (event.target.closest('.wiki-header, #checks-list, #evidence-list')) notePhaseEdit();
});
window.discardWorkflowDraft = () => { savingStopped = true; if (_saveTimer) clearTimeout(_saveTimer); _saveTimer = null; };
{% else %}
page.ready(()=>{
  const select=document.getElementById('phaseSectionSelect');
  select?.addEventListener('change',()=>{
    document.getElementById(select.value)?.scrollIntoView({block:'start'});
  });
});
{% endif %}

page.expose({
addCheck:typeof addCheck==='function'?addCheck:undefined,
addEvidence:typeof addEvidence==='function'?addEvidence:undefined,
addInstructionAfter:typeof addInstructionAfter==='function'?addInstructionAfter:undefined,
addInstructionLast:typeof addInstructionLast==='function'?addInstructionLast:undefined,
addSkillToInstruction:typeof addSkillToInstruction==='function'?addSkillToInstruction:undefined,
appendTextItem:typeof appendTextItem==='function'?appendTextItem:undefined,
currentPhaseSignature:typeof currentPhaseSignature==='function'?currentPhaseSignature:undefined,
deleteInstruction:typeof deleteInstruction==='function'?deleteInstruction:undefined,
deleteItem:typeof deleteItem==='function'?deleteItem:undefined,
escapeHtml:typeof escapeHtml==='function'?escapeHtml:undefined,
getInstructionItems:typeof getInstructionItems==='function'?getInstructionItems:undefined,
initializePhaseOutline:typeof initializePhaseOutline==='function'?initializePhaseOutline:undefined,
instructionDraft:typeof instructionDraft==='function'?instructionDraft:undefined,
jumpToPhaseSection:typeof jumpToPhaseSection==='function'?jumpToPhaseSection:undefined,
moveInstruction:typeof moveInstruction==='function'?moveInstruction:undefined,
normalizeSkillNames:typeof normalizeSkillNames==='function'?normalizeSkillNames:undefined,
notePhaseEdit:typeof notePhaseEdit==='function'?notePhaseEdit:undefined,
persistInstructionOrder:typeof persistInstructionOrder==='function'?persistInstructionOrder:undefined,
persistPhase:typeof persistPhase==='function'?persistPhase:undefined,
phaseApiUrl:typeof phaseApiUrl==='function'?phaseApiUrl:undefined,
phaseMatches:typeof phaseMatches==='function'?phaseMatches:undefined,
reconcilePhaseSave:typeof reconcilePhaseSave==='function'?reconcilePhaseSave:undefined,
releasePhaseSectionNavigationLock:typeof releasePhaseSectionNavigationLock==='function'?releasePhaseSectionNavigationLock:undefined,
removeSkillFromInstruction:typeof removeSkillFromInstruction==='function'?removeSkillFromInstruction:undefined,
renderInstructionTimeline:typeof renderInstructionTimeline==='function'?renderInstructionTimeline:undefined,
requestPhaseDetail:typeof requestPhaseDetail==='function'?requestPhaseDetail:undefined,
restorePhaseSectionFromLocation:typeof restorePhaseSectionFromLocation==='function'?restorePhaseSectionFromLocation:undefined,
saveEditorChanges:typeof saveEditorChanges==='function'?saveEditorChanges:undefined,
saveInstructionDescription:typeof saveInstructionDescription==='function'?saveInstructionDescription:undefined,
saveNewTextItem:typeof saveNewTextItem==='function'?saveNewTextItem:undefined,
savePhase:typeof savePhase==='function'?savePhase:undefined,
scheduleSave:typeof scheduleSave==='function'?scheduleSave:undefined,
setActivePhaseSection:typeof setActivePhaseSection==='function'?setActivePhaseSection:undefined,
syncPhaseSectionUrl:typeof syncPhaseSectionUrl==='function'?syncPhaseSectionUrl:undefined,
syncTextItemList:typeof syncTextItemList==='function'?syncTextItemList:undefined,
toggleInstructionType:typeof toggleInstructionType==='function'?toggleInstructionType:undefined,
updateInstructionControls:typeof updateInstructionControls==='function'?updateInstructionControls:undefined,
updatePhaseSaveStatus:typeof updatePhaseSaveStatus==='function'?updatePhaseSaveStatus:undefined,
});
page.handlesHistory=true;
page.busy=()=>typeof mutationPending!=='undefined'&&(mutationPending>0||instructionOrderSaving||!!phaseDraft?.pending||[...instructionDrafts.values()].some(draft=>draft.pending));
};
})();
