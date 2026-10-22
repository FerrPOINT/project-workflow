// The exporter and Jinja include this after platform-bridge.js in one module.
export const unsavedChangesConfirmation = Object.freeze({
  title: 'Покинуть страницу?', message: 'Есть несохранённые изменения.', confirmLabel: 'Покинуть',
})
export function installServerProduct(runtime, options) {
  window.PdlcPlatformNavigation = window.SdlcPlatformNavigation = { ...(window.PdlcPlatformNavigation || window.SdlcPlatformNavigation), navigate: runtime.platformNavigate, reload: runtime.platformReload, saved: () => {}, createDraftTracker: runtime.createDraftTracker, embedded: false, active: false }
  const snapshots = new Map()
  const snapshot = form => JSON.stringify([...form.querySelectorAll('input,textarea,select')].map((field, index) => [
    field.name || field.id || index,
    field.type === 'file' ? [...field.files].map(file => [file.name, file.size, file.lastModified])
      : field.tagName === 'SELECT' && field.multiple ? [...field.selectedOptions].map(option => option.value) : field.value,
    ['checkbox', 'radio'].includes(field.type) ? field.checked : null,
  ]))
  for (const form of document.querySelectorAll('form[data-platform-draft]')) snapshots.set(form, snapshot(form))
  let retired = false
  const dirty = () => !retired && (!!options.hasUnsavedChanges?.() || [...snapshots].some(([form, saved]) => form.isConnected && saved !== snapshot(form)))
  let pendingLeave = null
  let approvedUnload = false
  const refreshDrafts = () => {
    if (!dirty() && pendingLeave) {
      const finish = pendingLeave; pendingLeave = null
      options.cancelLeave?.(); finish(true)
    }
  }
  window.PdlcPlatformNavigation.refreshDrafts = refreshDrafts
  if (runtime.createDraftTracker) window.PdlcPlatformNavigation.createDraftTracker = () => runtime.createDraftTracker(refreshDrafts)
  window.PdlcPlatformNavigation.saved = form => { if (form) snapshots.set(form, snapshot(form)); refreshDrafts() }
  window.addEventListener('beforeunload', event => { if (!approvedUnload && dirty()) { event.preventDefault(); event.returnValue = '' } })
  document.addEventListener('input', event => {
    if (event.target instanceof Element && event.target.closest('form[data-platform-draft]')) refreshDrafts()
  })
  const checkLeave = () => {
    if (!dirty()) return true
    return new Promise(resolve => {
      pendingLeave?.(false); pendingLeave = resolve
      Promise.resolve(options.confirmLeave ? options.confirmLeave() : window.confirm('На странице есть несохранённые изменения. Покинуть страницу?')).then(allowed => {
        if (pendingLeave !== resolve) return
        pendingLeave = null; if (allowed) options.onDiscard?.(); resolve(allowed)
      }, () => { if (pendingLeave === resolve) { pendingLeave = null; resolve(false) } })
    })
  }
  const client = runtime.connectPlatformProduct(options)
  const retireAccess = () => {
    if (retired) return
    retired = true; approvedUnload = true
    const finish = pendingLeave; pendingLeave = null
    document.documentElement.setAttribute('data-pdlc-access-pending', '')
    document.body.replaceChildren()
    try {
      options.cancelLeave?.(); finish?.(false)
      options.onDiscard?.()
    } finally {
      snapshots.clear()
      try { client?.readiness({ ready: false }) } finally { runtime.platformReload() }
    }
  }
  const access = options.admission ? installAdmissionWindow(options.admission, retireAccess) : null
  if (!client) {
    const depart = action => { void Promise.resolve(checkLeave()).then(allowed => { if (allowed) { approvedUnload = true; action() } }) }
    window.PdlcPlatformNavigation.navigate = (url, navigationOptions) => depart(() => runtime.platformNavigate(url, navigationOptions))
    window.PdlcPlatformNavigation.reload = () => depart(runtime.platformReload)
    document.addEventListener('click', event => {
      const link = event.target instanceof Element ? /** @type {HTMLAnchorElement} */ (event.target.closest('a[href]')) : null
      if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.hasAttribute('download') || link.target === '_blank') return
      const url = new URL(link.href)
      if (!['http:', 'https:'].includes(url.protocol) || (url.origin === location.origin && url.pathname === location.pathname && url.search === location.search && url.hash)) return
      event.preventDefault()
      window.PdlcPlatformNavigation.navigate(url.href)
    })
    return
  }
  window.PdlcPlatformNavigation.embedded = true
  window.PdlcPlatformNavigation.syncRoute = (url, replace = false, state = null) => {
    history.replaceState(state, '', url)
    client.reportRoute(location.pathname + location.search + location.hash, replace)
  }
  document.addEventListener('input', event => {
    if (event.target instanceof Element && event.target.closest('form[data-platform-draft]')) client.refreshReadiness()
  })
  client.addLeaveGuard(checkLeave, () => { const finish = pendingLeave; pendingLeave = null; options.cancelLeave?.(); finish?.(false) })
  client.onCommitted(() => { window.PdlcPlatformNavigation.active = true; options.onCommitted?.(); document.querySelector('main')?.focus() })
  const map = () => {
    for (const link of /** @type {NodeListOf<HTMLAnchorElement>} */ (document.querySelectorAll('a[data-platform-service]'))) {
      const service = client.services.find(item => item.key === link.dataset.platformService)
      link.hidden = !service
      if (service) link.href = runtime.transportNamespaceLocation(client.portalOrigin + service.path, new URL(client.route, location.origin).search)
    }
  }
  client.subscribe(() => { map(); client.reportRoute(location.pathname + location.search + location.hash, true) }); map()
  document.addEventListener('click', event => {
    const link = event.target instanceof Element ? /** @type {HTMLAnchorElement} */ (event.target.closest('a[href]')) : null
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.hasAttribute('download') || link.target === '_blank') return
    const url = new URL(link.href)
    if (url.origin !== location.origin && url.origin !== client.portalOrigin && !client.services.some(service => service.origin === url.origin)) return
    if (url.origin === location.origin && url.pathname === '/logout' && options.logoutUrl) {
      event.preventDefault()
      // The owner clears its HttpOnly session cookie before the parent leaves.
      void Promise.resolve(checkLeave()).then(allowed => allowed ? fetch(url.href, { redirect: 'manual' }) : null).then(response => {
        if (!response) return
        if (response.type === 'opaqueredirect') client.endingSession(options.logoutUrl)
        else client.readiness({ ready: false, error: 'Не удалось завершить сессию.' })
      }).catch(() => client.readiness({ ready: false, error: 'Не удалось завершить сессию.' }))
      return
    }
    if (url.origin === location.origin && ['/login', '/logout', '/sso/callback'].includes(url.pathname)) return
    event.preventDefault()
    link.closest('details')?.removeAttribute('open')
    client.requestNavigation(url.href)
  })
  if (document.documentElement.hasAttribute('data-platform-login-required')) {
    client.requireLogin('/')
    return
  }
  if (options.error) { client.readiness({ ready: false, error: options.error }); return }
  const finish = () => {
    const main = document.querySelector('main')
    client.readiness({ ready: !retired && (!access || access.current()) && !!main?.textContent?.trim(), error: main ? null : 'Основное содержимое страницы отсутствует.' })
  }
  // SSR primary data has already been loaded by the owner before producing HTML.
  if (document.fonts) void document.fonts.ready.then(finish)
  else finish()
}


// The product supplies only display metadata from its already-authorized owner endpoint.
// Initial SSR metadata is anchored to navigation start (performance time zero), never receipt.
function installAdmissionWindow(options, retire) {
  let deadline = 0, stamp = null, enforced = null, stopped = false, suspended = false
  let expiration, renewal, pending
  const current = () => !stopped && !suspended && (enforced === false || performance.now() < deadline)
  const stop = () => {
    if (stopped) return
    stopped = true; clearTimeout(expiration); clearTimeout(renewal); pending?.abort()
    retire()
  }
  const accept = (value, started) => {
    if (!value || typeof value !== 'object' || Array.isArray(value)
      || Object.keys(value).sort().join(',') !== 'enforced,remaining_millis,schema_version,scope_revision'
      || value.schema_version !== 1 || typeof value.enforced !== 'boolean') throw Error('Invalid admission window')
    if (value.enforced) {
      if (!Number.isInteger(value.remaining_millis) || value.remaining_millis < 1 || value.remaining_millis > 60000
        || typeof value.scope_revision !== 'string' || !/^[a-f0-9]{64}$/.test(value.scope_revision)) throw Error('Invalid admission window')
    } else if (value.remaining_millis !== null || value.scope_revision !== null) throw Error('Invalid legacy window')
    if (enforced !== null && (enforced !== value.enforced || stamp !== value.scope_revision)) { stop(); return }
    enforced = value.enforced; stamp = value.scope_revision
    deadline = enforced ? started + value.remaining_millis : Infinity
    if (!current()) { stop(); return }
    clearTimeout(expiration); clearTimeout(renewal)
    if (enforced) expiration = setTimeout(stop, Math.max(0, deadline - performance.now()))
    renewal = setTimeout(refresh, enforced ? Math.min(30000, Math.max(1, (deadline - performance.now()) / 2)) : 30000)
    document.documentElement.removeAttribute('data-pdlc-access-pending')
  }
  const refresh = async () => {
    if (!current()) { stop(); return }
    const started = performance.now()
    pending = new AbortController()
    try {
      const value = await options.load(pending.signal)
      if (!stopped && !suspended) accept(value, started)
    } catch {
      // A failed renewal cannot extend the previous proof.
      if (suspended) return
      if (!current()) stop()
      else renewal = setTimeout(refresh, Math.min(1000, enforced ? deadline - performance.now() : 1000))
    } finally { pending = null }
  }
  try { accept(options.initial, 0) } catch { stop() }
  window.addEventListener('pagehide', () => {
    suspended = true
    document.documentElement.setAttribute('data-pdlc-access-pending', '')
    clearTimeout(expiration); clearTimeout(renewal); pending?.abort()
  })
  window.addEventListener('pageshow', event => { if (event.persisted) stop() })
  return { current }
}
