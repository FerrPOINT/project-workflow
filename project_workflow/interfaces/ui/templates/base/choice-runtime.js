/** @typedef { { renderOption?: (option: HTMLOptionElement, mode: 'value' | 'option') => Node } } ChoiceConfig */
/** @typedef { { refresh: () => void, destroy: () => void } } ChoiceController */
/** @type {WeakMap<HTMLSelectElement, ChoiceController>} */
const controls = new WeakMap()
let sequence = 0

/** Enhance one native backing control. Domain data and handlers remain with the caller.
 * @param {HTMLSelectElement} control
 * @param {ChoiceConfig} [config]
 * @returns {ChoiceController}
 */
export function initChoice(control, config = {}) {
  const installed = controls.get(control)
  if (installed) { installed.refresh(); return installed }
  const doc = control.ownerDocument
  const win = doc.defaultView
  if (!win) throw new Error('Choice needs a live document')
  const original = { hidden: control.hidden, tabIndex: control.getAttribute('tabindex'), ariaHidden: control.getAttribute('aria-hidden'), testId: control.getAttribute('data-testid') }
  const wrapper = doc.createElement('span')
  wrapper.className = 'base-choice-field'
  const trigger = doc.createElement('button')
  trigger.type = 'button'
  trigger.className = 'base-control base-choice-trigger'
  trigger.id = (control.id || `base-choice-${++sequence}`) + '-trigger'
  trigger.setAttribute('role', control.multiple ? 'button' : 'combobox')
  trigger.setAttribute('aria-haspopup', 'listbox')
  trigger.setAttribute('aria-expanded', 'false')
  const summary = doc.createElement('span'); summary.className = 'base-choice-summary'
  const chevron = doc.createElement('span'); chevron.textContent = '⌄'; chevron.setAttribute('aria-hidden', 'true')
  trigger.append(summary, chevron)
  const panel = doc.createElement('div')
  panel.className = 'base-choice-panel base-choice-ssr-panel'
  panel.id = trigger.id + '-options'
  panel.setAttribute('role', 'listbox')
  panel.setAttribute('aria-labelledby', trigger.id)
  if (control.multiple) panel.setAttribute('aria-multiselectable', 'true')
  panel.hidden = true
  trigger.setAttribute('aria-controls', panel.id)
  if (original.testId) trigger.setAttribute('data-testid', original.testId)
  const errorMessage = doc.createElement('span')
  errorMessage.id = trigger.id + '-error'; errorMessage.className = 'base-choice-error'; errorMessage.setAttribute('role', 'alert'); errorMessage.hidden = true
  control.before(wrapper); wrapper.append(trigger, panel, errorMessage)
  let validationShown = false
  let open = false
  let popped = false
  let active = -1
  let buffer = ''
  let typedAt = 0
  /** @type {HTMLButtonElement[]} */
  let items = []
  const abort = new AbortController()
  const listen = (target, event, handler, capture = false) => target.addEventListener(event, handler, { signal: abort.signal, capture })
  const position = () => {
    if (!open) return
    const rect = trigger.getBoundingClientRect()
    const viewport = win.visualViewport
    const width = viewport?.width ?? win.innerWidth
    const height = viewport?.height ?? win.innerHeight
    const above = rect.top > height - rect.bottom && height - rect.bottom < 200
    panel.style.position = 'fixed'
    panel.style.minWidth = Math.min(rect.width, width - 16) + 'px'
    panel.style.width = Math.min(Math.max(rect.width, 180), width - 16) + 'px'
    panel.style.left = Math.max(8, Math.min(rect.left, width - panel.offsetWidth - 8)) + 'px'
    panel.style.maxHeight = Math.max(44, Math.min(320, (above ? rect.top : height - rect.bottom) - 12)) + 'px'
    panel.style.top = (above ? Math.max(8, rect.top - panel.offsetHeight - 4) : rect.bottom + 4) + 'px'
  }
  const close = (focus = false) => {
    open = false; panel.hidden = true; trigger.setAttribute('aria-expanded', 'false')
    if (popped) { panel.hidePopover(); popped = false }
    if (focus) trigger.focus()
  }
  const focusItem = index => {
    if (!items.length) return
    active = (index + items.length) % items.length
    items[active].focus(); items[active].scrollIntoView?.({ block: 'nearest' })
  }
  const show = (last = false) => {
    if (control.matches(':disabled') || open) return
    open = true; panel.hidden = false; trigger.setAttribute('aria-expanded', 'true')
    if (typeof panel.showPopover === 'function') { panel.popover = 'manual'; panel.showPopover(); popped = true }
    position()
    const selected = items.findIndex(item => item.getAttribute('aria-selected') === 'true')
    focusItem(selected < 0 ? last ? items.length - 1 : 0 : selected)
  }
  const choose = option => {
    if (control.matches(':disabled') || option.disabled) return
    const changed = control.multiple || control.value !== option.value
    if (control.multiple) option.selected = !option.selected
    else control.value = option.value
    refresh()
    if (!control.multiple) close(true)
    if (!changed) return
    control.dispatchEvent(new win.Event('input', { bubbles: true }))
    control.dispatchEvent(new win.Event('change', { bubbles: true }))
  }
  function refresh() {
    const focused = /** @type {HTMLElement | null} */ (doc.activeElement)?.dataset.value ?? items[active]?.dataset.value
    trigger.disabled = control.matches(':disabled')
    for (const key of ['aria-label', 'aria-labelledby', 'aria-describedby', 'aria-invalid']) {
      const value = control.getAttribute(key)
      if (value != null) trigger.setAttribute(key, value); else trigger.removeAttribute(key)
    }
    const invalid = validationShown && control.willValidate && !control.validity.valid
    errorMessage.hidden = !invalid
    errorMessage.textContent = invalid ? control.validity.customError ? control.validationMessage : control.multiple ? 'Выберите хотя бы одно значение.' : 'Выберите значение.' : ''
    if (invalid) {
      trigger.setAttribute('aria-invalid', 'true')
      trigger.setAttribute('aria-describedby', [control.getAttribute('aria-describedby'), errorMessage.id].filter(Boolean).join(' '))
    }
    const labels = [...control.labels ?? []]
    if (!trigger.hasAttribute('aria-label') && !trigger.hasAttribute('aria-labelledby')) {
      for (const label of labels) if (!label.id) label.id = `base-choice-label-${++sequence}`
      if (labels.length) trigger.setAttribute('aria-labelledby', labels.map(label => label.id).join(' '))
      else trigger.setAttribute('aria-label', control.dataset.choiceLabel || 'Выбор значения')
    }
    if (!control.multiple) trigger.setAttribute('aria-required', String(control.required))
    else if (control.required) trigger.setAttribute('aria-description', 'Обязательное поле')
    else trigger.removeAttribute('aria-description')
    const selected = [...control.selectedOptions]
    const names = selected.map(option => option.label)
    summary.replaceChildren()
    if (selected.length === 1 && config.renderOption) summary.append(config.renderOption(selected[0], 'value'))
    else summary.textContent = names.length ? names.slice(0, 2).join(', ') + (names.length > 2 ? ` +${names.length - 2}` : '') : control.dataset.placeholder || (control.value ? `${control.value} — недоступно` : 'Выберите значение')
    trigger.title = names.join(', ')
    panel.replaceChildren(); items = []
    for (const option of control.options) {
      const item = doc.createElement('button')
      item.type = 'button'; item.className = 'base-choice-option'; item.tabIndex = -1
      item.dataset.value = option.value; item.disabled = option.disabled || option.parentElement?.tagName === 'OPTGROUP' && /** @type {HTMLOptGroupElement} */ (option.parentElement).disabled
      item.setAttribute('role', 'option'); item.setAttribute('aria-selected', String(option.selected))
      const mark = doc.createElement('span'); mark.className = 'base-choice-indicator'; mark.textContent = option.selected ? '✓' : ''; mark.setAttribute('aria-hidden', 'true')
      item.append(mark, config.renderOption ? config.renderOption(option, 'option') : doc.createTextNode(option.label))
      item.addEventListener('click', () => choose(option))
      panel.append(item)
      if (!item.disabled) items.push(item)
    }
    if (open) { position(); focusItem(Math.max(0, items.findIndex(item => item.dataset.value === focused))) }
    if (trigger.disabled) close()
  }
  listen(trigger, 'click', () => open ? close() : show())
  listen(wrapper, 'keydown', event => {
    if (event.key === 'Escape' && open) { event.preventDefault(); event.stopPropagation(); close(true); return }
    if (event.key === 'Tab' && open) {
      event.preventDefault(); close()
      const scope = trigger.closest('[role="dialog"], [role="alertdialog"], dialog') ?? doc
      const fields = [...scope.querySelectorAll('button, input, select, textarea, a[href], [tabindex]')]
        .filter(element => element instanceof win.HTMLElement && element.tabIndex >= 0 && !element.closest('[hidden], [inert]') && !element.matches(':disabled') && element.getClientRects().length > 0)
      const next = fields[fields.indexOf(trigger) + (event.shiftKey ? -1 : 1)] ?? (scope === doc ? trigger : fields[event.shiftKey ? fields.length - 1 : 0])
      if (next instanceof win.HTMLElement) next.focus()
      return
    }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault()
      if (!open) {
        show(event.key === 'ArrowUp' || event.key === 'End')
        if (event.key === 'Home' || event.key === 'End') focusItem(event.key === 'Home' ? 0 : items.length - 1)
        return
      }
      focusItem(event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : items.indexOf(/** @type {HTMLButtonElement} */ (doc.activeElement)) + (event.key === 'ArrowDown' ? 1 : -1))
    } else if (event.key.length === 1 && !event.ctrlKey && !event.altKey && !event.metaKey && event.key !== ' ') {
      event.preventDefault(); if (!open) show()
      const now = Date.now(); buffer = now - typedAt > 700 ? event.key : buffer + event.key; typedAt = now
      const index = items.findIndex(item => item.textContent?.replace(/^✓/, '').trim().toLocaleLowerCase().startsWith(buffer.toLocaleLowerCase()))
      if (index >= 0) focusItem(index)
    } else if ((event.key === 'Enter' || event.key === ' ') && event.target === trigger) { event.preventDefault(); open ? close() : show() }
  })
  listen(doc, 'pointerdown', event => { if (!wrapper.contains(event.target)) close() })
  listen(doc, 'focusin', event => { if (!wrapper.contains(event.target)) close() })
  listen(win, 'resize', position)
  listen(doc, 'scroll', position, true)
  listen(control, 'change', refresh)
  listen(control, 'invalid', event => { event.preventDefault(); validationShown = true; refresh(); trigger.focus() })
  for (const label of control.labels ?? []) listen(label, 'click', event => { if (!wrapper.contains(event.target) && !event.target.closest?.('a, button, input, select, textarea')) { event.preventDefault(); trigger.focus() } })
  if (control.form) listen(control.form, 'reset', event => queueMicrotask(() => { if (!event.defaultPrevented) { validationShown = false; refresh() } }))
  const controller = { refresh, destroy() {
    close(); abort.abort(); wrapper.remove(); controls.delete(control)
    control.hidden = original.hidden
    if (original.testId) control.setAttribute('data-testid', original.testId)
    for (const [key, value] of [['tabindex', original.tabIndex], ['aria-hidden', original.ariaHidden]])
      if (value == null) control.removeAttribute(key); else control.setAttribute(key, value)
  } }
  try {
    refresh()
    // Commit enhancement only after rendering and listeners succeeded.
    control.removeAttribute('data-testid')
    control.hidden = true; control.tabIndex = -1; control.setAttribute('aria-hidden', 'true')
    controls.set(control, controller)
    return controller
  } catch (error) { controller.destroy(); throw error }
}

/** Refresh after programmatic value/options/disabled changes; never emits input/change.
 * @param {HTMLSelectElement} control */
export function refreshChoice(control) { controls.get(control)?.refresh() }
/** Remove an enhancement and restore its native fallback.
 * @param {HTMLSelectElement} control */
export function destroyChoice(control) { controls.get(control)?.destroy() }
