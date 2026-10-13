// This module is also exported verbatim to the server-rendered Base consumers.
export const PLATFORM_PROTOCOL = 'sdlc.platform.v1'
/** Transport immutable namespace references without guessing a destination ID. */
export function transportNamespaceLocation(value, search) {
  const target = new URL(value, 'https://relative.invalid')
  const source = new URLSearchParams(search)
  for (const key of ['registry_instance_id', 'namespace_id', 'project_scope']) {
    target.searchParams.delete(key)
    for (const item of source.getAll(key)) target.searchParams.append(key, item)
  }
  return /^https?:\/\//.test(value) ? target.href : target.pathname + target.search + target.hash
}
// Vite can prebundle ./ui, ./sso and ./platform independently. The client belongs
// to this document, not to a particular copy of the package entry point.
const productKey = Symbol.for('sdlc.platform.product.v1')

export function routePath(value, origin) {
  const url = new URL(value, origin)
  if (url.origin !== origin || url.username || url.password || value.includes('\\')) throw new Error('Недопустимый маршрут приложения.')
  if (['/login', '/register', '/logout', '/sso/callback'].includes(url.pathname.replace(/\/+$/, ''))) throw new Error('Технический маршрут не является экраном приложения.')
  return url.pathname + url.search + url.hash
}

export function getPlatformProduct() { return typeof window === 'undefined' ? null : window[productKey] || null }

export function connectPlatformProduct({ serviceKey, portalOrigin, window: target = window }) {
  if (target.parent === target || !portalOrigin) return null
  const origin = new URL(portalOrigin).origin
  if (target[productKey]) return target[productKey]
  let attemptId = null
  let status = { ready: false, error: null }
  let check = () => status
  let navigate = null
  let publicPath = null
  let services = []
  let currentRoute = target.location.pathname + target.location.search + target.location.hash
  let disposed = false
  let loginRoute = null
  let leaveGeneration = 0
  const guards = new Set()
  const readinessSources = new Set()
  const committedCallbacks = new Set()
  const retireCallbacks = new Set()
  const listeners = new Set()
  const send = (type, payload = {}) => {
    if (!disposed) target.parent.postMessage({ protocol: PLATFORM_PROTOCOL, serviceKey, attemptId, type, ...payload }, origin)
  }
  const publish = () => {
    if (!attemptId) return
    if (loginRoute) { send('login-required', { route: loginRoute }); return }
    const next = checkAll()
    send(next.error ? 'error' : next.ready ? 'ready' : 'pending', next.error ? { message: next.error } : {})
  }
  const checkAll = () => {
    const primary = check()
    if (!primary.ready || primary.error) return primary
    for (const source of readinessSources) {
      const next = source()
      if (!next.ready || next.error) return next
    }
    return primary
  }
  const receive = async event => {
    const message = event.data
    if (event.origin !== origin || event.source !== target.parent || !message || message.protocol !== PLATFORM_PROTOCOL || message.serviceKey !== serviceKey) return
    if (message.type === 'initialize' && typeof message.attemptId === 'string' && typeof message.publicPath === 'string' && Array.isArray(message.services)) {
      attemptId = message.attemptId
      publicPath = message.publicPath
      services = message.services
      for (const listener of listeners) listener()
      publish()
      return
    }
    if (!attemptId || message.attemptId !== attemptId) return
    if (message.type === 'activate') {
      const next = checkAll()
      send(next.ready && !next.error ? 'activated' : 'pending')
    } else if (message.type === 'prepare-leave' && typeof message.transitionId === 'string') {
      const transitionId = message.transitionId
      const generation = ++leaveGeneration
      let allowed = true
      try { for (const guard of guards) { if (!await guard.check()) { allowed = false; break } } } catch { allowed = false }
      if (disposed || generation !== leaveGeneration) return
      if (allowed && !disposed) target.document.documentElement.inert = true
      send('leave-result', { transitionId, allowed })
    } else if (message.type === 'committed') {
      for (const callback of committedCallbacks) callback()
    } else if (message.type === 'retire') {
      leaveGeneration++
      for (const callback of retireCallbacks) callback()
      send('retired')
      product.dispose()
    } else if (message.type === 'resume') {
      leaveGeneration++
      for (const guard of guards) guard.cancel()
      target.document.documentElement.inert = false
    }
  }
  target.addEventListener('message', receive)
  const leavePage = event => {
    if (event.persisted) return
    for (const callback of retireCallbacks) callback()
    product.dispose()
  }
  target.addEventListener('pagehide', leavePage)
  const product = {
    serviceKey,
    portalOrigin: origin,
    get route() { return currentRoute },
    get services() { return services },
    get publicPath() { return publicPath },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    readiness(next, predicate) { status = next; check = predicate || (() => status); publish() },
    addReadinessSource(source) { readinessSources.add(source); publish(); return () => { readinessSources.delete(source); queueMicrotask(publish) } },
    refreshReadiness() { publish() },
    onCommitted(callback) { committedCallbacks.add(callback); return () => committedCallbacks.delete(callback) },
    onRetire(callback) { retireCallbacks.add(callback); return () => retireCallbacks.delete(callback) },
    reportRoute(path, replace = false) { currentRoute = routePath(path, target.location.origin); send('route', { route: currentRoute, replace }) },
    requestNavigation(url, { replace = false } = {}) { send('navigate', { url, replace }) },
    recheckAuthorization() { send('navigate', { url: new URL(currentRoute, target.location.origin).href, replace: true, recheckAuth: true }) },
    setNavigator(handler) { navigate = handler },
    navigate(url, options) { if (navigate) navigate(url, options); else this.requestNavigation(new URL(url, target.location.origin).href, options) },
    addLeaveGuard(check, cancel = () => {}) { const guard = { check, cancel }; guards.add(guard); return () => guards.delete(guard) },
    endingSession(url) { send('session-ending', { url }) },
    requireLogin(route) { loginRoute = route; publish() },
    dispose() { disposed = true; target.removeEventListener('message', receive); target.removeEventListener('pagehide', leavePage); listeners.clear(); guards.clear(); readinessSources.clear(); committedCallbacks.clear(); retireCallbacks.clear(); if (target[productKey] === this) delete target[productKey] },
  }
  target[productKey] = product
  send('connect')
  return product
}

export function platformNavigate(url, options = {}) {
  const product = getPlatformProduct()
  if (product) product.navigate(url, options)
  else if (options.replace) window.location.replace(url)
  else window.location.assign(url)
}

export function platformReload() { platformNavigate(window.location.href, { replace: true }) }

export function capturePlatformReturn(portalOrigin) {
  if (!portalOrigin || window.parent !== window || window.location.pathname !== '/login') return
  const path = new URLSearchParams(window.location.search).get('platform_return')
  if (!path || !path.startsWith('/') || path.startsWith('//') || path.includes('\\')) return
  const origin = new URL(portalOrigin).origin
  try { sessionStorage.setItem('sdlc.platform.return', JSON.stringify({ origin, path, createdAt: Date.now() })) } catch { /* Standalone login remains available. */ }
}

export function finishPlatformLogin(portalOrigin) {
  if (!portalOrigin || window.parent !== window) return false
  try {
    const raw = sessionStorage.getItem('sdlc.platform.return')
    sessionStorage.removeItem('sdlc.platform.return')
    if (!raw) return false
    const value = JSON.parse(raw)
    const origin = new URL(portalOrigin).origin
    const age = Date.now() - value.createdAt
    if (value.origin !== origin || typeof value.path !== 'string' || !value.path.startsWith('/') || value.path.startsWith('//') || value.path.includes('\\') || !Number.isFinite(value.createdAt) || age < 0 || age > 600000) return false
    window.location.replace(origin + value.path)
    return true
  } catch { return false }
}
