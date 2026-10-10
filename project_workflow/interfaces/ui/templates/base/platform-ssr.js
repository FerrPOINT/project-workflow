// The exporter and Jinja include this after platform-bridge.js in one module.
export function installServerProduct(runtime, options) {
  window.SdlcPlatformNavigation = { ...window.SdlcPlatformNavigation, navigate: runtime.platformNavigate, reload: runtime.platformReload, saved: () => {}, embedded: false, active: false }
  const client = runtime.connectPlatformProduct(options)
  if (!client) return
  window.SdlcPlatformNavigation.embedded = true
  window.SdlcPlatformNavigation.syncRoute = (url, replace = false, state = null) => {
    history.replaceState(state, '', url)
    client.reportRoute(location.pathname + location.search + location.hash, replace)
  }
  const snapshots = new Map()
  const snapshot = form => JSON.stringify([...new FormData(form)].map(([key, value]) => [key, typeof value === 'string' ? value : value.name]))
  for (const form of document.querySelectorAll('form[data-platform-draft]')) snapshots.set(form, snapshot(form))
  const dirty = () => [...snapshots].some(([form, saved]) => form.isConnected && saved !== snapshot(form))
  document.addEventListener('input', event => {
    if (event.target instanceof Element && event.target.closest('form[data-platform-draft]')) client.refreshReadiness()
  })
  window.SdlcPlatformNavigation.saved = form => { if (form) snapshots.set(form, snapshot(form)) }
  client.addLeaveGuard(() => !dirty() || (options.confirmLeave ? options.confirmLeave() : window.confirm('На странице есть несохранённые изменения. Покинуть страницу?')), options.cancelLeave)
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
      void fetch(url.href, { redirect: 'manual' }).then(response => {
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
