// Request-independent controller; private view data is supplied by the owner HTML.
(function(){
window.WorkflowPageControllers["instructions"] = function(page, config){
const fetch=page.fetch,showToast=page.notify,showRequestError=()=>showToast("Не удалось связаться с сервером","error");

const PHASE_ID = config.phaseId;
const selectedNamespaceId = config.professionId;

function instructionApiUrl(path) {
  const url = new URL(path, window.location.origin);
  if (selectedNamespaceId !== null) {
    url.searchParams.set('namespace_id', String(selectedNamespaceId));
  }
  return url.pathname + url.search;
}

function getRows() {
  return Array.from(document.querySelectorAll('#instructionsLayout .instruction-row'));
}

function renumberRows() {
  getRows().forEach((row, idx) => {
    row.dataset.stepNum = String(idx + 1);
    const num = row.querySelector('.step-num');
    if (num) num.textContent = String(idx + 1);
    row.querySelector('.move-up')?.setAttribute('aria-label', `Поднять инструкцию ${idx + 1} выше`);
    row.querySelector('.move-down')?.setAttribute('aria-label', `Опустить инструкцию ${idx + 1} ниже`);
    row.querySelector('.instruction-text')?.setAttribute('aria-label', `Описание инструкции ${idx + 1}`);
    row.querySelector('.skills-input')?.setAttribute('aria-label', `Навыки инструкции ${idx + 1}`);
    row.querySelector('.type-badge')?.setAttribute('aria-label', `Параллельное выполнение инструкции ${idx + 1}`);
    row.querySelector('.row-actions .icon-btn')?.setAttribute('aria-label', `Удалить инструкцию ${idx + 1}`);
  });
}

function updateTimeline() {
  const layout = document.getElementById('instructionsLayout');
  const rows = getRows();
  layout.innerHTML = '';
  const groups = [];
  rows.forEach((row, idx) => {
    const type = row.querySelector('.type-badge')?.dataset.executionType || 'sync';
    if (idx === 0 || type !== 'parallel') {
      groups.push([row]);
    } else {
      groups[groups.length - 1].push(row);
    }
  });
  groups.forEach(group => {
    const isParallelGroup = group.length > 1;
    const block = document.createElement('div');
    block.className = 'instruction-block' + (isParallelGroup ? ' parallel-group base-card base-card-content' : '');
    if (isParallelGroup) {
      const label = document.createElement('span');
      label.className = 'base-badge parallel-label';
      label.dataset.tone = 'info';
      label.dataset.appearance = 'badge';
      label.textContent = '⚡ параллельно';
      block.appendChild(label);
    }
    group.forEach(row => block.appendChild(row));
    layout.appendChild(block);
  });
  renumberRows();
  updateMoveButtons();
  layout.querySelectorAll('textarea[data-base-autosize]').forEach(field => window.PdlcTextarea?.initTextareaAutosize(field));
}

function updateMoveButtons() {
  const rows = getRows();
  rows.forEach((row, idx) => {
    const up = row.querySelector('.move-up');
    const down = row.querySelector('.move-down');
    if (up) up.disabled = idx === 0;
    if (down) down.disabled = idx === rows.length - 1;
  });
}

async function persistOrder() {
  const ids = getRows().map(r => parseInt(r.dataset.instructionId, 10));
  try {
    const resp = await fetch(instructionApiUrl('' + config.basePath + '/api/phases/' + PHASE_ID + '/instructions/reorder'), {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({instruction_ids: ids}),
    });
    if (!resp.ok) {
      showToast('Не удалось сохранить порядок', 'error');
      return false;
    }
    return true;
  } catch (_error) {
    showToast('Не удалось сохранить порядок', 'error');
    return false;
  }
}

async function moveInstruction(button, dir) {
  const row = button.closest('.instruction-row');
  const rows = getRows();
  const idx = rows.indexOf(row);
  const target = idx + dir;
  if (target < 0 || target >= rows.length) return;
  const reordered = [...rows];
  const [moved] = reordered.splice(idx, 1);
  reordered.splice(target, 0, moved);
  const layout = document.getElementById('instructionsLayout');
  layout.replaceChildren(...reordered);
  updateTimeline();
  if (!await persistOrder()) {
    layout.replaceChildren(...rows);
    updateTimeline();
  }
}

async function requestInstruction(url, options) {
  try {
    const resp = await fetch(url, options);
    const data = await resp.json().catch(() => ({}));
    return {resp, data};
  } catch (_error) {
    showRequestError();
    return null;
  }
}

async function updateInstruction(textarea) {
  const row = textarea.closest('.instruction-row');
  const id = parseInt(row.dataset.instructionId, 10);
  const description = textarea.value.trim();
  if (!description) {
    window.PdlcTextarea.refreshTextareaAutosize(textarea);
    showToast('Описание инструкции обязательно', 'error');
    return;
  }
  textarea.disabled = true;
  try {
    const result = await requestInstruction(instructionApiUrl('' + config.basePath + '/api/instructions/' + id), {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({description: description}),
    });
    if (!result) {
      return;
    }
    const {resp, data} = result;
    if (!resp.ok || !data.ok) {
      showToast(data.error || 'Ошибка сохранения', 'error');
      return;
    }
    const savedDescription = data.instruction?.description || description;
    textarea.value = savedDescription;
    textarea.dataset.originalDescription = savedDescription;
  } finally {
    textarea.disabled = false;
    window.PdlcTextarea.refreshTextareaAutosize(textarea);
  }
}

async function toggleType(badge) {
  const row = badge.closest('.instruction-row');
  const id = parseInt(row.dataset.instructionId, 10);
  const nextType = (badge.dataset.executionType || 'sync') === 'sync' ? 'parallel' : 'sync';
  const result = await requestInstruction(instructionApiUrl('' + config.basePath + '/api/instructions/' + id), {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({execution_type: nextType}),
  });
  if (!result) return;
  const {resp, data} = result;
  if (!resp.ok || !data.ok) {
    showToast(data.error || 'Ошибка сохранения', 'error');
    return;
  }
  badge.dataset.executionType = nextType;
  badge.textContent = nextType === 'parallel' ? 'параллельно' : 'последовательно';
  badge.setAttribute('aria-pressed', String(nextType === 'parallel'));
  updateTimeline();
}

async function deleteInstruction(button) {
  const row = button.closest('.instruction-row');
  const id = parseInt(row.dataset.instructionId, 10);
  if (!await window.PdlcBaseUI.requestConfirmation({eyebrow:'Удаление инструкции',title:'Удалить инструкцию?',message:'Инструкция будет удалена без возможности восстановления.',confirmLabel:'Удалить'})) return;
  const result = await requestInstruction(instructionApiUrl('' + config.basePath + '/api/instructions/' + id), {method: 'DELETE'});
  if (!result) return;
  const {resp, data} = result;
  if (!resp.ok || !data.ok) {
    showToast(data.error || 'Ошибка удаления', 'error');
    return;
  }
  row.querySelectorAll('textarea[data-base-autosize]').forEach(window.PdlcTextarea.destroyTextareaAutosize);
  row.remove();
  updateTimeline();
}

async function addInstruction() {
  const input = document.getElementById('newInstructionText');
  const description = input.value.trim();
  if (!description) return;
  const result = await requestInstruction(instructionApiUrl('' + config.basePath + '/api/instructions'), {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({phase_id: PHASE_ID, description: description}),
  });
  if (!result) return;
  const {resp, data} = result;
  if (!resp.ok || !data.ok) {
    showToast(data.error || 'Ошибка добавления', 'error');
    return;
  }
  window.PdlcPlatformNavigation.reload();
}

async function updateSkills(input) {
  const row = input.closest('.instruction-row');
  const id = parseInt(row.dataset.instructionId, 10);
  const selected = input.value.split(',').map(value => value.trim()).filter(Boolean);
  const result = await requestInstruction(instructionApiUrl('' + config.basePath + '/api/instructions/' + id), {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({skills: selected}),
  });
  if (!result) return;
  const {resp, data} = result;
  if (!resp.ok || !data.ok) {
    showToast(data.error || 'Ошибка сохранения', 'error');
    return;
  }
  window.PdlcPlatformNavigation.reload();
}

page.ready(() => {
  updateMoveButtons();
});

page.expose({
addInstruction:typeof addInstruction==='function'?addInstruction:undefined,
deleteInstruction:typeof deleteInstruction==='function'?deleteInstruction:undefined,
getRows:typeof getRows==='function'?getRows:undefined,
instructionApiUrl:typeof instructionApiUrl==='function'?instructionApiUrl:undefined,
moveInstruction:typeof moveInstruction==='function'?moveInstruction:undefined,
persistOrder:typeof persistOrder==='function'?persistOrder:undefined,
renumberRows:typeof renumberRows==='function'?renumberRows:undefined,
requestInstruction:typeof requestInstruction==='function'?requestInstruction:undefined,
toggleType:typeof toggleType==='function'?toggleType:undefined,
updateInstruction:typeof updateInstruction==='function'?updateInstruction:undefined,
updateMoveButtons:typeof updateMoveButtons==='function'?updateMoveButtons:undefined,
updateSkills:typeof updateSkills==='function'?updateSkills:undefined,
updateTimeline:typeof updateTimeline==='function'?updateTimeline:undefined,
});
page.handlesHistory=false;
page.busy=()=>false;
};
})();
