// Available before product inline startup scripts; the module upgrades it later.
(() => {
  if (window.SdlcPlatformNavigation) return
  const embedded = window.parent !== window && !!document.documentElement.dataset.platformOrigin
  window.SdlcPlatformNavigation = {
    embedded, active: false, saved: () => {},
    navigate: (url, options = {}) => options.replace ? location.replace(url) : location.assign(url),
    reload: () => location.reload(),
    syncRoute: (url, replace = false, state = null) => history[embedded || replace ? 'replaceState' : 'pushState'](state, '', url),
  }
})()
