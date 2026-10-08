(() => {
  if (typeof window === 'undefined' || window.SdlcThemePreference) return
  const cookieName = 'sdlc-ui-theme'
  const eventName = 'sdlc-ui-theme-change'
  const valid = value => ['dark', 'gray', 'light'].includes(value)
  let sessionTheme

  function shared() {
    try {
      const cookie = document.cookie.split(';').map(value => value.trim()).find(value => value.startsWith(cookieName + '='))
      const value = cookie?.slice(cookieName.length + 1)
      if (valid(value)) return value
    } catch { /* Cookies may be blocked. */ }
  }

  function read(legacyKey = 'theme') {
    if (valid(sessionTheme)) return sessionTheme
    const preference = shared()
    if (preference) return preference
    try {
      const value = localStorage.getItem(legacyKey)
      if (valid(value)) return value
    } catch { /* Keep theme controls usable without storage. */ }
    return 'dark'
  }

  function set(value, legacyKey = 'theme') {
    if (!valid(value)) return
    sessionTheme = value
    try {
      document.cookie = cookieName + '=' + value + '; Path=/; Max-Age=31536000; SameSite=Lax' + (location.protocol === 'https:' ? '; Secure' : '')
    } catch { /* The current window retains the selection. */ }
    if (shared() === value) sessionTheme = undefined
    try { localStorage.setItem(legacyKey, value) } catch { /* The shared cookie remains authoritative. */ }
    window.dispatchEvent(new Event(eventName))
  }

  function subscribe(listener) {
    const change = event => {
      if ([...(event.changed || []), ...(event.deleted || [])].some(cookie => cookie.name === cookieName)) {
        sessionTheme = undefined
        listener()
      }
    }
    const visible = () => { if (document.visibilityState === 'visible') listener() }
    window.cookieStore?.addEventListener('change', change)
    window.addEventListener(eventName, listener)
    window.addEventListener('focus', listener)
    window.addEventListener('pageshow', listener)
    document.addEventListener('visibilitychange', visible)
    return () => {
      window.cookieStore?.removeEventListener('change', change)
      window.removeEventListener(eventName, listener)
      window.removeEventListener('focus', listener)
      window.removeEventListener('pageshow', listener)
      document.removeEventListener('visibilitychange', visible)
    }
  }

  window.SdlcThemePreference = { read, set, subscribe }
})()
