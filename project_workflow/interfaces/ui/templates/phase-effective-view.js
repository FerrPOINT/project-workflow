/* Raw editors stay inert until the server has resolved the instruction scope. */
document.addEventListener('DOMContentLoaded', async () => {
  const view = document.getElementById('phaseEffectiveView');
  const editor = document.getElementById('phaseStoredEditor');
  const status = document.getElementById('phaseViewStatus');
  const instructionsOnly = view.dataset.instructionsOnly === 'true';

  function appendSections(target, phase, projected) {
    const sections = [['instructions', 'Инструкции', projected ? 'step' : 'description']];
    if (!instructionsOnly) {
      sections.push(['checks', 'Проверки', 'description'], ['evidence', 'Подтверждения', projected ? 'item' : 'description']);
    }
    for (const [key, title, field] of sections) {
      const section = document.createElement('section');
      section.className = 'base-page-stack';
      const heading = document.createElement('h3');
      heading.className = 'base-section-title';
      heading.textContent = title;
      const list = document.createElement(key === 'instructions' ? 'ol' : 'ul');
      list.className = 'base-prose';
      for (const item of phase[key] || []) {
        const row = document.createElement('li');
        const text = document.createElement('p');
        text.style.whiteSpace = 'pre-wrap';
        text.style.overflowWrap = 'anywhere';
        text.textContent = item[field];
        row.appendChild(text);
        if (key === 'instructions' && item.execution_type === 'parallel') {
          const execution = document.createElement('p');
          execution.textContent = 'Параллельно';
          row.appendChild(execution);
        }
        if (key === 'instructions' && item.skills?.length) {
          const skills = document.createElement('p');
          skills.textContent = item.skills.join(', ');
          row.appendChild(skills);
        }
        list.appendChild(row);
      }
      section.append(heading, list);
      target.appendChild(section);
    }
  }

  try {
    const response = await fetch(view.dataset.apiUrl, {cache: 'no-store'});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error('unavailable');
    if (!Object.hasOwn(data, 'effective_view')) {
      editor.hidden = false;
      editor.inert = false;
      view.hidden = true;
      editor.querySelectorAll('textarea[data-base-autosize]').forEach(field => window.PdlcTextarea?.initTextareaAutosize(field));
      return;
    }
    const effective = data.effective_view;
    if (effective?.interaction_protocol !== 'configured-cli-v1' || effective.read_only !== true || !effective.phase) {
      throw new Error('invalid effective view');
    }
    document.getElementById('phaseEffectiveTitle').textContent = effective.phase.name;
    document.getElementById('phaseEffectiveDescription').textContent = effective.phase.description;
    appendSections(document.getElementById('phaseEffectiveSections'), effective.phase, true);
    appendSections(document.getElementById('phaseStoredSections'), {
      ...data.phase, instructions: data.instructions || data.phase.instructions,
    }, false);
    // No editable copy of the historical catalog remains in the active DOM.
    editor.remove();
    document.getElementById('phaseEffectiveContent').hidden = false;
    status.hidden = true;
  } catch (_) {
    status.textContent = 'Не удалось проверить инструкции. Обновите страницу.';
    status.setAttribute('role', 'alert');
  }
});
