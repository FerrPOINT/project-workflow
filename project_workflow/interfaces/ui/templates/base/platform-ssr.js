// The exporter and Jinja include this after platform-bridge.js in one module.
export const unsavedChangesConfirmation = Object.freeze({
  title: 'Покинуть страницу?', message: 'Есть несохранённые изменения.', confirmLabel: 'Покинуть',
})
export function installServerProduct(runtime, options) {
  window.SdlcPlatformNavigation = { ...window.SdlcPlatformNavigation, navigate: runtime.platformNavigate, reload: runtime.platformReload, saved: () => {}, createDraftTracker: runtime.createDraftTracker, embedded: false, active: false }
  const snapshots = new Map()
  const snapshot = form => JSON.stringify([...form.querySelectorAll('input,textarea,select')].map((field, index) => [
    field.name || field.id || index,
    field.type === 'file' ? [...field.files].map(file => [file.name, file.size, file.lastModified])
      : field.tagName === 'SELECT' && field.multiple ? [...field.selectedOptions].map(option => option.value) : field.value,
    ['checkbox', 'radio'].includes(field.type) ? field.checked : null,
  ]))
  for (const form of document.querySelectorAll('form[data-platform-draft]')) snapshots.set(form, snapshot(form))
  const dirty = () => !!options.hasUnsavedChanges?.() || [...snapshots].some(([form, saved]) => form.isConnected && saved !== snapshot(form))
  let pendingLeave = null
  let approvedUnload = false
  const refreshDrafts = () => {
    if (!dirty() && pendingLeave) {
      const finish = pendingLeave; pendingLeave = null
      options.cancelLeave?.(); finish(true)
    }
  }
  window.SdlcPlatformNavigation.refreshDrafts = refreshDrafts
  if (runtime.createDraftTracker) window.SdlcPlatformNavigation.createDraftTracker = () => runtime.createDraftTracker(refreshDrafts)
  window.SdlcPlatformNavigation.saved = form => { if (form) snapshots.set(form, snapshot(form)); refreshDrafts() }
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
  if (!client) {
    const depart = action => { void Promise.resolve(checkLeave()).then(allowed => { if (allowed) { approvedUnload = true; action() } }) }
    window.SdlcPlatformNavigation.navigate = (url, navigationOptions) => depart(() => runtime.platformNavigate(url, navigationOptions))
    window.SdlcPlatformNavigation.reload = () => depart(runtime.platformReload)
    document.addEventListener('click', event => {
      const link = event.target instanceof Element ? event.target.closest('a[href]') : null
      if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.hasAttribute('download') || link.target === '_blank') return
      const url = new URL(link.href)
      if (!['http:', 'https:'].includes(url.protocol) || (url.origin === location.origin && url.pathname === location.pathname && url.search === location.search && url.hash)) return
      event.preventDefault()
      window.SdlcPlatformNavigation.navigate(url.href)
    })
    return
  }
  window.SdlcPlatformNavigation.embedded = true
  window.SdlcPlatformNavigation.syncRoute = (url, replace = false, state = null) => {
    history.replaceState(state, '', url)
    client.reportRoute(location.pathname + location.search + location.hash, replace)
  }
  document.addEventListener('input', event => {
    if (event.target instanceof Element && event.target.closest('form[data-platform-draft]')) client.refreshReadiness()
  })
  client.addLeaveGuard(checkLeave, () => { const finish = pendingLeave; pendingLeave = null; options.cancelLeave?.(); finish?.(false) })
  client.onCommitted(() => { window.SdlcPlatformNavigation.active = true; options.onCommitted?.(); document.querySelector('main')?.focus() })
  const map = () => {
    for (const link of document.querySelectorAll('a[data-platform-service]')) {
      const service = client.services.find(item => item.key === link.dataset.platformService)
      link.hidden = !service
      if (service) link.href = runtime.transportNamespaceLocation(client.portalOrigin + service.path, new URL(client.route, location.origin).search)
    }
  }
  client.subscribe(() => { map(); client.reportRoute(location.pathname + location.search + location.hash, true) }); map()
  document.addEventListener('click', event => {
    const link = event.target instanceof Element ? event.target.closest('a[href]') : null
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
    client.readiness({ ready: !!main?.textContent?.trim(), error: main ? null : 'Основное содержимое страницы отсутствует.' })
  }
  // SSR primary data has already been loaded by the owner before producing HTML.
  if (document.fonts) void document.fonts.ready.then(finish)
  else finish()
}
